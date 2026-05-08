# Security Policy

## Reporting

Please report vulnerabilities privately by opening a private security advisory
on GitHub for this repo. Avoid filing public issues for unpatched problems.

## Threat Model

`bug-intake` is a local-first developer tool. It runs as the operator's user
account and assumes the local machine is trusted. It:

- Reads OAuth client + token JSON files you provide.
- Calls Google APIs (Gmail) over HTTPS.
- Calls the GitHub CLI (`gh`) as a local subprocess.
- Writes logs and pending message JSON under `.bug-intake/`.

It does **not** run a server, expose ports, or accept untrusted input from the
network. The only inputs it processes are the messages your Gmail label
receives and the strings you (or the agent) pass on the CLI.

## Hardening Built In

- **Subprocess invocation** uses `subprocess.run([...], shell=False)` with
  argument lists, so `title`, `body`, `repo`, etc. cannot inject shell.
- **GitHub repo argument** is validated against `owner/repo` regex before
  being passed to `gh`.
- **Gmail label** is validated against an allow-list of characters before
  being interpolated into the Gmail search query.
- **`message_id`** is validated against `[A-Za-z0-9_-]{1,128}` before being
  used as a filename, and the resolved path is checked to remain inside the
  pending issues directory (defense-in-depth against path traversal).
- **OAuth tokens** are written via `os.open(..., 0o600)` with explicit
  `os.chmod(0o600)` so only the local user can read them.
- **Subprocess calls** to `gh` use a 30s timeout to prevent hangs.
- **No `pickle`** anywhere; logs are JSON.
- **No third-party dotenv parser**; `bug_intake/config.py` ships its own
  small `.env` loader to reduce dependency surface.

## Operator Responsibilities

- Keep `*.json` credential and token files out of source control. The
  `init` command writes safe `.gitignore` entries for `.bug-intake/`,
  `.env.bug_intake`, and `secrets/token.json`. If you store the token
  elsewhere, ensure that location is also gitignored.
- Treat `.env.bug_intake` as a secret-adjacent file (it points to credential
  paths and your repo).
- Keep `gh` (`brew upgrade gh`) and Python dependencies current.

## Supply Chain / Dependencies

Run a vulnerability scan against installed dependencies:

```bash
pip install pip-audit
pip-audit --skip-editable
```

> Note: Several Python packages used by `google-api-python-client` (and its
> transitive deps `requests`, `filelock`) have shipped CVE patches that
> require Python 3.10+. If you run `bug-intake` on Python 3.9, those packages
> stay on their last 3.9-compatible versions and `pip-audit` will report
> residual advisories. To eliminate them, upgrade to Python 3.10 or newer
> (Python 3.9 itself is also end-of-life).

```bash
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```
