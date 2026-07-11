"""Gmail search + attachment extraction, independent of MCP.

Kept separate from server.py so it can be unit-tested or reused directly.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path

from googleapiclient.errors import HttpError

# Cap how many messages a single call will scan, so a broad query like
# "has:attachment" can't fan out into thousands of API round-trips.
DEFAULT_MAX_MESSAGES = 25
HARD_MAX_MESSAGES = 200

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class AttachmentInfo:
    """One attachment, with metadata and optionally its bytes."""

    message_id: str
    filename: str
    mime_type: str
    size: int
    sender: str
    subject: str
    attachment_id: str
    data: bytes | None = field(default=None, repr=False)


def _header(headers: list[dict], name: str) -> str:
    name = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name:
            return h.get("value", "")
    return ""


def _walk_parts(part: dict):
    """Yield every part in a payload tree (depth-first)."""
    yield part
    for sub in part.get("parts", []) or []:
        yield from _walk_parts(sub)


def _sanitize_filename(name: str, fallback: str) -> str:
    name = _UNSAFE.sub("_", name).strip(" ._")
    return name or fallback


def _matches_mime(mime_type: str, filename: str, allowed: list[str] | None) -> bool:
    if not allowed:
        return True
    ext = Path(filename).suffix.lower().lstrip(".")
    for a in allowed:
        a = a.lower().strip()
        if not a:
            continue
        if a == ext:  # extension match, e.g. "pdf"
            return True
        if a.endswith("/*") and mime_type.lower().startswith(a[:-1]):  # "image/*"
            return True
        if a == mime_type.lower():  # full mime, e.g. "application/pdf"
            return True
    return False


def _clamp_max(max_messages: int) -> int:
    if max_messages <= 0:
        return DEFAULT_MAX_MESSAGES
    return min(max_messages, HARD_MAX_MESSAGES)


def search_message_ids(service, query: str, max_messages: int) -> list[str]:
    """Return message IDs matching a Gmail search query (newest first)."""
    max_messages = _clamp_max(max_messages)
    ids: list[str] = []
    page_token = None
    while len(ids) < max_messages:
        resp = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                pageToken=page_token,
                maxResults=min(100, max_messages - len(ids)),
            )
            .execute()
        )
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_messages]


def find_attachments(
    service,
    query: str,
    *,
    mime_types: list[str] | None = None,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    fetch_data: bool = False,
) -> list[AttachmentInfo]:
    """Find (and optionally download) attachments across matching messages."""
    results: list[AttachmentInfo] = []
    for msg_id in search_message_ids(service, query, max_messages):
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        sender = _header(headers, "From")
        subject = _header(headers, "Subject")

        for part in _walk_parts(msg.get("payload", {})):
            filename = part.get("filename") or ""
            body = part.get("body", {})
            attachment_id = body.get("attachmentId")
            if not filename or not attachment_id:
                continue  # not an attachment (inline text, container part, etc.)

            mime_type = part.get("mimeType", "application/octet-stream")
            if not _matches_mime(mime_type, filename, mime_types):
                continue

            info = AttachmentInfo(
                message_id=msg_id,
                filename=filename,
                mime_type=mime_type,
                size=body.get("size", 0),
                sender=sender,
                subject=subject,
                attachment_id=attachment_id,
            )
            if fetch_data:
                info.data = _download(service, msg_id, attachment_id)
                info.size = len(info.data)
            results.append(info)
    return results


def _download(service, message_id: str, attachment_id: str) -> bytes:
    att = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment_id)
        .execute()
    )
    return base64.urlsafe_b64decode(att["data"])


def _unique_path(dest: Path, filename: str) -> Path:
    """Resolve collisions by appending _1, _2, ... before the extension."""
    candidate = dest / filename
    if not candidate.exists():
        return candidate
    stem, suffix = Path(filename).stem, Path(filename).suffix
    i = 1
    while (dest / f"{stem}_{i}{suffix}").exists():
        i += 1
    return dest / f"{stem}_{i}{suffix}"


def save_attachments(
    service,
    query: str,
    dest_dir: str,
    *,
    mime_types: list[str] | None = None,
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> list[dict]:
    """Download matching attachments to dest_dir. Returns saved-file records."""
    dest = Path(dest_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    saved: list[dict] = []
    for info in find_attachments(
        service, query, mime_types=mime_types, max_messages=max_messages, fetch_data=True
    ):
        safe = _sanitize_filename(info.filename, fallback=f"{info.message_id}.bin")
        path = _unique_path(dest, safe)
        path.write_bytes(info.data or b"")
        saved.append(
            {
                "path": str(path),
                "filename": path.name,
                "size": info.size,
                "mime_type": info.mime_type,
                "from": info.sender,
                "subject": info.subject,
                "message_id": info.message_id,
            }
        )
    return saved
