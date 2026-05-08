from __future__ import annotations

from abc import ABC, abstractmethod

from bug_intake.models import NormalizedMessage, ProcessingRecord


class ChannelAdapter(ABC):
    @abstractmethod
    def fetch_messages(self, *, label: str, max_results: int = 50) -> list[NormalizedMessage]:
        """Fetch and normalize incoming reports from a channel."""

    @abstractmethod
    def send_reply(self, *, record: ProcessingRecord, body: str) -> str:
        """Send a reply to the original reporter and return provider message id."""
