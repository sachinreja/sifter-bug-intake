from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GitHubIssueRef:
    issue_number: int | None = None
    issue_url: str | None = None
    state: str | None = None
    state_checked_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "GitHubIssueRef":
        if not data:
            return cls()
        return cls(
            issue_number=data.get("issue_number"),
            issue_url=data.get("issue_url"),
            state=data.get("state"),
            state_checked_at=data.get("state_checked_at"),
        )


@dataclass
class ActionEntry:
    action: str
    notes: str = ""
    at: str = field(default_factory=utc_now_iso)
    issue_number: int | None = None
    issue_url: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionEntry":
        return cls(
            action=data.get("action", ""),
            notes=data.get("notes", ""),
            at=data.get("at", utc_now_iso()),
            issue_number=data.get("issue_number"),
            issue_url=data.get("issue_url"),
            detail=data.get("detail"),
        )


@dataclass
class NormalizedMessage:
    message_id: str
    thread_id: str
    from_email: str
    from_name: str | None
    subject: str
    body_text: str
    snippet: str
    received_at: str | None = None
    raw_headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessingRecord:
    message_id: str
    thread_id: str
    reporter_email: str
    reporter_name: str | None
    subject: str
    snippet: str
    body_text: str
    received_at: str | None = None
    action: str = "fetched"
    notes: str = ""
    github: GitHubIssueRef = field(default_factory=GitHubIssueRef)
    notified: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    last_error: str | None = None
    history: list[ActionEntry] = field(default_factory=list)

    def mark_updated(self) -> None:
        self.updated_at = utc_now_iso()

    def append_history(
        self,
        *,
        action: str,
        notes: str = "",
        issue_number: int | None = None,
        issue_url: str | None = None,
        detail: str | None = None,
    ) -> ActionEntry:
        entry = ActionEntry(
            action=action,
            notes=notes,
            issue_number=issue_number,
            issue_url=issue_url,
            detail=detail,
        )
        self.history.append(entry)
        self.action = action
        self.notes = notes
        self.mark_updated()
        return entry

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["github"] = self.github.to_dict()
        data["history"] = [entry.to_dict() for entry in self.history]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcessingRecord":
        return cls(
            message_id=data["message_id"],
            thread_id=data["thread_id"],
            reporter_email=data["reporter_email"],
            reporter_name=data.get("reporter_name"),
            subject=data.get("subject", ""),
            snippet=data.get("snippet", ""),
            body_text=data.get("body_text", ""),
            received_at=data.get("received_at"),
            action=data.get("action", "fetched"),
            notes=data.get("notes", ""),
            github=GitHubIssueRef.from_dict(data.get("github")),
            notified=bool(data.get("notified", False)),
            created_at=data.get("created_at", utc_now_iso()),
            updated_at=data.get("updated_at", utc_now_iso()),
            last_error=data.get("last_error"),
            history=[ActionEntry.from_dict(item) for item in data.get("history", [])],
        )
