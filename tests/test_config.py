from __future__ import annotations

import os
from pathlib import Path

import pytest

from bug_intake.config import BugIntakeConfig

_ENV_KEYS = [
    "BUG_INTAKE_CHANNEL",
    "BUG_INTAKE_GMAIL_LABEL",
    "BUG_INTAKE_GMAIL_CREDENTIALS_PATH",
    "BUG_INTAKE_GMAIL_TOKEN_PATH",
    "BUG_INTAKE_GITHUB_REPO",
    "BUG_INTAKE_LOG_PATH",
    "BUG_INTAKE_PENDING_ISSUES_DIR",
    "BUG_INTAKE_REQUIRE_APPROVAL_FOR_REPLIES",
]


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_load_returns_defaults_when_no_env_file(tmp_path: Path) -> None:
    config = BugIntakeConfig.load(tmp_path / "missing.env")

    assert config.channel == "gmail"
    assert config.gmail_label == "Bug Reports"
    assert config.gmail_credentials_path == Path("./secrets/credentials.json")
    assert config.gmail_token_path == Path("./secrets/token.json")
    assert config.github_repo == ""
    assert config.log_path == Path("./.bug-intake/processing_log.json")
    assert config.pending_issues_dir == Path("./.bug-intake/pending_issues")
    assert config.require_approval_for_replies is True


def test_load_reads_values_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.bug_intake"
    env_file.write_text(
        "\n".join(
            [
                "# comment line",
                "BUG_INTAKE_CHANNEL=gmail",
                "BUG_INTAKE_GMAIL_LABEL=\"Sifter Support\"",
                "BUG_INTAKE_GMAIL_CREDENTIALS_PATH=./creds.json",
                "BUG_INTAKE_GMAIL_TOKEN_PATH='./token.json'",
                "BUG_INTAKE_GITHUB_REPO=acme/widgets",
                "BUG_INTAKE_LOG_PATH=./logs/out.json",
                "BUG_INTAKE_PENDING_ISSUES_DIR=./pending",
                "BUG_INTAKE_REQUIRE_APPROVAL_FOR_REPLIES=false",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = BugIntakeConfig.load(env_file)

    assert config.channel == "gmail"
    assert config.gmail_label == "Sifter Support"
    assert config.gmail_credentials_path == Path("./creds.json")
    assert config.gmail_token_path == Path("./token.json")
    assert config.github_repo == "acme/widgets"
    assert config.log_path == Path("./logs/out.json")
    assert config.pending_issues_dir == Path("./pending")
    assert config.require_approval_for_replies is False


def test_load_does_not_override_existing_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env.bug_intake"
    env_file.write_text("BUG_INTAKE_GITHUB_REPO=from-file/repo\n", encoding="utf-8")

    monkeypatch.setenv("BUG_INTAKE_GITHUB_REPO", "from-env/repo")
    config = BugIntakeConfig.load(env_file)

    assert config.github_repo == "from-env/repo"
    assert os.environ["BUG_INTAKE_GITHUB_REPO"] == "from-env/repo"


@pytest.mark.parametrize(
    "raw, expected",
    [("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
     ("false", False), ("0", False), ("no", False), ("off", False), ("", False)],
)
def test_require_approval_bool_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("BUG_INTAKE_REQUIRE_APPROVAL_FOR_REPLIES", raw)
    config = BugIntakeConfig.load(tmp_path / "missing.env")
    assert config.require_approval_for_replies is expected
