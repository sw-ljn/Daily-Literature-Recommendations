#!/usr/bin/env python3
"""Native Gmail delivery for the daily-literature-recommendations workflow.

Stdlib-only (no google-api-python-client, no gws binary). Talks to the Gmail
REST API with the OAuth token managed by the Hermes google-workspace skill:
``$HERMES_HOME/google_token.json`` (default ``~/.hermes``). The token is
refreshed in place when expired, so any Python 3.8+ interpreter can run this
script — cron, conda, PowerShell, or the Hermes venv.

Implements the delivery and label-filing contract in
``references/contracts.md``:

* send success is required before any history row is written;
* the label is applied by its EXACT configured name, created when absent, and
  verified on the message before reporting success;
* a label failure never triggers a resend. A retry locates the already-sent
  message by its exact ``email_subject`` (from ``run.json``) so no Gmail
  message ID ever has to be written into a run artifact.

Exit codes (stable, so the agent can branch without parsing prose):

===== ==========================================================
0     success
2     send failure  -> do not record delivered history
3     label failure -> keep delivery_status=delivered, label_status=pending
4     auth/config failure (missing token, refresh rejected, no scope)
5     invalid input / usage error
===== ==========================================================

All commands print a single JSON object on stdout.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
TOKEN_FILENAME = "google_token.json"
GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
)

EXIT_OK = 0
EXIT_SEND_FAILED = 2
EXIT_LABEL_FAILED = 3
EXIT_AUTH_FAILED = 4
EXIT_USAGE = 5


class GmailDeliveryError(Exception):
    """Base error carrying a stable exit code."""

    exit_code = EXIT_USAGE

    def __init__(self, message: str, *, status: str = "failed") -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class AuthError(GmailDeliveryError):
    exit_code = EXIT_AUTH_FAILED


class SendError(GmailDeliveryError):
    exit_code = EXIT_SEND_FAILED


class LabelError(GmailDeliveryError):
    exit_code = EXIT_LABEL_FAILED


class UsageError(GmailDeliveryError):
    exit_code = EXIT_USAGE


class ApiError(GmailDeliveryError):
    """An HTTP error returned by a Google API."""

    def __init__(self, http_status: int, message: str) -> None:
        super().__init__(message)
        self.http_status = http_status


# --------------------------------------------------------------------------
# Pure helpers (unit-tested, no network)
# --------------------------------------------------------------------------


def hermes_home(explicit: str | None = None) -> Path:
    """Resolve HERMES_HOME the way the Hermes skill scripts do.

    ``--hermes-home`` wins, then ``$HERMES_HOME``, then ``~/.hermes``. A shell
    that never had ``HERMES_HOME`` exported (plain PowerShell, a bare cron
    entry) would look in the wrong place on a Hermes desktop install, so when
    neither the explicit value nor the environment supplies one and the default
    location holds no token, an existing token under ``%LOCALAPPDATA%/hermes``
    is used instead. The resolved path is always reported by ``auth-check``.
    """
    if explicit:
        return Path(explicit).expanduser()
    val = (os.environ.get("HERMES_HOME") or "").strip()
    if val:
        return Path(val)
    default = Path.home() / ".hermes"
    if (default / TOKEN_FILENAME).exists():
        return default
    data_home = (os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") or "").strip()
    if data_home:
        candidate = Path(data_home) / "hermes"
        if (candidate / TOKEN_FILENAME).exists():
            return candidate
    return default


def token_path(home: Path) -> Path:
    return home / TOKEN_FILENAME


def decode_stored_token(payload: dict, *, now: float | None = None) -> dict:
    """Return the stored token with a normalized ``expiry_epoch``.

    Raises AuthError when the payload cannot be used at all.
    """
    now = time.time() if now is None else now
    access = payload.get("token") or payload.get("access_token") or ""
    expiry = payload.get("expiry") or payload.get("expiry_date") or ""

    expiry_epoch = 0.0
    if isinstance(expiry, (int, float)):  # expiry_date style (ms or s)
        value = float(expiry)
        expiry_epoch = value / 1000.0 if value > 1e11 else value
    elif isinstance(expiry, str) and expiry:
        text = expiry.strip().replace("Z", "+00:00")
        try:
            import datetime as _dt

            parsed = _dt.datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_dt.timezone.utc)
            expiry_epoch = parsed.timestamp()
        except ValueError:
            expiry_epoch = 0.0

    return {
        "access_token": access,
        "refresh_token": payload.get("refresh_token") or "",
        "client_id": payload.get("client_id") or "",
        "client_secret": payload.get("client_secret") or "",
        "scopes": payload.get("scopes") or [],
        "expiry_epoch": expiry_epoch,
        "valid": bool(access) and expiry_epoch > now + 60,
    }


def missing_gmail_scopes(scopes: list[str]) -> list[str]:
    """Scopes required by this script that the stored token does not carry."""
    return [scope for scope in GMAIL_SCOPES if scope not in (scopes or [])]


def label_id_for(rows: list[dict], name: str) -> str | None:
    """Exact-name lookup. Never returns a similar or system label.

    Gmail label names are case-insensitive for uniqueness but the configured
    value is treated as authoritative, so the match must be exact.
    """
    target = (name or "").strip()
    if not target:
        return None
    for row in rows:
        if str(row.get("name") or "") == target:
            return str(row.get("id") or "") or None
    return None


def build_message(
    *,
    sender: str | None,
    to: str,
    subject: str,
    body: str,
    html: bool = False,
    message_id: str | None = None,
) -> str:
    """Build a base64url-encoded RFC 5322 message for Gmail ``messages.send``."""
    if not to.strip():
        raise UsageError("recipient is empty")
    if not subject.strip():
        raise UsageError("subject is empty")
    subtype = "html" if html else "plain"
    msg = MIMEText(body, _subtype=subtype, _charset="utf-8")
    if sender:
        msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = message_id or make_msgid(domain="gmail.com")
    raw = msg.as_bytes()
    return base64.urlsafe_b64encode(raw).decode("ascii")


# --------------------------------------------------------------------------
# Network layer
# --------------------------------------------------------------------------


def api_request(
    method: str,
    url: str,
    token: str,
    *,
    body: dict | None = None,
    timeout: int = 45,
) -> dict:
    """Call a Google API and return the decoded JSON body.

    Injectable in tests: everything else in this module goes through here.
    """
    data = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        message = detail
        try:
            parsed = json.loads(detail)
            err = parsed.get("error") or {}
            if isinstance(err, dict):
                message = err.get("message") or detail
                reason = ""
                for item in err.get("errors") or []:
                    reason = item.get("reason") or reason
                if reason and reason not in message:
                    message = f"{message} ({reason})"
        except (ValueError, AttributeError):
            pass
        raise ApiError(int(exc.code), f"HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise GmailDeliveryError(f"network error: {exc.reason}") from exc
    if not payload.strip():
        return {}
    return json.loads(payload)


def refresh_access_token(payload: dict, *, now: float | None = None) -> dict:
    """Exchange the refresh token for a new access token."""
    now = time.time() if now is None else now
    if not payload.get("refresh_token"):
        raise AuthError(
            "stored token has no refresh_token; re-run the google-workspace setup"
        )
    if not payload.get("client_id") or not payload.get("client_secret"):
        raise AuthError(
            "stored token has no client credentials; re-run the google-workspace setup"
        )
    form = urllib.parse.urlencode(
        {
            "client_id": payload["client_id"],
            "client_secret": payload["client_secret"],
            "refresh_token": payload["refresh_token"],
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AuthError(f"token refresh rejected: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GmailDeliveryError(f"network error during token refresh: {exc.reason}") from exc

    access = data.get("access_token")
    if not access:
        raise AuthError(f"token refresh returned no access_token: {data}")
    expires_in = float(data.get("expires_in") or 3600)
    import datetime as _dt

    expiry = _dt.datetime.fromtimestamp(now + expires_in, tz=_dt.timezone.utc)
    return {
        "access_token": access,
        "expiry": expiry.isoformat().replace("+00:00", "Z"),
        "scopes": data.get("scope", "").split() or payload.get("scopes") or [],
    }


def write_token_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def get_access_token(home: Path, *, allow_network: bool = True) -> str:
    path = token_path(home)
    if not path.exists():
        raise AuthError(
            f"no OAuth token at {path}; run the Hermes google-workspace setup "
            "(skills/productivity/google-workspace/scripts/setup.py)"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    state = decode_stored_token(raw)

    missing = missing_gmail_scopes(state["scopes"])
    if missing:
        raise AuthError(
            "stored token is missing required Gmail scopes: "
            + ", ".join(missing)
            + " — re-authorize with setup.py"
        )

    if state["valid"]:
        return state["access_token"]
    if not allow_network:
        raise AuthError("stored access token is expired and network refresh is disabled")

    refreshed = refresh_access_token(raw)
    raw.update(
        {
            "token": refreshed["access_token"],
            "expiry": refreshed["expiry"],
            "scopes": refreshed["scopes"],
            "type": raw.get("type") or "authorized_user",
        }
    )
    try:
        write_token_atomic(path, raw)
    except OSError:
        pass  # refresh still works for this call; caching is best-effort
    return refreshed["access_token"]


# --------------------------------------------------------------------------
# Gmail operations
# --------------------------------------------------------------------------


def gmail_profile(token: str) -> dict:
    return api_request("GET", f"{GMAIL_API}/profile", token)


def resolve_recipient(token: str, to: str) -> str:
    """``recipient: me`` in a task YAML means the authenticated address."""
    if to.strip().lower() == "me":
        address = gmail_profile(token).get("emailAddress") or ""
        if not address:
            raise SendError("could not resolve the authenticated Gmail address for 'me'")
        return address
    return to


def resolve_sender(token: str, sender: str | None) -> str | None:
    """Expand a bare display name into ``"name" <authenticated address>``.

    A task config names the sender for readability (``sender_name: daily-lit``)
    without repeating the account address.  Anything containing ``@`` passes
    through untouched, so an explicit address still wins.
    """
    if not sender or not sender.strip():
        return None
    sender = sender.strip()
    if "@" in sender:
        return sender
    address = gmail_profile(token).get("emailAddress") or ""
    if not address:
        raise SendError("could not resolve the authenticated Gmail address for --from")
    return formataddr((sender, address))


def list_labels(token: str) -> list[dict]:
    data = api_request("GET", f"{GMAIL_API}/labels", token)
    return list(data.get("labels") or [])


def create_label(token: str, name: str) -> dict:
    return api_request(
        "POST",
        f"{GMAIL_API}/labels",
        token,
        body={
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    )


def message_label_ids(token: str, message_id: str) -> list[str]:
    data = api_request("GET", f"{GMAIL_API}/messages/{message_id}?format=minimal", token)
    return list(data.get("labelIds") or [])


def message_subject(token: str, message_id: str) -> str:
    data = api_request(
        "GET",
        f"{GMAIL_API}/messages/{message_id}?format=metadata&metadataHeaders=Subject",
        token,
    )
    for header in (data.get("payload") or {}).get("headers") or []:
        if str(header.get("name") or "").lower() == "subject":
            return str(header.get("value") or "")
    return ""


GMAIL_QUERY_UNSAFE = set("()[]{}\"|~^\\/:*<>-+&") | {"\u2014"}


def subject_query_terms(subject: str) -> str:
    """Reduce a subject to plain words that Gmail search treats literally.

    Gmail's query grammar gives ``() [] {} | ~ ^ " : -`` special meaning, so a
    production subject such as ``[每日文献推荐] Name | 2026-09-14 21:02`` matches
    nothing when quoted verbatim. The search only supplies candidates; exact
    equality is enforced by re-reading each candidate's decoded subject.
    """
    cleaned = "".join(
        " " if (ch in GMAIL_QUERY_UNSAFE or ch.isspace()) else ch for ch in subject
    )
    words = [
        word
        for word in cleaned.split()
        if len(word) > 1 or not word.isascii()
    ]
    return " ".join(words)


def find_sent_by_subject(token: str, subject: str) -> list[str]:
    """Return sent message IDs whose Subject header equals ``subject`` exactly.

    Used by the label retry path so no Gmail message ID has to be stored in a
    run artifact (project rule). This is a recovery lookup for the message this
    workflow already sent — never a filter for suppressing an invocation.
    """
    target = (subject or "").strip()
    if not target:
        raise UsageError("subject is empty")
    terms = subject_query_terms(target)
    if not terms:
        raise UsageError("subject has no searchable content")
    query = f"subject:({terms}) in:sent"
    data = api_request(
        "GET",
        f"{GMAIL_API}/messages?q={urllib.parse.quote(query)}&maxResults=20",
        token,
    )
    matches: list[str] = []
    for row in data.get("messages") or []:
        message_id = str(row.get("id") or "")
        if not message_id:
            continue
        if message_subject(token, message_id) == target:
            matches.append(message_id)
    return matches


def resolve_message_id(token: str, args: argparse.Namespace) -> str:
    """Locate the sent message: explicit ID, or by the run's exact subject."""
    if getattr(args, "message_id", None):
        return str(args.message_id)

    subject = getattr(args, "subject", None) or ""
    run_json = getattr(args, "run_json", None)
    if run_json and not subject:
        path = Path(run_json)
        if not path.exists():
            raise UsageError(f"run.json not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        subject = str(data.get("email_subject") or "")
        if not subject:
            raise UsageError(
                f"no email_subject recorded in {path}; pass --message-id instead"
            )
    if not subject:
        raise UsageError("provide --message-id, --subject, or --run-json")

    matches = find_sent_by_subject(token, subject)
    if not matches:
        raise LabelError(f"no sent message with subject {subject!r} found")
    if len(matches) > 1:
        raise UsageError(
            f"{len(matches)} sent messages share subject {subject!r}; pass --message-id"
        )
    return matches[0]


def send_message(token: str, raw: str, thread_id: str | None = None) -> dict:
    body: dict = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    try:
        return api_request("POST", f"{GMAIL_API}/messages/send", token, body=body)
    except ApiError as exc:
        raise SendError(f"send failed: {exc.message}") from exc


def apply_label(token: str, message_id: str, label_name: str, *, create_missing: bool) -> dict:
    """Resolve the exact label name, create it when allowed, apply, and verify."""
    rows = list_labels(token)
    label_id = label_id_for(rows, label_name)
    created = False
    if not label_id:
        if not create_missing:
            raise LabelError(f"label {label_name!r} does not exist")
        created_label = create_label(token, label_name)
        label_id = str(created_label.get("id") or "") or None
        created = True
        if not label_id:
            raise LabelError(f"Gmail created no label id for {label_name!r}")

    try:
        api_request(
            "POST",
            f"{GMAIL_API}/messages/{message_id}/modify",
            token,
            body={"addLabelIds": [label_id]},
        )
    except ApiError as exc:
        raise LabelError(f"label write failed: {exc.message}") from exc

    applied_ids = message_label_ids(token, message_id)
    verified = label_id in applied_ids
    if not verified:
        raise LabelError(
            f"label {label_name!r} ({label_id}) not found on message after the write"
        )
    return {
        "status": "applied",
        "label_name": label_name,
        "label_id": label_id,
        "gmail_label_expected": label_name,
        "gmail_label_applied": label_name,
        "created": created,
        "verified": True,
    }


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def emit(payload: dict) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def read_body(args: argparse.Namespace) -> str:
    if args.body_file:
        path = Path(args.body_file)
        if not path.exists():
            raise UsageError(f"body file not found: {path}")
        return path.read_text(encoding="utf-8")
    if args.body is not None:
        return args.body
    raise UsageError("provide --body or --body-file")


def cmd_auth_check(args: argparse.Namespace) -> int:
    home = hermes_home(args.hermes_home)
    path = token_path(home)
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    state = decode_stored_token(raw) if raw else {"scopes": [], "access_token": ""}
    result = {
        "status": "unauthenticated",
        "token_path": str(path),
        "has_refresh_token": bool(state.get("refresh_token")),
        "missing_scopes": missing_gmail_scopes(state.get("scopes") or []),
    }
    try:
        token = get_access_token(home, allow_network=args.live)
        result["status"] = "authenticated"
        result["access_token_source"] = "cache" if state.get("valid") else "refreshed"
        if args.live:
            profile = gmail_profile(token)
            result["email_address"] = profile.get("emailAddress", "")
            result["live"] = True
        else:
            result["live"] = False
    except GmailDeliveryError as exc:
        result["error"] = exc.message
        emit(result)
        return exc.exit_code
    emit(result)
    return EXIT_OK


def cmd_send(args: argparse.Namespace) -> int:
    home = hermes_home(args.hermes_home)
    body = read_body(args)
    token = get_access_token(home)
    to = resolve_recipient(token, args.to)
    sender = resolve_sender(token, args.sender)
    raw = build_message(
        sender=sender, to=to, subject=args.subject, body=body, html=args.html
    )
    result = send_message(token, raw, thread_id=args.thread_id)
    emit(
        {
            "status": "sent",
            "id": result.get("id", ""),
            "threadId": result.get("threadId", ""),
            "to": to,
            "from": sender or "",
            "subject": args.subject,
            "html": bool(args.html),
        }
    )
    return EXIT_OK


def cmd_label(args: argparse.Namespace) -> int:
    home = hermes_home(args.hermes_home)
    token = get_access_token(home)
    message_id = resolve_message_id(token, args)
    payload = apply_label(
        token, message_id, args.label, create_missing=not args.no_create
    )
    payload["message_id"] = message_id
    emit(payload)
    return EXIT_OK


def cmd_verify_label(args: argparse.Namespace) -> int:
    home = hermes_home(args.hermes_home)
    token = get_access_token(home)
    message_id = resolve_message_id(token, args)
    rows = list_labels(token)
    label_id = label_id_for(rows, args.label)
    applied_ids = message_label_ids(token, message_id)
    verified = bool(label_id) and label_id in applied_ids
    emit(
        {
            "status": "applied" if verified else "not_applied",
            "message_id": message_id,
            "label_name": args.label,
            "label_id": label_id or "",
            "verified": verified,
            "message_label_ids": applied_ids,
        }
    )
    return EXIT_OK if verified else EXIT_LABEL_FAILED


def cmd_find_message(args: argparse.Namespace) -> int:
    home = hermes_home(args.hermes_home)
    token = get_access_token(home)
    matches = find_sent_by_subject(token, args.subject)
    emit(
        {
            "status": "found" if matches else "not_found",
            "subject": args.subject,
            "message_ids": matches,
        }
    )
    return EXIT_OK if matches else EXIT_LABEL_FAILED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--hermes-home",
        default=None,
        help="Hermes home holding google_token.json (default: $HERMES_HOME or ~/.hermes)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("auth-check", help="verify the stored OAuth token")
    check.add_argument(
        "--live", action="store_true", help="also call the Gmail API and print the address"
    )
    check.set_defaults(func=cmd_auth_check)

    send = subparsers.add_parser("send", help="send one message")
    send.add_argument("--to", required=True, help="recipient; 'me' means the authenticated address")
    send.add_argument("--subject", required=True)
    send.add_argument("--body", default=None)
    send.add_argument("--body-file", default=None)
    send.add_argument("--html", action="store_true", help="send as text/html")
    send.add_argument(
        "--from",
        dest="sender",
        default=None,
        help='display sender: a bare name uses the authenticated address, e.g. "daily-lit"',
    )
    send.add_argument("--thread-id", default=None)
    send.set_defaults(func=cmd_send)

    label = subparsers.add_parser("label", help="resolve EXACT label name, create, apply, verify")
    label.add_argument("--message-id", default=None)
    label.add_argument("--run-json", default=None, help="resolve the message from its email_subject")
    label.add_argument("--subject", default=None, help="exact sent subject of the message")
    label.add_argument("--label", required=True, help="exact configured label name")
    label.add_argument("--no-create", action="store_true", help="fail instead of creating the label")
    label.set_defaults(func=cmd_label)

    verify = subparsers.add_parser("verify-label", help="read back a label without writing")
    verify.add_argument("--message-id", default=None)
    verify.add_argument("--run-json", default=None)
    verify.add_argument("--subject", default=None)
    verify.add_argument("--label", required=True)
    verify.set_defaults(func=cmd_verify_label)

    find = subparsers.add_parser(
        "find-message", help="locate an already-sent message by its exact subject"
    )
    find.add_argument("--subject", required=True)
    find.set_defaults(func=cmd_find_message)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except GmailDeliveryError as exc:
        emit({"status": exc.status, "error": exc.message, "exit_code": exc.exit_code})
        return exc.exit_code
    except KeyboardInterrupt:
        emit({"status": "failed", "error": "interrupted", "exit_code": EXIT_USAGE})
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
