from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CreatedIssue:
    number: int
    url: str


@dataclass
class IssueStatus:
    number: int
    url: str
    state: str


class IssueProvider(ABC):
    @abstractmethod
    def create_issue(self, *, title: str, body: str) -> CreatedIssue:
        """Create an issue and return provider metadata."""

    @abstractmethod
    def get_issue_status(self, *, issue_number: int) -> IssueStatus:
        """Return issue status metadata."""
