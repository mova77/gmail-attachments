"""Offline unit tests for gmail_client — no network, no real Gmail.

Run:  python -m pytest test_gmail_client.py   (or: python test_gmail_client.py)
"""

from __future__ import annotations

import base64
from pathlib import Path

import gmail_client as gc


def test_matches_mime_extension_full_and_wildcard():
    assert gc._matches_mime("application/pdf", "report.pdf", ["pdf"])
    assert gc._matches_mime("application/pdf", "report.pdf", ["application/pdf"])
    assert gc._matches_mime("image/png", "pic.png", ["image/*"])
    assert not gc._matches_mime("image/png", "pic.png", ["pdf"])
    # Empty / None filter means "accept everything".
    assert gc._matches_mime("anything/here", "x.bin", None)
    assert gc._matches_mime("anything/here", "x.bin", [])


def test_sanitize_filename_strips_unsafe_and_falls_back():
    assert gc._sanitize_filename("in/voice:2024?.pdf", "fb") == "in_voice_2024_.pdf"
    assert gc._sanitize_filename("///", "fallback.bin") == "fallback.bin"


def test_clamp_max_bounds():
    assert gc._clamp_max(0) == gc.DEFAULT_MAX_MESSAGES
    assert gc._clamp_max(-5) == gc.DEFAULT_MAX_MESSAGES
    assert gc._clamp_max(10_000) == gc.HARD_MAX_MESSAGES
    assert gc._clamp_max(7) == 7


def test_unique_path_avoids_collision(tmp_path: Path):
    (tmp_path / "a.pdf").write_text("x")
    assert gc._unique_path(tmp_path, "a.pdf").name == "a_1.pdf"
    (tmp_path / "a_1.pdf").write_text("x")
    assert gc._unique_path(tmp_path, "a.pdf").name == "a_2.pdf"


def test_walk_parts_and_header():
    payload = {
        "headers": [{"name": "From", "value": "a@b.com"}],
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "body": {"size": 3}},
            {"mimeType": "multipart/mixed", "parts": [{"filename": "x.pdf", "body": {"attachmentId": "AID"}}]},
        ],
    }
    names = [p.get("filename") for p in gc._walk_parts(payload)]
    assert "x.pdf" in names
    assert gc._header(payload["headers"], "from") == "a@b.com"
    assert gc._header(payload["headers"], "Subject") == ""


class _FakeAttachments:
    def get(self, userId, messageId, id):
        payload = base64.urlsafe_b64encode(b"hello-bytes").decode()
        return _Exec({"data": payload})


class _FakeMessages:
    def __init__(self, listing, message):
        self._listing, self._message = listing, message

    def list(self, **kw):
        return _Exec(self._listing)

    def get(self, **kw):
        return _Exec(self._message)

    def attachments(self):
        return _FakeAttachments()


class _FakeUsers:
    def __init__(self, messages):
        self._messages = messages

    def messages(self):
        return self._messages


class _FakeService:
    def __init__(self, messages):
        self._users = _FakeUsers(messages)

    def users(self):
        return self._users


class _Exec:
    def __init__(self, value):
        self._value = value

    def execute(self):
        return self._value


def _service_with_one_pdf():
    listing = {"messages": [{"id": "M1"}]}
    message = {
        "payload": {
            "headers": [
                {"name": "From", "value": "sender@x.com"},
                {"name": "Subject", "value": "Invoice"},
            ],
            "parts": [{"filename": "invoice.pdf", "mimeType": "application/pdf",
                        "body": {"size": 11, "attachmentId": "AID"}}],
        }
    }
    return _FakeService(_FakeMessages(listing, message))


def test_find_attachments_metadata_only():
    found = gc.find_attachments(_service_with_one_pdf(), "q", fetch_data=False)
    assert len(found) == 1
    assert found[0].filename == "invoice.pdf"
    assert found[0].sender == "sender@x.com"
    assert found[0].data is None


def test_save_attachments_writes_file(tmp_path: Path):
    saved = gc.save_attachments(_service_with_one_pdf(), "q", str(tmp_path))
    assert len(saved) == 1
    written = Path(saved[0]["path"])
    assert written.read_bytes() == b"hello-bytes"
    assert saved[0]["from"] == "sender@x.com"


if __name__ == "__main__":
    import sys
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    import tempfile

    for fn in fns:
        try:
            if "tmp_path" in fn.__code__.co_varnames[: fn.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"ok   {fn.__name__}")
        except Exception:  # noqa: BLE001
            failures += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    sys.exit(1 if failures else 0)
