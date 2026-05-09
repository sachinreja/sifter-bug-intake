from __future__ import annotations

import pytest

from bug_intake.issue_providers.github_gh import GitHubGhProvider


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/octocat/hello-world/issues/1", 1),
        ("https://github.com/owner/repo/issues/42", 42),
        ("https://github.com/owner/repo-name/issues/12345", 12345),
        ("http://github.com/o/r/issues/7", 7),
    ],
)
def test_extract_issue_number_valid(url: str, expected: int) -> None:
    assert GitHubGhProvider._extract_issue_number(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "https://github.com/owner/repo/pull/1",
        "https://github.com/owner/repo/issues/",
        "https://github.com/owner/repo/issues/abc",
        "https://example.com/owner/repo/issues/1?foo=bar",
    ],
)
def test_extract_issue_number_invalid(url: str) -> None:
    assert GitHubGhProvider._extract_issue_number(url) is None
