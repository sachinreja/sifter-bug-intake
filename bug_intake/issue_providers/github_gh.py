from __future__ import annotations

import json
import re
import subprocess

from bug_intake.issue_providers.base import CreatedIssue, IssueProvider, IssueStatus


_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")
_GH_TIMEOUT_SECONDS = 30


class GitHubGhProvider(IssueProvider):
    def __init__(self, *, repo: str) -> None:
        if not repo:
            raise ValueError("BUG_INTAKE_GITHUB_REPO is required for GitHub provider")
        if not _REPO_PATTERN.fullmatch(repo):
            raise ValueError(
                f"Invalid GitHub repo '{repo}'. Expected format 'owner/repo'."
            )
        self.repo = repo

    def create_issue(self, *, title: str, body: str) -> CreatedIssue:
        if not title.strip():
            raise ValueError("Issue title cannot be empty.")
        cmd = [
            "gh",
            "issue",
            "create",
            "--repo",
            self.repo,
            "--title",
            title,
            "--body",
            body,
        ]
        completed = self._run(cmd)
        output = completed.stdout.strip()
        # `gh issue create` prints the issue URL (not JSON); some versions never supported --json.
        url = ""
        for line in reversed(output.splitlines()):
            candidate = line.strip()
            if candidate.startswith("http") and "/issues/" in candidate:
                url = candidate
                break
        if not url:
            url = output.splitlines()[-1].strip() if output else ""
        number = self._extract_issue_number(url)
        if not number:
            raise RuntimeError(f"Could not parse issue info from gh output: {output}")
        return CreatedIssue(number=number, url=url)

    def get_issue_status(self, *, issue_number: int) -> IssueStatus:
        if not isinstance(issue_number, int) or issue_number <= 0:
            raise ValueError("issue_number must be a positive integer.")
        cmd = [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            self.repo,
            "--json",
            "number,url,state",
        ]
        completed = self._run(cmd)
        payload = json.loads(completed.stdout)
        return IssueStatus(
            number=int(payload["number"]),
            url=payload["url"],
            state=str(payload["state"]).upper(),
        )

    @staticmethod
    def _run(cmd: list[str]) -> subprocess.CompletedProcess:
        try:
            completed = subprocess.run(  # nosec - args is a list, shell=False
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "GitHub CLI `gh` not found on PATH. Install it from https://cli.github.com/"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"`{' '.join(cmd[:3])}` timed out after {_GH_TIMEOUT_SECONDS}s."
            ) from exc
        if completed.returncode != 0:
            raise RuntimeError(
                f"`{' '.join(cmd[:3])}` failed: "
                f"{completed.stderr.strip() or completed.stdout.strip() or 'unknown error'}"
            )
        return completed

    @staticmethod
    def _extract_issue_number(url: str) -> int | None:
        match = re.search(r"/issues/(\d+)$", url)
        if not match:
            return None
        return int(match.group(1))
