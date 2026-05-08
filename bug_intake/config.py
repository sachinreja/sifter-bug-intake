from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import os


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_env_file(env_path: str | Path, override: bool = False) -> None:
    """Minimal .env loader: KEY=VALUE per line, comments allowed.

    Implemented in-tree to avoid pulling in third-party dotenv parsers
    (and their CVE surface) for what is effectively trivial config.
    """
    path = Path(env_path)
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class BugIntakeConfig:
    channel: str
    gmail_label: str
    gmail_credentials_path: Path
    gmail_token_path: Path
    github_repo: str
    log_path: Path
    pending_issues_dir: Path
    require_approval_for_replies: bool

    @classmethod
    def load(cls, env_path: str | Path = ".env.bug_intake") -> "BugIntakeConfig":
        _load_env_file(env_path, override=False)
        return cls(
            channel=os.getenv("BUG_INTAKE_CHANNEL", "gmail"),
            gmail_label=os.getenv("BUG_INTAKE_GMAIL_LABEL", "Bug Reports"),
            gmail_credentials_path=Path(
                os.getenv("BUG_INTAKE_GMAIL_CREDENTIALS_PATH", "./secrets/credentials.json")
            ),
            gmail_token_path=Path(os.getenv("BUG_INTAKE_GMAIL_TOKEN_PATH", "./secrets/token.json")),
            github_repo=os.getenv("BUG_INTAKE_GITHUB_REPO", "").strip(),
            log_path=Path(os.getenv("BUG_INTAKE_LOG_PATH", "./.bug-intake/processing_log.json")),
            pending_issues_dir=Path(
                os.getenv("BUG_INTAKE_PENDING_ISSUES_DIR", "./.bug-intake/pending_issues")
            ),
            require_approval_for_replies=_read_bool(
                "BUG_INTAKE_REQUIRE_APPROVAL_FOR_REPLIES", True
            ),
        )
