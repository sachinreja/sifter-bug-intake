---
name: bug-intake
description: >-
  Triages incoming bug reports from Gmail, files GitHub issues, replies to
  reporters, and notifies them when their bug is fixed. Use when the user says
  "check the bug inbox", "triage bug reports", "notify reporters of fixed bugs",
  "respond to bug reporters", or any variant of managing bug report emails.
disable-model-invocation: true
---

# Bug Intake Skill

The CLI is `bug-intake` (installed via `pip install -e .` or a published
package). All state lives under `.bug-intake/` at the repo root:

- `.bug-intake/processing_log.json` — source of truth (gitignored)
- `.bug-intake/pending_issues/<message_id>.json` — normalized email payloads
- `.env.bug_intake` — runtime config (channel, label, repo, paths)

This skill drives two workflows:

1. Triage new bug reports
2. Notify reporters when their bugs are fixed

Never act on a `message_id` twice. The processing log is authoritative.

---

## Workflow 1 — Triage new bug reports

Trigger phrases: "check the bug inbox", "get latest bugs", "triage bug
reports", "process bug reports".

### Step 1 — Fetch new messages

```bash
bug-intake fetch --headless --max-results 25
```

- Pulls messages from the configured Gmail label
- Skips any `message_id` already present in `processing_log.json`
- Writes one JSON file per new message into `.bug-intake/pending_issues/`
- Updates `processing_log.json` with `action: "fetched"` records

If nothing new is returned, stop and report: "No new bug reports."

### Step 2 — Read each pending message

For each file in `.bug-intake/pending_issues/*.json` decide one of:

- **Real, actionable bug** → `create_issue`
- **Plausible bug but missing repro details** → `reply` asking for specifics
- **Not a bug** (spam, test, support question, marketing) → `ignore`

Be specific about *why* — that reasoning goes into `--notes` and stays in the
log for audit.

### Step 3 — Execute the action

#### A) Create a GitHub issue

```bash
bug-intake act create_issue \
  --message-id "<message_id>" \
  --title "[Bug] <concise, specific title>" \
  --body "$(cat <<'EOF'
### Reporter
<name> <<email>>

### Summary
<1–2 sentence description>

### Steps to reproduce
1. ...
2. ...
3. ...

### Expected
...

### Actual
...

### Source
Original message_id: <message_id>
EOF
)" \
  --notes "<your reasoning, e.g. 'Clear repro steps, affects checkout flow'>"
```

The CLI calls `gh issue create` under the hood, captures the issue number and
URL, and writes both into `processing_log.json` under the record's `github`
field. It is idempotent: re-running on the same `message_id` is a no-op once
the issue is recorded.

#### B) Reply to the reporter (asks for details)

Replies are explicit-only. Nothing is sent until this command is invoked.

```bash
bug-intake act reply \
  --message-id "<message_id>" \
  --body "$(cat <<'EOF'
Hi <first name>,

Thanks for the report. To file this correctly, could you share:
- Steps to reproduce
- What you expected vs. what happened
- Browser / OS / app version
- A screenshot or short video, if possible

— The team
EOF
)" \
  --notes "<reasoning, e.g. 'Vague: no repro steps, no env'>"
```

#### C) Ignore (not actionable)

```bash
bug-intake act ignore \
  --message-id "<message_id>" \
  --notes "<reasoning, e.g. 'Marketing/newsletter, not a bug'>"
```

### Step 4 — Report back to the user

Summarise concisely, e.g.:

> Processed 3 messages — 1 issue filed (#42 https://github.com/owner/repo/issues/42), 1 clarification reply sent, 1 ignored.

Include each created GitHub issue URL.

---

## Workflow 2 — Notify reporters of fixed bugs

Trigger phrases: "notify reporters", "bugs have been fixed", "respond to
reporters", "let reporters know".

### Step 1 — Identify candidates

Candidates are records that:

- have `github.issue_number` set, AND
- have `notified: false`

Each record also has a `history` array — an append-only audit trail of every
action taken on the message, including notes and timestamps. Use it when the
top-level `action`/`notes` fields don't tell the full story (e.g., a record
that was first `create_issue` then `reply`).

You can inspect them directly:

```bash
python3 -c "
import json, pathlib
log = json.loads(pathlib.Path('.bug-intake/processing_log.json').read_text())
candidates = [
    r for r in log.get('records', [])
    if r.get('github', {}).get('issue_number') and not r.get('notified')
]
print(json.dumps(candidates, indent=2))
"
```

### Step 2 — Run the notify pass

The CLI checks each linked GitHub issue and only sends a notification when the
issue is **closed**. Run:

```bash
bug-intake act notify
```

By default it sends a generic "issue resolved" message. To send a tailored
message for the closed issues in this batch:

```bash
bug-intake act notify --template "$(cat <<'EOF'
Hi there,

Quick update — the bug you reported has been resolved and shipped. Tracking
issue: <will be appended automatically by the CLI context>.

If anything still looks off, just reply to this email with steps to reproduce
and we will reopen.

— The team
EOF
)"
```

Behaviour:

- For each candidate, the CLI runs `gh issue view <n> --json state` and updates
  `github.state` and `github.state_checked_at` on the record
- If `state == CLOSED`, it sends a reply via the channel adapter and sets
  `notified: true`, `action: "notify"`
- Open issues are skipped (no message sent, no flag changed)

If you need to differentiate "completed" vs. "won't fix", inspect issue state
beforehand and call `bug-intake act reply` directly with a custom body, then
manually flip `notified` by re-running notify (closed + custom template).

### Step 3 — Report back

Summarise: who was notified, who was skipped (still open), and any errors.

---

## Key rules

- Never process the same `message_id` twice — the processing log is the source
  of truth.
- Never send a reply or notification automatically. They only fire when
  `bug-intake act reply` or `bug-intake act notify` is explicitly invoked.
- Always pass `--notes` describing your reasoning. The log is the audit trail.
- Keep replies warm and human. Avoid template-sounding language and signatures
  that look auto-generated.
- The GitHub repo is whatever is configured in `.env.bug_intake`
  (`BUG_INTAKE_GITHUB_REPO`). Confirm with `gh repo view` if unsure.
- If `bug-intake fetch` errors with auth issues, run `bug-intake init` again to
  refresh OAuth tokens.
