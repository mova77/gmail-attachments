"""Gmail OAuth handling for the attachment-saver MCP server.

Uses an installed-app OAuth flow. On first run it opens a browser to consent,
then caches the token so subsequent runs are non-interactive.

Files (all beside this module, override with env vars):
  credentials.json  OAuth *client* secret downloaded from Google Cloud Console.
                    Path override: GMAIL_CREDENTIALS
  token.json        Cached user token, created automatically after first consent.
                    Path override: GMAIL_TOKEN
"""

from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Read-only is all we need to search messages and pull attachments.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_HERE = Path(__file__).resolve().parent
CREDENTIALS_PATH = Path(os.environ.get("GMAIL_CREDENTIALS", _HERE / "credentials.json"))
TOKEN_PATH = Path(os.environ.get("GMAIL_TOKEN", _HERE / "token.json"))


class AuthError(RuntimeError):
    """Raised when Gmail credentials are missing or unusable."""


def _load_cached_credentials() -> Credentials | None:
    if not TOKEN_PATH.exists():
        return None
    return Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)


def get_credentials(*, allow_interactive: bool = True) -> Credentials:
    """Return valid user credentials, refreshing or running consent as needed.

    Set allow_interactive=False (e.g. inside the always-non-interactive MCP
    server) to fail loudly instead of trying to pop a browser.
    """
    creds = _load_cached_credentials()

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
        return creds

    if not allow_interactive:
        raise AuthError(
            f"No valid Gmail token at {TOKEN_PATH}. Run `python gmail_auth.py` "
            "once from a terminal to complete the one-time browser consent."
        )

    if not CREDENTIALS_PATH.exists():
        raise AuthError(
            f"Missing OAuth client secret at {CREDENTIALS_PATH}. Download it from "
            "Google Cloud Console (APIs & Services -> Credentials -> OAuth client "
            "ID -> Desktop app) and save it there. See README.md."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())
    return creds


def get_service(*, allow_interactive: bool = True):
    """Build an authenticated Gmail API client."""
    creds = get_credentials(allow_interactive=allow_interactive)
    # cache_discovery=False avoids a noisy warning on 3.13 / oauth2client absence.
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


if __name__ == "__main__":
    # Running this module directly performs the one-time interactive consent.
    get_service(allow_interactive=True)
    print(f"Authorized. Token cached at {TOKEN_PATH}")
