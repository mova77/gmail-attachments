"""MCP server exposing Gmail attachment-saving tools.

Tools:
  list_attachments   Dry-run: what WOULD be saved for a query (no download).
  save_attachments   Download matching attachments to a local directory.
  whoami             Report the authorized Gmail address (auth sanity check).

Auth is read-only (gmail.readonly) and must be set up once out-of-band by
running `python gmail_auth.py` in a terminal; see README.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from gmail_auth import AuthError, get_service
from gmail_client import DEFAULT_MAX_MESSAGES, find_attachments, save_attachments

mcp = FastMCP("gmail-attachments")

# Where downloads go when the caller doesn't specify. Override with env var.
DEFAULT_DEST = os.environ.get(
    "GMAIL_ATTACHMENTS_DIR", str(Path.home() / "Downloads" / "gmail-attachments")
)


def _service():
    # allow_interactive=False: the server never blocks on a browser prompt.
    return get_service(allow_interactive=False)


@mcp.tool()
def whoami() -> str:
    """Return the email address of the authorized Gmail account."""
    try:
        profile = _service().users().getProfile(userId="me").execute()
    except AuthError as e:
        return f"Not authorized: {e}"
    return json.dumps(
        {
            "email": profile.get("emailAddress"),
            "messages_total": profile.get("messagesTotal"),
        }
    )


@mcp.tool()
def list_attachments(query: str, max_messages: int = DEFAULT_MAX_MESSAGES) -> str:
    """Preview attachments matching a Gmail search WITHOUT downloading them.

    Args:
        query: A Gmail search query, e.g. "from:acme.com has:attachment newer_than:7d".
               Tip: add "has:attachment" to skip messages with none.
        max_messages: Max messages to scan (default 25, hard cap 200).

    Returns JSON: a list of {filename, size, mime_type, from, subject, message_id}.
    """
    try:
        found = find_attachments(
            _service(), query, max_messages=max_messages, fetch_data=False
        )
    except AuthError as e:
        return f"Not authorized: {e}"
    return json.dumps(
        [
            {
                "filename": a.filename,
                "size": a.size,
                "mime_type": a.mime_type,
                "from": a.sender,
                "subject": a.subject,
                "message_id": a.message_id,
            }
            for a in found
        ],
        indent=2,
    )


@mcp.tool(name="save_attachments")
def save_attachments_tool(
    query: str,
    dest_dir: str | None = None,
    mime_types: list[str] | None = None,
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> str:
    """Download attachments from matching Gmail messages to a local folder.

    Args:
        query: Gmail search query, e.g. "from:boss subject:invoice has:attachment".
        dest_dir: Destination folder (created if needed). Defaults to
                  ~/Downloads/gmail-attachments (override via GMAIL_ATTACHMENTS_DIR).
        mime_types: Optional filter — extensions ("pdf"), full mimes
                    ("application/pdf"), or wildcards ("image/*"). Omit for all.
        max_messages: Max messages to scan (default 25, hard cap 200).

    Returns JSON: a list of saved-file records with absolute paths.
    """
    dest = dest_dir or DEFAULT_DEST
    try:
        saved = save_attachments(
            _service(),
            query,
            dest,
            mime_types=mime_types,
            max_messages=max_messages,
        )
    except AuthError as e:
        return f"Not authorized: {e}"
    return json.dumps(
        {"saved_count": len(saved), "dest_dir": str(Path(dest).expanduser()), "files": saved},
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()
