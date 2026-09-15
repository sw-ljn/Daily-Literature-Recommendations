"""Offline contract tests for the native Gmail delivery path.

No network: the Gmail/HTTP layer (``api_request``) and the OAuth refresh are
replaced with fakes, so these tests run anywhere python3 does.
"""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
from contextlib import redirect_stdout
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parseaddr
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT / ".agents/skills/daily-literature-recommendations/scripts"
DELIVERY_SCRIPT = SCRIPTS / "gmail_delivery.py"
HISTORY_SCRIPT = SCRIPTS / "history.py"


def load_module():
    spec = importlib.util.spec_from_file_location("gmail_delivery", DELIVERY_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gmail_delivery"] = module
    spec.loader.exec_module(module)
    return module


gd = load_module()


class FakeGmail:
    """Minimal in-memory Gmail: labels, messages, modify, send."""

    def __init__(self, labels=None, address="reader@example.com"):
        self.labels = list(
            labels
            if labels is not None
            else [
                {"id": "Label_1", "name": "Literature recommendations", "type": "user"},
                {"id": "INBOX", "name": "INBOX", "type": "system"},
            ]
        )
        self.messages: dict[str, list[str]] = {}
        self.subjects: dict[str, str] = {}
        self.sent: list[dict] = []
        self.calls: list[tuple[str, str, dict | None]] = []
        self.address = address
        self._next_id = 100

    def seed(self, message_id: str, subject: str, label_ids=None):
        self.messages[message_id] = list(label_ids or ["SENT"])
        self.subjects[message_id] = subject
        return message_id

    def __call__(self, method, url, token, *, body=None, timeout=45):
        self.calls.append((method, url, body))
        if url.endswith("/profile") and method == "GET":
            return {"emailAddress": self.address}
        if url.endswith("/labels") and method == "GET":
            return {"labels": self.labels}
        if url.endswith("/labels") and method == "POST":
            label = {"id": f"Label_{self._next_id}", "name": body["name"], "type": "user"}
            self._next_id += 1
            self.labels.append(label)
            return label
        if url.endswith("/send") and method == "POST":
            self._next_id += 1
            message_id = f"msg_{self._next_id}"
            raw = body["raw"]
            parsed = message_from_bytes(base64.urlsafe_b64decode(raw))
            self.seed(message_id, str(make_header(decode_header(parsed["Subject"]))))
            self.sent.append({"id": message_id, "raw": raw})
            return {"id": message_id, "threadId": f"thread_{self._next_id}"}
        if "/messages/" in url and url.endswith("/modify") and method == "POST":
            message_id = url.split("/messages/")[1].split("/")[0]
            self.messages.setdefault(message_id, []).extend(body.get("addLabelIds", []))
            return {"id": message_id, "labelIds": self.messages[message_id]}
        if "/messages/" in url and method == "GET":
            message_id = url.split("/messages/")[1].split("?")[0]
            if message_id not in self.messages:
                raise gd.ApiError(404, "HTTP 404: Requested entity was not found")
            if "format=metadata" in url:
                return {
                    "id": message_id,
                    "payload": {"headers": [{"name": "Subject", "value": self.subjects.get(message_id, "")}]},
                }
            return {"id": message_id, "labelIds": self.messages[message_id]}
        if "/messages?q=" in url and method == "GET":
            query = urllib.parse.unquote(url.split("/messages?q=")[1].split("&")[0])
            # Mirror Gmail: `subject:(a b) in:sent` matches a message when every
            # term appears in its subject.
            terms = query.split("subject:(", 1)[1].rsplit(")", 1)[0].split()
            return {
                "messages": [
                    {"id": mid}
                    for mid, subject in self.subjects.items()
                    if all(term in subject for term in terms)
                ]
            }
        raise AssertionError(f"unexpected call {method} {url}")


def run_cli(module, argv):
    """Run main() with stdout captured; return (exit_code, payload)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = module.main(argv)
    text = buffer.getvalue().strip()
    return code, (json.loads(text) if text else {})


_ORIGINAL_API_REQUEST = gd.api_request
_ORIGINAL_GET_ACCESS_TOKEN = gd.get_access_token


def with_fake_gmail(fake):
    """Point the module's HTTP layer and auth at fakes."""
    gd.api_request = fake
    gd.get_access_token = lambda home, allow_network=True: "fake-token"


def restore_real_auth():
    """Undo with_fake_gmail so token handling is exercised for real."""
    gd.api_request = _ORIGINAL_API_REQUEST
    gd.get_access_token = _ORIGINAL_GET_ACCESS_TOKEN


def test_pure_helpers() -> None:
    assert gd.hermes_home("/tmp/x") == Path("/tmp/x")
    assert gd.label_id_for([{"id": "A", "name": "Exact"}], "Exact") == "A"
    # Never substitute a similar, differently-cased, or default label.
    assert gd.label_id_for([{"id": "A", "name": "exact"}], "Exact") is None
    assert gd.label_id_for([{"id": "A", "name": "Exact two"}], "Exact") is None
    assert gd.label_id_for([{"id": "A", "name": "Exact"}], "  ") is None

    future = time.time() + 3600
    state = gd.decode_stored_token(
        {
            "token": "t",
            "refresh_token": "r",
            "client_id": "c",
            "client_secret": "s",
            "scopes": list(gd.GMAIL_SCOPES),
            "expiry": "2099-01-01T00:00:00Z",
        }
    )
    assert state["valid"] is True
    expired = gd.decode_stored_token({"token": "t", "expiry": "2020-01-01T00:00:00Z"})
    assert expired["valid"] is False
    # google-auth's own numeric expiry_date style (milliseconds)
    ms = gd.decode_stored_token({"token": "t", "expiry_date": (future * 1000)})
    assert ms["valid"] is True
    assert gd.missing_gmail_scopes(list(gd.GMAIL_SCOPES)) == []
    assert gd.missing_gmail_scopes(["https://www.googleapis.com/auth/gmail.readonly"])

    raw = gd.build_message(
        sender='"Codex" <bot@example.com>',
        to="me@example.com",
        subject="[每日文献推荐] 测试 | 2026-09-14 09:00",
        body="你好，本次推荐 0 篇。",
    )
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw))
    assert str(make_header(decode_header(parsed["Subject"]))) == "[每日文献推荐] 测试 | 2026-09-14 09:00"
    assert parsed["To"] == "me@example.com"
    assert parsed["From"] == '"Codex" <bot@example.com>'
    assert parsed["Message-ID"]
    body_text = parsed.get_payload(decode=True).decode("utf-8")
    assert "本次推荐 0 篇" in body_text

    html_raw = gd.build_message(sender=None, to="a@b.c", subject="s", body="<p>hi</p>", html=True)
    assert message_from_bytes(base64.urlsafe_b64decode(html_raw)).get_content_type() == "text/html"

    for bad in ({"sender": None, "to": "  ", "subject": "s", "body": "b"},
                {"sender": None, "to": "a@b.c", "subject": " ", "body": "b"}):
        try:
            gd.build_message(**bad)
        except gd.UsageError:
            pass
        else:
            raise AssertionError("empty recipient/subject must be rejected")
    print("pure helpers: ok")


def test_label_exact_and_create() -> None:
    fake = FakeGmail()
    with_fake_gmail(fake)
    fake.messages["msg_1"] = ["SENT"]
    code, payload = run_cli(
        gd, ["label", "--message-id", "msg_1", "--label", "Literature recommendations"]
    )
    assert code == 0, payload
    assert payload["status"] == "applied"
    assert payload["label_id"] == "Label_1"
    assert payload["created"] is False
    assert payload["verified"] is True
    assert payload["gmail_label_expected"] == "Literature recommendations"
    assert payload["gmail_label_applied"] == "Literature recommendations"
    assert fake.messages["msg_1"] == ["SENT", "Label_1"]

    # Missing label -> created with the exact configured name, then verified.
    fake2 = FakeGmail()
    with_fake_gmail(fake2)
    code, payload = run_cli(
        gd, ["label", "--message-id", "msg_9", "--label", "结构操作 Agent 的材料性能优化应用"]
    )
    assert code == 0, payload
    assert payload["created"] is True
    assert payload["verified"] is True
    assert any(label["name"] == "结构操作 Agent 的材料性能优化应用" for label in fake2.labels)

    # --no-create must fail rather than inventing a label.
    fake3 = FakeGmail()
    with_fake_gmail(fake3)
    code, payload = run_cli(
        gd, ["label", "--message-id", "msg_9", "--label", "Not there", "--no-create"]
    )
    assert code == gd.EXIT_LABEL_FAILED, payload
    assert "does not exist" in payload["error"]

    # A write that does not stick must be reported as failure, not success.
    fake4 = FakeGmail()
    with_fake_gmail(fake4)
    fake4.messages["msg_5"] = ["SENT"]
    original = fake4.__call__

    def swallow_modify(method, url, token, *, body=None, timeout=45):
        if url.endswith("/modify"):
            fake4.calls.append((method, url, body))
            return {"id": "msg_5", "labelIds": ["SENT"]}
        return original(method, url, token, body=body, timeout=timeout)

    gd.api_request = swallow_modify
    code, payload = run_cli(
        gd, ["label", "--message-id", "msg_5", "--label", "Literature recommendations"]
    )
    assert code == gd.EXIT_LABEL_FAILED, payload
    assert "not found on message" in payload["error"]

    # verify-label is read-only and reports absence without writing.
    fake5 = FakeGmail()
    with_fake_gmail(fake5)
    fake5.messages["msg_7"] = ["SENT"]
    code, payload = run_cli(
        gd, ["verify-label", "--message-id", "msg_7", "--label", "Literature recommendations"]
    )
    assert code == gd.EXIT_LABEL_FAILED
    assert payload["status"] == "not_applied"
    assert not any(url.endswith("/modify") for _, url, _ in fake5.calls)
    print("exact label resolve/create/apply/verify: ok")


def test_send_and_failure_exit_codes() -> None:
    fake = FakeGmail()
    with_fake_gmail(fake)
    code, payload = run_cli(
        gd,
        ["send", "--to", "me", "--subject", "[每日文献推荐] x", "--body", "正文"],
    )
    assert code == 0, payload
    assert payload["status"] == "sent"
    assert payload["to"] == "reader@example.com"  # 'me' resolves to the authenticated address
    assert payload["id"] == "msg_101"
    sent_message = message_from_bytes(base64.urlsafe_b64decode(fake.sent[0]["raw"]))
    assert sent_message["To"] == "reader@example.com"
    assert sent_message.get_payload(decode=True).decode("utf-8") == "正文"

    # Send failure -> exit 2 (the agent must not append delivered history).
    def failing_send(method, url, token, *, body=None, timeout=45):
        if url.endswith("/send"):
            raise gd.ApiError(403, "HTTP 403: Insufficient Permission (insufficientPermissions)")
        return fake(method, url, token, body=body, timeout=timeout)

    gd.api_request = failing_send
    code, payload = run_cli(gd, ["send", "--to", "me", "--subject", "s", "--body", "b"])
    assert code == gd.EXIT_SEND_FAILED, payload
    assert "insufficientPermissions" in payload["error"]

    # Auth failure -> exit 4.
    def no_token(home, allow_network=True):
        raise gd.AuthError("no OAuth token at C:/x/google_token.json")

    gd.get_access_token = no_token
    code, payload = run_cli(gd, ["send", "--to", "me", "--subject", "s", "--body", "b"])
    assert code == gd.EXIT_AUTH_FAILED, payload

    # Usage failure -> exit 5.
    with_fake_gmail(FakeGmail())
    code, payload = run_cli(gd, ["send", "--to", "me", "--subject", "s"])
    assert code == gd.EXIT_USAGE, payload
    print("send + failure exit codes: ok")


def test_auth_check_without_token() -> None:
    restore_real_auth()
    with tempfile.TemporaryDirectory() as temp_dir:
        code, payload = run_cli(
            gd, ["--hermes-home", temp_dir, "auth-check"]
        )
        assert code == gd.EXIT_AUTH_FAILED, payload
        assert payload["status"] == "unauthenticated"
        assert str(Path(temp_dir) / "google_token.json") in payload["token_path"]

        token_file = Path(temp_dir) / "google_token.json"
        token_file.write_text(
            json.dumps(
                {
                    "token": "t",
                    "refresh_token": "r",
                    "client_id": "c",
                    "client_secret": "s",
                    "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
                    "expiry": "2099-01-01T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        code, payload = run_cli(gd, ["--hermes-home", temp_dir, "auth-check"])
        assert code == gd.EXIT_AUTH_FAILED, payload
        assert payload["missing_scopes"] == [
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
        ]
    print("auth-check: ok")


def test_label_retry_updates_history_without_resend() -> None:
    """deliver -> record pending -> label -> mark applied, with one send only."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        fake = FakeGmail()
        with_fake_gmail(fake)
        code, sent = run_cli(
            gd, ["send", "--to", "me", "--subject", "[每日文献推荐] t | 2026-09-14 09:00", "--body", "b"]
        )
        assert code == 0, sent

        selected = root / "selected.jsonl"
        selected.write_text(
            json.dumps(
                {
                    "canonical_id": "doi:10.1/test",
                    "normalized_title": "test",
                    "title": "Test",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        history = root / "recommendations.jsonl"
        run_json = root / "run.json"
        run_json.write_text(
            json.dumps({"email_subject": "[每日文献推荐] t | 2026-09-14 09:00"}),
            encoding="utf-8",
        )

        subprocess.run(
            [
                sys.executable, str(HISTORY_SCRIPT), "record-delivery",
                "--history", str(history), "--input", str(selected),
                "--task-id", "test-task", "--run-key", "test-task:2026-09-14T09-00-00",
                "--email-subject", "[每日文献推荐] t | 2026-09-14 09:00",
                "--gmail-label", "结构操作 Agent 的材料性能优化应用",
                "--label-status", "pending",
            ],
            check=True, capture_output=True, text=True,
        )

        # Label write fails (scope revoked) -> delivered history keeps pending.
        def failing_modify(method, url, token, *, body=None, timeout=45):
            if url.endswith("/modify"):
                raise gd.ApiError(403, "HTTP 403: Insufficient Permission")
            return fake(method, url, token, body=body, timeout=timeout)

        gd.api_request = failing_modify
        code, payload = run_cli(
            gd, ["label", "--run-json", str(run_json), "--label", "结构操作 Agent 的材料性能优化应用"]
        )
        assert code == gd.EXIT_LABEL_FAILED, payload
        row = json.loads(history.read_text(encoding="utf-8").strip())
        assert row["delivery_status"] == "delivered"
        assert row["label_status"] == "pending"

        # Retry the label only: no second send, history flips to applied.
        with_fake_gmail(fake)
        code, payload = run_cli(
            gd, ["label", "--run-json", str(run_json), "--label", "结构操作 Agent 的材料性能优化应用"]
        )
        assert code == 0, payload
        assert len(fake.sent) == 1, "a label retry must never resend the email"

        result = subprocess.run(
            [
                sys.executable, str(HISTORY_SCRIPT), "mark-label-status",
                "--history", str(history), "--task-id", "test-task",
                "--run-key", "test-task:2026-09-14T09-00-00",
                "--gmail-label", "结构操作 Agent 的材料性能优化应用",
                "--status", "applied",
            ],
            check=True, capture_output=True, text=True,
        )
        assert json.loads(result.stdout)["updated"] == 1
        row = json.loads(history.read_text(encoding="utf-8").strip())
        assert row["label_status"] == "applied"

        # A wrong/foreign label name must not match rows.
        rejected = subprocess.run(
            [
                sys.executable, str(HISTORY_SCRIPT), "mark-label-status",
                "--history", str(history), "--task-id", "test-task",
                "--run-key", "test-task:2026-09-14T09-00-00",
                "--gmail-label", "Literature recommendations",
                "--status", "applied",
            ],
            check=False, capture_output=True, text=True,
        )
        assert rejected.returncode != 0
        assert "No delivered rows" in rejected.stderr

        # Subject-based lookup must never invent a message: unknown subject -> 3,
        # ambiguous subject -> 5 (the agent must disambiguate explicitly).
        code, payload = run_cli(
            gd, ["label", "--subject", "[每日文献推荐] not sent", "--label", "x"]
        )
        assert code == gd.EXIT_LABEL_FAILED, payload
        assert payload["status"] == "failed"

        fake.seed("msg_777", "[每日文献推荐] t | 2026-09-14 09:00")
        code, payload = run_cli(
            gd, ["label", "--subject", "[每日文献推荐] t | 2026-09-14 09:00", "--label", "x"]
        )
        assert code == gd.EXIT_USAGE, payload
        assert "share subject" in payload["error"]

        code, payload = run_cli(gd, ["find-message", "--subject", "[每日文献推荐] t | 2026-09-14 09:00"])
        assert code == 0, payload
        assert payload["message_ids"] == [sent["id"], "msg_777"]
    print("label retry without resend: ok")


def test_hermes_home_resolution() -> None:
    """Explicit > $HERMES_HOME > ~/.hermes, with a Windows-install fallback."""
    saved = {k: os.environ.get(k) for k in ("HERMES_HOME", "LOCALAPPDATA", "XDG_DATA_HOME")}
    try:
        for key in ("HERMES_HOME", "LOCALAPPDATA", "XDG_DATA_HOME"):
            os.environ.pop(key, None)
        assert gd.hermes_home("/tmp/explicit") == Path("/tmp/explicit")
        assert gd.hermes_home() == Path.home() / ".hermes"

        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "hermes"
            home.mkdir()
            os.environ["LOCALAPPDATA"] = temp_dir
            # No token anywhere -> keep the documented default.
            assert gd.hermes_home() == Path.home() / ".hermes"
            (home / gd.TOKEN_FILENAME).write_text("{}", encoding="utf-8")
            assert gd.hermes_home() == home

        os.environ["HERMES_HOME"] = "C:/custom/home"
        assert gd.hermes_home() == Path("C:/custom/home")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    print("hermes home resolution: ok")


def test_sender_display_name_resolution() -> None:
    """A bare --from name is paired with the authenticated address."""
    fake = FakeGmail(address="reader@example.com")
    with_fake_gmail(fake)

    assert gd.resolve_sender("fake-token", None) is None
    assert gd.resolve_sender("fake-token", "   ") is None
    # A bare display name resolves to the authenticated address, never a hard-coded one.
    name, address = parseaddr(gd.resolve_sender("fake-token", "daily-lit"))
    assert (name, address) == ("daily-lit", "reader@example.com")
    # An explicit address always wins over the account default.
    explicit = '"Other" <other@example.com>'
    assert gd.resolve_sender("fake-token", explicit) == explicit

    code, payload = run_cli(
        gd,
        [
            "send",
            "--to",
            "me",
            "--subject",
            "sender display check",
            "--from",
            "daily-lit",
            "--body",
            "x",
        ],
    )
    assert code == 0, payload
    assert payload["from"] == "daily-lit <reader@example.com>"
    parsed = message_from_bytes(base64.urlsafe_b64decode(fake.sent[-1]["raw"]))
    assert parseaddr(parsed["From"]) == ("daily-lit", "reader@example.com")
    print("sender display name: ok")


def test_subject_query_sanitization() -> None:
    """Real subjects carry [] and | that Gmail's query grammar would eat."""
    terms = gd.subject_query_terms("[每日文献推荐] 命名迁移验证 | 2026-09-14 21:02")
    assert terms == "每日文献推荐 命名迁移验证 2026 09 14 21 02", terms
    assert not (set(terms) & gd.GMAIL_QUERY_UNSAFE), "operator characters must not survive"
    assert gd.subject_query_terms('[Apple] | Pear (2026-09-14)') == "Apple Pear 2026 09 14"
    # Single ASCII characters are dropped as noise; CJK stays (no word spaces).
    assert gd.subject_query_terms('("a") [b] | 中文') == "中文"
    assert gd.subject_query_terms("   ") == ""
    print("subject query sanitization: ok")


def main() -> int:
    test_pure_helpers()
    test_hermes_home_resolution()
    test_label_exact_and_create()
    test_send_and_failure_exit_codes()
    test_auth_check_without_token()
    test_label_retry_updates_history_without_resend()
    test_sender_display_name_resolution()
    test_subject_query_sanitization()
    print("gmail delivery contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
