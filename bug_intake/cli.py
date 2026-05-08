from __future__ import annotations

import argparse
from importlib import resources
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Iterable

from bug_intake.actions import BugIntakeActions
from bug_intake.channels.gmail import GmailChannelAdapter
from bug_intake.config import BugIntakeConfig
from bug_intake.issue_providers.github_gh import GitHubGhProvider
from bug_intake.log import ProcessingLog
from bug_intake.models import NormalizedMessage, ProcessingRecord


ENV_EXAMPLE = """BUG_INTAKE_CHANNEL=gmail
BUG_INTAKE_GMAIL_LABEL=Bug Reports
BUG_INTAKE_GMAIL_CREDENTIALS_PATH=./secrets/credentials.json
BUG_INTAKE_GMAIL_TOKEN_PATH=./secrets/token.json
BUG_INTAKE_GITHUB_REPO=owner/repo
BUG_INTAKE_LOG_PATH=./.bug-intake/processing_log.json
BUG_INTAKE_PENDING_ISSUES_DIR=./.bug-intake/pending_issues
BUG_INTAKE_REQUIRE_APPROVAL_FOR_REPLIES=true
"""


def _load_skill_template() -> str:
    return resources.files("bug_intake.templates").joinpath("SKILL.md").read_text(
        encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bug-intake", description="Sifter bug intake CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init", help="Initialize bug-intake files")
    init_cmd.add_argument("--force", action="store_true", help="Overwrite generated templates")
    init_cmd.add_argument(
        "--headless",
        action="store_true",
        help="Use console OAuth flow during guided Gmail setup",
    )
    init_cmd.set_defaults(func=cmd_init)

    fetch_cmd = sub.add_parser("fetch", help="Fetch new bug reports from channel")
    fetch_cmd.add_argument("--headless", action="store_true", help="Use console OAuth flow")
    fetch_cmd.add_argument("--max-results", type=int, default=50)
    fetch_cmd.add_argument("--env-file", default=".env.bug_intake")
    fetch_cmd.set_defaults(func=cmd_fetch)

    act_cmd = sub.add_parser("act", help="Execute triage actions")
    act_cmd.add_argument("--env-file", default=".env.bug_intake")
    act_sub = act_cmd.add_subparsers(dest="act_command", required=True)

    create_issue = act_sub.add_parser("create_issue", help="Create GitHub issue")
    create_issue.add_argument("--message-id", required=True)
    create_issue.add_argument("--title", required=True)
    create_issue.add_argument("--body", required=True)
    create_issue.add_argument("--notes", default="")
    create_issue.set_defaults(func=cmd_act_create_issue)

    reply = act_sub.add_parser("reply", help="Reply to reporter")
    reply.add_argument("--message-id", required=True)
    reply.add_argument("--body", required=True)
    reply.add_argument("--notes", default="")
    reply.set_defaults(func=cmd_act_reply)

    ignore = act_sub.add_parser("ignore", help="Mark message ignored")
    ignore.add_argument("--message-id", required=True)
    ignore.add_argument("--notes", default="")
    ignore.set_defaults(func=cmd_act_ignore)

    notify = act_sub.add_parser("notify", help="Notify reporters when linked issues are closed")
    notify.add_argument("--template", default=None, help="Optional custom notification body")
    notify.set_defaults(func=cmd_act_notify)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    root = Path.cwd()
    bug_dir = root / ".bug-intake"
    pending_dir = bug_dir / "pending_issues"
    skill_path = root / ".cursor" / "skills" / "bug-intake" / "SKILL.md"
    env_path = root / ".env.bug_intake"
    env_example = root / ".env.bug_intake.example"
    log_path = bug_dir / "processing_log.json"
    gitignore_path = root / ".gitignore"

    bug_dir.mkdir(parents=True, exist_ok=True)
    pending_dir.mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "skills" / "bug-intake").mkdir(parents=True, exist_ok=True)

    _write_file(skill_path, _load_skill_template(), force=args.force)
    _write_file(env_example, ENV_EXAMPLE, force=args.force)
    if not log_path.exists():
        ProcessingLog(path=log_path).save()
    _ensure_gitignore_entries(
        gitignore_path,
        [
            ".env.bug_intake",
            ".bug-intake/",
            "secrets/token.json",
        ],
    )

    existing = _read_existing_env(env_path)
    if existing and not args.force:
        print(f"Existing config detected at `{env_path}`. Re-running setup with saved values as defaults.")
        print("Press Enter to keep an existing answer, or type a new one to update.")
        print("")

    config_values = _run_guided_setup(
        root=root,
        headless=args.headless,
        defaults=existing,
    )
    _write_file(env_path, _render_env(config_values), force=True)

    print("")
    print("Sifter bug-intake is ready.")
    print("Your config is saved in `.env.bug_intake`.")
    print("")
    print("From here on, you don't need this CLI directly.")
    print("Open a Cursor chat in this repo and just say things like:")
    print('  - "fetch latest bugs"')
    print('  - "check the bug inbox"')
    print('  - "triage bug reports"')
    print('  - "notify reporters of fixed bugs"')
    print("")
    print("The Cursor agent will use the bug-intake skill to do the rest.")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    config = BugIntakeConfig.load(args.env_file)
    if config.channel != "gmail":
        raise RuntimeError(f"Unsupported channel '{config.channel}'. Only gmail is implemented.")

    processing_log = ProcessingLog.load(config.log_path)
    channel = GmailChannelAdapter(
        credentials_path=config.gmail_credentials_path,
        token_path=config.gmail_token_path,
        headless=args.headless,
    )
    messages = channel.fetch_messages(label=config.gmail_label, max_results=args.max_results)
    new_messages = [
        message for message in messages if processing_log.get(message.message_id) is None
    ]

    for message in new_messages:
        record = _record_from_message(message)
        record.append_history(action="fetched", notes="Imported from Gmail")
        processing_log.upsert(record)
        _write_pending_message(config.pending_issues_dir, message)
    processing_log.save()

    print(
        f"Fetched {len(messages)} messages, added {len(new_messages)} new "
        "records to processing log."
    )
    if new_messages:
        print(f"Pending triage files written to `{config.pending_issues_dir}`")
    return 0


def cmd_act_create_issue(args: argparse.Namespace) -> int:
    actions = _build_actions(args.env_file)
    result = actions.create_issue(
        message_id=args.message_id, title=args.title, body=args.body, notes=args.notes
    )
    print(result.detail)
    return 0


def cmd_act_reply(args: argparse.Namespace) -> int:
    actions = _build_actions(args.env_file)
    result = actions.reply(message_id=args.message_id, body=args.body, notes=args.notes)
    print(result.detail)
    return 0


def cmd_act_ignore(args: argparse.Namespace) -> int:
    actions = _build_actions(args.env_file)
    result = actions.ignore(message_id=args.message_id, notes=args.notes)
    print(result.detail)
    return 0


def cmd_act_notify(args: argparse.Namespace) -> int:
    actions = _build_actions(args.env_file)
    results = actions.notify_closed_issues(template=args.template)
    if not results:
        print("No closed issues pending notification.")
        return 0
    for result in results:
        print(f"{result.message_id}: {result.detail}")
    return 0


def _build_actions(env_file: str) -> BugIntakeActions:
    config = BugIntakeConfig.load(env_file)
    if config.channel != "gmail":
        raise RuntimeError(f"Unsupported channel '{config.channel}'. Only gmail is implemented.")

    processing_log = ProcessingLog.load(config.log_path)
    channel = GmailChannelAdapter(
        credentials_path=config.gmail_credentials_path,
        token_path=config.gmail_token_path,
        headless=False,
    )
    issue_provider = GitHubGhProvider(repo=config.github_repo)
    return BugIntakeActions(
        processing_log=processing_log,
        channel=channel,
        issue_provider=issue_provider,
    )


def _record_from_message(message: NormalizedMessage) -> ProcessingRecord:
    return ProcessingRecord(
        message_id=message.message_id,
        thread_id=message.thread_id,
        reporter_email=message.from_email,
        reporter_name=message.from_name,
        subject=message.subject,
        snippet=message.snippet,
        body_text=message.body_text,
        received_at=message.received_at,
    )


_MESSAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


def _write_pending_message(directory: Path, message: NormalizedMessage) -> None:
    if not _MESSAGE_ID_PATTERN.fullmatch(message.message_id):
        raise ValueError(
            f"Refusing to write pending message: invalid message_id '{message.message_id}'."
        )
    directory.mkdir(parents=True, exist_ok=True)
    output = (directory / f"{message.message_id}.json").resolve()
    if directory.resolve() not in output.parents:
        raise ValueError(
            f"Refusing to write pending message outside `{directory}`: {output}"
        )
    with output.open("w", encoding="utf-8") as handle:
        json.dump(message.to_dict(), handle, indent=2)
        handle.write("\n")


def _write_file(path: Path, contents: str, *, force: bool) -> None:
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents.rstrip() + "\n", encoding="utf-8")


def _ensure_gitignore_entries(path: Path, entries: Iterable[str]) -> None:
    if path.exists():
        existing = path.read_text(encoding="utf-8").splitlines()
    else:
        existing = []

    missing = [entry for entry in entries if entry not in existing]
    if not missing:
        return

    lines = existing + ([""] if existing and existing[-1] != "" else [])
    lines.extend(missing)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _read_existing_env(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _run_guided_setup(
    *, root: Path, headless: bool, defaults: dict[str, str] | None = None
) -> dict[str, str]:
    defaults = defaults or {}
    print("Sifter bug-intake guided setup")
    print("-----------------------------")
    print("This will configure Gmail + GitHub and write `.env.bug_intake`.")
    print("")

    print(
        "Need a Gmail OAuth client (Desktop app) JSON.\n"
        "If you don't have one yet, create it at https://console.cloud.google.com/\n"
        "  -> APIs & Services -> Credentials -> Create OAuth client ID -> Desktop app,\n"
        "  then download the JSON and pass its path below.\n"
    )
    credentials_path = _prompt_path(
        prompt="Path to Gmail OAuth credentials JSON",
        default=defaults.get("BUG_INTAKE_GMAIL_CREDENTIALS_PATH", "./secrets/credentials.json"),
        root=root,
        must_exist=True,
        require_file=True,
    )
    _validate_gmail_credentials_file(credentials_path)

    token_path = _prompt_path(
        prompt="Path to store Gmail OAuth token (file path, not a folder)",
        default=defaults.get("BUG_INTAKE_GMAIL_TOKEN_PATH", "./secrets/token.json"),
        root=root,
        must_exist=False,
        require_file=True,
        default_filename="token.json",
    )
    channel = GmailChannelAdapter(
        credentials_path=credentials_path,
        token_path=token_path,
        headless=headless,
    )
    account_email = _authenticate_with_retry(channel, credentials_path=credentials_path)
    print(f"Gmail authentication verified for: {account_email or 'authenticated account'}")

    labels = set(channel.list_labels())
    label_default = defaults.get("BUG_INTAKE_GMAIL_LABEL", "Bug Reports")
    gmail_label = _prompt_non_empty("Gmail label to monitor", default=label_default)
    while gmail_label not in labels:
        print(f"Label '{gmail_label}' was not found in this Gmail account.")
        if _prompt_yes_no("Use this label anyway?", default=False):
            break
        gmail_label = _prompt_non_empty("Gmail label to monitor", default=label_default)

    repo_default = defaults.get("BUG_INTAKE_GITHUB_REPO", "")
    github_repo = _prompt_non_empty("GitHub repository (owner/repo or URL)", default=repo_default)
    github_repo = _normalize_github_repo(github_repo)
    _ensure_gh_ready()
    _verify_github_repo_exists(github_repo)
    print(f"GitHub repository verified: {github_repo}")

    run_test = _prompt_yes_no("Run a safe test fetch now (no replies sent)?", default=True)
    if run_test:
        test_messages = channel.fetch_messages(label=gmail_label, max_results=5)
        print(
            f"Test fetch succeeded: found {len(test_messages)} message(s) "
            f"for label '{gmail_label}'."
        )

    return {
        "BUG_INTAKE_CHANNEL": "gmail",
        "BUG_INTAKE_GMAIL_LABEL": gmail_label,
        "BUG_INTAKE_GMAIL_CREDENTIALS_PATH": _to_relative(credentials_path, root),
        "BUG_INTAKE_GMAIL_TOKEN_PATH": _to_relative(token_path, root),
        "BUG_INTAKE_GITHUB_REPO": github_repo,
        "BUG_INTAKE_LOG_PATH": "./.bug-intake/processing_log.json",
        "BUG_INTAKE_PENDING_ISSUES_DIR": "./.bug-intake/pending_issues",
        "BUG_INTAKE_REQUIRE_APPROVAL_FOR_REPLIES": "true",
    }


def _prompt_non_empty(prompt: str, default: str = "") -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{prompt}{suffix}: ").strip()
        if not value and default:
            return default
        if value:
            return value
        print("Value is required.")


def _prompt_yes_no(prompt: str, *, default: bool) -> bool:
    options = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{options}]: ").strip().lower()
    if raw == "":
        return default
    return raw in {"y", "yes"}


def _prompt_path(
    *,
    prompt: str,
    default: str,
    root: Path,
    must_exist: bool,
    require_file: bool = False,
    default_filename: str | None = None,
) -> Path:
    while True:
        raw = _prompt_non_empty(prompt, default=default)
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (root / path).resolve()
        if path.is_dir() and require_file:
            if default_filename:
                path = path / default_filename
                print(f"Interpreting as file: {path}")
            else:
                print(f"Path is a directory; please give a file path: {path}")
                continue
        if must_exist and not path.exists():
            print(f"File not found: {path}")
            continue
        if require_file and path.exists() and not path.is_file():
            print(f"Path exists but is not a file: {path}")
            continue
        return path


def _authenticate_with_retry(channel: GmailChannelAdapter, *, credentials_path: Path) -> str:
    while True:
        try:
            return channel.ensure_authenticated()
        except Exception as exc:
            message = str(exc)
            if "accessNotConfigured" in message or "has not been used in project" in message:
                project_id = _extract_gcp_project_id(credentials_path)
                link = (
                    f"https://console.developers.google.com/apis/api/gmail.googleapis.com/overview?project={project_id}"
                    if project_id
                    else "https://console.cloud.google.com/apis/library/gmail.googleapis.com"
                )
                print("")
                print("Gmail API is not enabled on this Google Cloud project.")
                print(f"Open this link in your browser and click ENABLE:\n  {link}")
                print("Wait ~30 seconds after enabling for it to propagate.")
                input("Press Enter to retry, or Ctrl+C to abort: ")
                continue
            raise


def _extract_gcp_project_id(credentials_path: Path) -> str | None:
    try:
        payload = json.loads(credentials_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    block = payload.get("installed") or payload.get("web") or {}
    return block.get("project_id") or None


def _validate_gmail_credentials_file(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gmail credentials file is not valid JSON: {path}") from exc

    if not isinstance(payload, dict) or ("installed" not in payload and "web" not in payload):
        raise RuntimeError(
            "Gmail credentials JSON must contain either 'installed' or 'web' OAuth config."
        )


def _normalize_github_repo(value: str) -> str:
    trimmed = value.strip().rstrip("/")
    if trimmed.startswith("git@github.com:"):
        trimmed = trimmed.removeprefix("git@github.com:")
    if trimmed.startswith("https://github.com/"):
        trimmed = trimmed.removeprefix("https://github.com/")
    if trimmed.startswith("http://github.com/"):
        trimmed = trimmed.removeprefix("http://github.com/")
    if trimmed.endswith(".git"):
        trimmed = trimmed[: -len(".git")]
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", trimmed):
        raise RuntimeError(f"Invalid GitHub repository value: '{value}'")
    return trimmed


def _ensure_gh_ready() -> None:
    while shutil.which("gh") is None:
        print("")
        print("GitHub CLI `gh` is not installed.")
        print("Install it with one of:")
        print("  macOS (Homebrew):  brew install gh")
        print("  macOS (MacPorts):  sudo port install gh")
        print("  Other platforms:   https://github.com/cli/cli#installation")
        input("Press Enter to retry once installed, or Ctrl+C to abort: ")

    try:
        status = subprocess.run(
            ["gh", "auth", "status"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("`gh auth status` timed out.") from exc
    if status.returncode == 0:
        return
    print("GitHub CLI is not authenticated. Starting `gh auth login`...")
    login = subprocess.run(["gh", "auth", "login"], check=False)
    if login.returncode != 0:
        raise RuntimeError("`gh auth login` failed. Authenticate and run init again.")


def _verify_github_repo_exists(repo: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+", repo):
        raise RuntimeError(f"Refusing to query gh with suspicious repo value: '{repo}'")
    cmd = ["gh", "repo", "view", repo, "--json", "nameWithOwner"]
    try:
        completed = subprocess.run(
            cmd, check=False, capture_output=True, text=True, timeout=20
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("`gh repo view` timed out.") from exc
    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or "unknown gh error"
        raise RuntimeError(f"Could not access repository '{repo}': {error}")


def _to_relative(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return str(path)
    return f"./{relative.as_posix()}"


def _render_env(values: dict[str, str]) -> str:
    order = [
        "BUG_INTAKE_CHANNEL",
        "BUG_INTAKE_GMAIL_LABEL",
        "BUG_INTAKE_GMAIL_CREDENTIALS_PATH",
        "BUG_INTAKE_GMAIL_TOKEN_PATH",
        "BUG_INTAKE_GITHUB_REPO",
        "BUG_INTAKE_LOG_PATH",
        "BUG_INTAKE_PENDING_ISSUES_DIR",
        "BUG_INTAKE_REQUIRE_APPROVAL_FOR_REPLIES",
    ]
    lines = [f"{key}={values[key]}" for key in order]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
