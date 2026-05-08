from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from bug_intake.models import ProcessingRecord


@dataclass
class ProcessingLog:
    path: Path
    records: dict[str, ProcessingRecord] = field(default_factory=dict)
    version: int = 1

    @classmethod
    def load(cls, path: str | Path) -> "ProcessingLog":
        log_path = Path(path)
        if not log_path.exists():
            return cls(path=log_path, records={})

        with log_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        records = {
            item["message_id"]: ProcessingRecord.from_dict(item)
            for item in raw.get("records", [])
            if item.get("message_id")
        }
        return cls(path=log_path, records=records, version=raw.get("version", 1))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "version": self.version,
            "records": [record.to_dict() for record in self.records.values()],
        }
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=False)
            handle.write("\n")

    def get(self, message_id: str) -> ProcessingRecord | None:
        return self.records.get(message_id)

    def upsert(self, record: ProcessingRecord) -> ProcessingRecord:
        current = self.records.get(record.message_id)
        if current:
            current.thread_id = record.thread_id
            current.reporter_email = record.reporter_email
            current.reporter_name = record.reporter_name
            current.subject = record.subject
            current.snippet = record.snippet
            current.body_text = record.body_text
            current.received_at = record.received_at
            current.mark_updated()
            return current
        self.records[record.message_id] = record
        return record

    def all_records(self) -> list[ProcessingRecord]:
        return sorted(self.records.values(), key=lambda r: r.created_at)

    def pending_notify(self) -> list[ProcessingRecord]:
        return [
            record
            for record in self.records.values()
            if record.github.issue_number is not None and not record.notified
        ]
