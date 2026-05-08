# Sifter Bug Intake

`bug-intake` is a local-first CLI that turns unstructured bug reports in your
inbox into structured GitHub issues, with the **Cursor agent** doing the
triage. You install it once, run a guided `init`, and after that you talk to
your Cursor agent in plain English ("check the bug inbox", "notify reporters
of fixed bugs") — the agent uses the bug-intake skill to drive the CLI on
your behalf.

The flow today:

```
Gmail label → bug-intake fetch → Cursor agent triages → bug-intake act → GitHub
                                                                ↓
                                               processing_log.json (audit)
```

---

## Status / Roadmap

Bug-intake is built around two pluggable interfaces so new channels and issue
trackers can be added without touching the rest of the system.

### Available today (v1)

- **Channel:** Gmail (`GmailChannelAdapter`)
- **Issue provider:** GitHub via `gh` CLI (`GitHubGhProvider`)
- **Triage agent:** Cursor (via `.cursor/skills/bug-intake/SKILL.md`)

### Planned

- **Channels:** Slack, Microsoft Teams, Linear inbox, generic webhook
- **Issue providers:** Linear, Jira, GitLab
- **Agents:** Claude Code, OpenAI / Codex, generic OpenAI-compatible

The `ChannelAdapter` and `IssueProvider` base classes in
`bug_intake/channels/base.py` and `bug_intake/issue_providers/base.py` are the
extension points — implementing one is the entire integration.

---

## Prerequisites

Before you run `bug-intake init`, get these in place:

### 1. Python 3.10+ (recommended)

3.9 works but pulls in older `requests`/`filelock` with known CVEs (see
[SECURITY.md](./SECURITY.md)). On macOS:

```bash
brew install python@3.11
```

### 2. A Gmail account + a label that holds bug reports

- In Gmail, create (or pick) a label such as `Bug Reports` or `Sifter Support`.
  - Web UI → left sidebar → **+** next to "Labels" → name it.
  - Use a Gmail filter so reports auto-apply this label, e.g.
    `to:bugs@yourcompany.com → Apply label "Bug Reports"`.
- Make sure messages actually land in the label before fetching.
- Label name validation: letters, digits, spaces, `_`, `-`, `/`, `&` only.

### 3. A Google Cloud OAuth client (Desktop app)

bug-intake reads/sends Gmail using your account via OAuth. You need a JSON
client file:

1. Open https://console.cloud.google.com/ and select / create a project.
2. **APIs & Services → Library → Gmail API → Enable.**
3. **APIs & Services → Credentials → Create credentials → OAuth client ID.**
4. Application type: **Desktop app**. Name it anything.
5. Click **Download JSON**. Save it somewhere private (e.g. `~/Downloads/...`
   or `./secrets/credentials.json`).

Required scopes (granted automatically the first time you authorize):

- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/gmail.send`

The token is saved on disk (default `./secrets/token.json`) with
`chmod 0600` permissions.

### 4. GitHub CLI (`gh`)

bug-intake creates GitHub issues by shelling out to `gh`. Install + log in:

```bash
brew install gh
gh auth login            # init runs this for you if you skip it
```

You need write access to the target repo (`gh repo view <owner>/<repo>`
should succeed for your account).

### 5. Cursor (today's only supported agent)

- Install Cursor: https://cursor.com
- Open this repo in Cursor.
- The skill at `.cursor/skills/bug-intake/SKILL.md` is committed to the repo
  so anyone in the team gets it for free.

---

## Install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
bug-intake --help
```

---

## Guided Setup

```bash
bug-intake init
```

The wizard walks you through everything:

1. Path to your Gmail OAuth credentials JSON (validated).
2. Path to store the OAuth token (defaults to `./secrets/token.json`, 0600).
3. Opens the browser for Google OAuth consent and saves the token.
4. Lists your Gmail labels and asks which one to monitor.
5. Asks for the GitHub repository (`owner/repo` or full URL).
6. Runs `gh auth login` if needed and verifies the repo with `gh repo view`.
7. Optional safe test fetch (no replies sent).
8. Writes `.env.bug_intake`.

If a step fails (Gmail API not enabled, `gh` not installed, etc.) the wizard
shows the exact link or command, **waits** for you to fix it, and retries on
Enter — you don't lose progress.

Re-running `init` later prefills every prompt from your saved
`.env.bug_intake`, so it becomes a quick "press Enter through".

---

## Daily Use (via Cursor agent)

You don't typically run the CLI directly. Open a Cursor chat in this repo
and use natural-language triggers from the skill:

- "check the bug inbox"
- "triage bug reports"
- "process latest bugs"
- "notify reporters of fixed bugs"

The agent will:

1. Run `bug-intake fetch --headless` to pull new messages.
2. Read each pending message under `.bug-intake/pending_issues/`.
3. Decide per message: `create_issue`, `reply`, or `ignore`.
4. Run the appropriate `bug-intake act ...` command.
5. Report back in plain English with issue URLs.

Replies and notifications are **never** sent automatically — they only fire
when the agent (or you) explicitly invokes `act reply` or `act notify`.

---

## CLI Reference (for debugging / direct use)

| Command | Purpose |
| --- | --- |
| `bug-intake init` | Guided setup wizard. |
| `bug-intake fetch --headless [--max-results N]` | Pull new messages from the channel. Idempotent by `message_id`. |
| `bug-intake act create_issue --message-id ID --title T --body B [--notes N]` | Create a GitHub issue, link it to the message. |
| `bug-intake act reply --message-id ID --body B [--notes N]` | Send an email reply to the original reporter. |
| `bug-intake act ignore --message-id ID [--notes N]` | Mark the message ignored. |
| `bug-intake act notify [--template T]` | For each linked-but-not-yet-notified record, check `gh issue view`; if closed, email the reporter. |

State lives under `.bug-intake/`:

- `processing_log.json` — append-only audit (every action, with timestamp +
  notes, including a per-record `history` array).
- `pending_issues/<message_id>.json` — normalized message payloads ready for
  triage.

Configuration lives in `.env.bug_intake`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `BUG_INTAKE_CHANNEL` | `gmail` | Which channel adapter to use. |
| `BUG_INTAKE_GMAIL_LABEL` | `Bug Reports` | Label to monitor. |
| `BUG_INTAKE_GMAIL_CREDENTIALS_PATH` | `./secrets/credentials.json` | OAuth client JSON path. |
| `BUG_INTAKE_GMAIL_TOKEN_PATH` | `./secrets/token.json` | OAuth token store (0600). |
| `BUG_INTAKE_GITHUB_REPO` | _(required)_ | `owner/repo`. |
| `BUG_INTAKE_LOG_PATH` | `./.bug-intake/processing_log.json` | Audit log. |
| `BUG_INTAKE_PENDING_ISSUES_DIR` | `./.bug-intake/pending_issues` | Per-message JSON. |
| `BUG_INTAKE_REQUIRE_APPROVAL_FOR_REPLIES` | `true` | Reserved for future automation. |

---

## Architecture

```
bug_intake/
  cli.py                     # argparse entry, init wizard, command wiring
  config.py                  # in-tree .env loader + BugIntakeConfig
  models.py                  # NormalizedMessage, ProcessingRecord, ActionEntry
  log.py                     # ProcessingLog (JSON-backed)
  actions.py                 # BugIntakeActions: create_issue / reply / ignore / notify
  channels/
    base.py                  # ChannelAdapter interface
    gmail.py                 # GmailChannelAdapter
  issue_providers/
    base.py                  # IssueProvider interface
    github_gh.py             # GitHubGhProvider (uses `gh` CLI)
  templates/
    SKILL.md                 # canonical Cursor skill (also installed by init)
.cursor/skills/bug-intake/
  SKILL.md                   # operational runbook the Cursor agent reads
```

**To add a new channel** (e.g. Slack), implement `ChannelAdapter`:

- `fetch_messages(*, label, max_results) -> list[NormalizedMessage]`
- `send_reply(*, record, body) -> str`

**To add a new issue provider** (e.g. Linear), implement `IssueProvider`:

- `create_issue(*, title, body) -> CreatedIssue`
- `get_issue_status(*, issue_number) -> IssueStatus`

Then add a config switch in `cli.py`'s factory (`_build_actions`,
`cmd_fetch`).

---

## Security

See [SECURITY.md](./SECURITY.md). Highlights:

- OAuth tokens written `0600`, never logged.
- All `gh` calls use argument lists (no shell injection) with 30s timeouts.
- Gmail label and `message_id` are validated before use.
- No `pickle`; logs are JSON.
- Run `pip-audit --skip-editable` periodically. Use Python 3.10+ for full
  patch coverage of transitive deps.

---

## License
Sifter Bug Intake is licensed under the Apache License 2.0. See [LICENSE](./LICENSE) for details.

---

## Uninstall

```bash
pip uninstall bug-intake
rm -rf .bug-intake .env.bug_intake .env.bug_intake.example
rm -rf .cursor/skills/bug-intake
rm -f secrets/token.json
```
