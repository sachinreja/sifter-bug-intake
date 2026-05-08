from __future__ import annotations

from dataclasses import dataclass

from bug_intake.channels.base import ChannelAdapter
from bug_intake.issue_providers.base import IssueProvider
from bug_intake.log import ProcessingLog
from bug_intake.models import utc_now_iso


@dataclass
class ActionResult:
    message_id: str
    action: str
    detail: str


class BugIntakeActions:
    def __init__(
        self,
        *,
        processing_log: ProcessingLog,
        channel: ChannelAdapter,
        issue_provider: IssueProvider,
    ) -> None:
        self.log = processing_log
        self.channel = channel
        self.issue_provider = issue_provider

    def create_issue(
        self,
        *,
        message_id: str,
        title: str,
        body: str,
        notes: str = "",
    ) -> ActionResult:
        record = self._require_record(message_id)
        if record.github.issue_number:
            return ActionResult(
                message_id=message_id,
                action="create_issue",
                detail=f"Skipped: issue already exists #{record.github.issue_number}",
            )

        issue = self.issue_provider.create_issue(title=title, body=body)
        record.github.issue_number = issue.number
        record.github.issue_url = issue.url
        record.github.state = "OPEN"
        record.github.state_checked_at = utc_now_iso()
        detail = f"Created issue #{issue.number}: {issue.url}"
        record.append_history(
            action="create_issue",
            notes=notes,
            issue_number=issue.number,
            issue_url=issue.url,
            detail=detail,
        )
        self.log.save()
        return ActionResult(
            message_id=message_id,
            action="create_issue",
            detail=detail,
        )

    def reply(
        self,
        *,
        message_id: str,
        body: str,
        notes: str = "",
    ) -> ActionResult:
        record = self._require_record(message_id)
        provider_message_id = self.channel.send_reply(record=record, body=body)
        detail = f"Reply sent (provider id: {provider_message_id or 'unknown'})"
        record.append_history(action="reply", notes=notes, detail=detail)
        self.log.save()
        return ActionResult(
            message_id=message_id,
            action="reply",
            detail=detail,
        )

    def ignore(self, *, message_id: str, notes: str = "") -> ActionResult:
        record = self._require_record(message_id)
        detail = "Message ignored"
        record.append_history(action="ignore", notes=notes, detail=detail)
        self.log.save()
        return ActionResult(message_id=message_id, action="ignore", detail=detail)

    def notify_closed_issues(self, *, template: str | None = None) -> list[ActionResult]:
        results: list[ActionResult] = []
        for record in self.log.pending_notify():
            issue_number = record.github.issue_number
            if issue_number is None:
                continue
            status = self.issue_provider.get_issue_status(issue_number=issue_number)
            record.github.state = status.state
            record.github.state_checked_at = utc_now_iso()
            if status.state == "CLOSED" and not record.notified:
                body = template or (
                    "Thanks again for the report.\n\n"
                    f"We've now closed the related issue #{status.number}: {status.url}\n"
                    "If the problem persists, reply to this email with steps to reproduce."
                )
                self.channel.send_reply(record=record, body=body)
                record.notified = True
                detail = f"Notified reporter for closed issue #{status.number}"
                record.append_history(
                    action="notify",
                    notes="Reporter notified after issue closure",
                    issue_number=status.number,
                    issue_url=status.url,
                    detail=detail,
                )
                results.append(
                    ActionResult(
                        message_id=record.message_id,
                        action="notify",
                        detail=detail,
                    )
                )
        self.log.save()
        return results

    def _require_record(self, message_id: str):
        record = self.log.get(message_id)
        if record is None:
            raise ValueError(
                f"message_id '{message_id}' not found in processing log; fetch first."
            )
        return record
