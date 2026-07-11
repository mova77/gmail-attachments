# Gmail Attachments MCP Server

A small [MCP](https://modelcontextprotocol.io) server that lets Claude search your
Gmail and **save attachments to a local folder** — no browser extension, no UI.

It uses the Gmail API with **read-only** access (`gmail.readonly`).

## Tools

| Tool | What it does |
|------|--------------|
| `whoami` | Reports the authorized Gmail address (auth sanity check). |
| `list_attachments(query, max_messages)` | **Dry run** — shows what *would* be saved for a Gmail search, no download. |
| `save_attachments(query, dest_dir, mime_types, max_messages)` | Downloads matching attachments to a folder. |

`query` is a normal [Gmail search](https://support.google.com/mail/answer/7190),
e.g. `from:acme.com has:attachment newer_than:7d subject:invoice`.

## One-time setup

### 1. Install dependencies

```bash
cd /Users/mova/code/chrome/attachments
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Create Google OAuth credentials (~5 min, once)

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or pick an existing one).
3. **APIs & Services → Library →** search "Gmail API" → **Enable**.
4. **APIs & Services → OAuth consent screen:**
   - User type: **External** (fine for personal use).
   - Fill app name + your email. Add your Google account under **Test users**.
   - Add scope `.../auth/gmail.readonly` (optional at this stage; the app requests it anyway).
5. **APIs & Services → Credentials → Create credentials → OAuth client ID:**
   - Application type: **Desktop app**.
   - Download the JSON, save it as `credentials.json` in this folder.

### 3. Authorize once (interactive)

```bash
.venv/bin/python gmail_auth.py
```

A browser opens; grant read-only access. This writes `token.json`, which the
server reuses non-interactively. (If the app is in "testing", the token may
expire after 7 days — just rerun this command to refresh.)

Verify:

```bash
.venv/bin/python -c "from gmail_auth import get_service; print(get_service().users().getProfile(userId='me').execute()['emailAddress'])"
```

## Wire it into Claude

### Claude Code (CLI)

```bash
claude mcp add gmail-attachments -- /Users/mova/code/chrome/attachments/.venv/bin/python /Users/mova/code/chrome/attachments/server.py
```

### Or edit your MCP config directly

```json
{
  "mcpServers": {
    "gmail-attachments": {
      "command": "/Users/mova/code/chrome/attachments/.venv/bin/python",
      "args": ["/Users/mova/code/chrome/attachments/server.py"],
      "env": {
        "GMAIL_ATTACHMENTS_DIR": "/Users/mova/Downloads/gmail-attachments"
      }
    }
  }
}
```

Then ask Claude, e.g.:

> "Save all PDF attachments from invoices@acme.com in the last 30 days."

Claude calls `list_attachments` to preview, then `save_attachments` with
`query="from:invoices@acme.com has:attachment newer_than:30d"`, `mime_types=["pdf"]`.

## Configuration (env vars)

| Var | Default | Purpose |
|-----|---------|---------|
| `GMAIL_CREDENTIALS` | `./credentials.json` | OAuth client secret path. |
| `GMAIL_TOKEN` | `./token.json` | Cached user token path. |
| `GMAIL_ATTACHMENTS_DIR` | `~/Downloads/gmail-attachments` | Default download folder. |

## Safety notes

- **Read-only.** The server cannot send, delete, or modify mail.
- `credentials.json` and `token.json` are secrets — they're git-ignored. Never commit them.
- Message scans are capped (default 25, hard cap 200) so a broad query can't
  fan out into thousands of API calls.

## Tests

```bash
.venv/bin/python test_gmail_client.py
```

Offline unit tests (fake Gmail service) covering search, MIME filtering,
filename sanitizing, collision handling, and file writes.
