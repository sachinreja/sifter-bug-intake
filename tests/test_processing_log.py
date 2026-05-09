from __future__ import annotations

from pathlib import Path

from bug_intake.log import ProcessingLog
from bug_intake.models import GitHubIssueRef, ProcessingRecord


def _record(message_id: str, *, issue_number: int | None = None, notified: bool = False) -> ProcessingRecord:
    return ProcessingRecord(
        message_id=message_id,
        thread_id=f"thread-{message_id}",
        reporter_email="reporter@example.com",
        reporter_name="Reporter",
        subject="subject",
        snippet="snippet",
        body_text="body",
        github=GitHubIssueRef(issue_number=issue_number),
        notified=notified,
    )


def test_pending_notify_includes_only_linked_unnotified(tmp_path: Path) -> None:
    log = ProcessingLog(path=tmp_path / "log.json")
    log.upsert(_record("a"))
    log.upsert(_record("b", issue_number=10, notified=False))
    log.upsert(_record("c", issue_number=11, notified=True))
    log.upsert(_record("d", issue_number=None, notified=True))

    pending = log.pending_notify()
    pending_ids = {record.message_id for record in pending}

    assert pending_ids == {"b"}


def test_pending_notify_round_trips_through_disk(tmp_path: Path) -> None:
    log_path = tmp_path / "log.json"
    log = ProcessingLog(path=log_path)
    log.upsert(_record("a", issue_number=1))
    log.upsert(_record("b", issue_number=2, notified=True))
    log.save()

    reloaded = ProcessingLog.load(log_path)
    pending_ids = {record.message_id for record in reloaded.pending_notify()}
    assert pending_ids == {"a"}


def test_pending_notify_empty_log_returns_empty_list(tmp_path: Path) -> None:
    log = ProcessingLog(path=tmp_path / "log.json")
    assert log.pending_notify() == []
