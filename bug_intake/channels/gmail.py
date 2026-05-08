from __future__ import annotations

import base64
import binascii
from email.mime.text import MIMEText
from email.utils import parseaddr
import os
from pathlib import Path
import re
import stat
from typing import Any

from bug_intake.channels.base import ChannelAdapter
from bug_intake.models import NormalizedMessage, ProcessingRecord


_GMAIL_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9 _\-/&]+$")


def _sanitize_label(label: str) -> str:
    label = label.strip()
    if not label:
        raise ValueError("Gmail label is empty.")
    if not _GMAIL_LABEL_PATTERN.fullmatch(label):
        raise ValueError(
            "Gmail label contains unsupported characters; "
            "allowed: letters, digits, spaces, '_', '-', '/', '&'."
        )
    return label


def _write_secret_file(path: Path, contents: str) -> None:
    """Write text to disk with strict 0600 permissions for secrets."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(contents)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    try:
        os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


class GmailChannelAdapter(ChannelAdapter):
    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    ]

    def __init__(
        self,
        *,
        credentials_path: Path,
        token_path: Path,
        headless: bool = False,
    ) -> None:
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.headless = headless
        self._service = None

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Missing Gmail dependencies. Install: google-api-python-client "
                "google-auth-httplib2 google-auth-oauthlib"
            ) from exc

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), self.SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_path.exists():
                    raise RuntimeError(
                        f"Gmail credentials file not found: {self.credentials_path}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), self.SCOPES
                )
                if self.headless:
                    creds = flow.run_console()
                else:
                    creds = flow.run_local_server(port=0)
            _write_secret_file(self.token_path, creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def fetch_messages(self, *, label: str, max_results: int = 50) -> list[NormalizedMessage]:
        if max_results <= 0 or max_results > 500:
            raise ValueError("max_results must be between 1 and 500.")
        safe_label = _sanitize_label(label)
        service = self._get_service()
        query = f'label:"{safe_label}"'
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        ids = response.get("messages", [])
        normalized: list[NormalizedMessage] = []
        for item in ids:
            raw = (
                service.users()
                .messages()
                .get(userId="me", id=item["id"], format="full")
                .execute()
            )
            normalized.append(self._normalize(raw))
        return normalized

    def ensure_authenticated(self) -> str:
        """Ensure OAuth tokens exist and return authenticated account email."""
        service = self._get_service()
        profile = service.users().getProfile(userId="me").execute()
        return profile.get("emailAddress", "")

    def list_labels(self) -> list[str]:
        service = self._get_service()
        response = service.users().labels().list(userId="me").execute()
        return [label.get("name", "") for label in response.get("labels", []) if label.get("name")]

    def label_exists(self, label_name: str) -> bool:
        return label_name in set(self.list_labels())

    def _normalize(self, message: dict[str, Any]) -> NormalizedMessage:
        payload = message.get("payload", {})
        headers_list = payload.get("headers", [])
        headers = {header.get("name", ""): header.get("value", "") for header in headers_list}

        from_name, from_email = parseaddr(headers.get("From", ""))
        subject = headers.get("Subject", "(no subject)")
        body_text = self._extract_body(payload)
        return NormalizedMessage(
            message_id=message.get("id", ""),
            thread_id=message.get("threadId", ""),
            from_email=from_email or "",
            from_name=from_name or None,
            subject=subject,
            body_text=body_text,
            snippet=message.get("snippet", ""),
            received_at=headers.get("Date"),
            raw_headers=headers,
        )

    def _extract_body(self, payload: dict[str, Any]) -> str:
        body_data = payload.get("body", {}).get("data")
        if body_data:
            decoded = self._decode_body(body_data)
            if decoded:
                return decoded
        for part in payload.get("parts", []) or []:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain" and part.get("body", {}).get("data"):
                decoded = self._decode_body(part["body"]["data"])
                if decoded:
                    return decoded
        for part in payload.get("parts", []) or []:
            decoded = self._extract_body(part)
            if decoded:
                return decoded
        return ""

    @staticmethod
    def _decode_body(data: str) -> str:
        try:
            return base64.urlsafe_b64decode(data.encode("utf-8")).decode(
                "utf-8", errors="replace"
            )
        except (binascii.Error, ValueError):
            return ""

    def send_reply(self, *, record: ProcessingRecord, body: str) -> str:
        if not record.reporter_email:
            raise RuntimeError(f"Cannot reply to message {record.message_id}: missing reporter email")
        service = self._get_service()
        msg = MIMEText(body)
        msg["to"] = record.reporter_email
        msg["subject"] = f"Re: {record.subject}"
        msg["In-Reply-To"] = record.message_id
        msg["References"] = record.message_id
        encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        sent = (
            service.users()
            .messages()
            .send(
                userId="me",
                body={"raw": encoded, "threadId": record.thread_id},
            )
            .execute()
        )
        return sent.get("id", "")
