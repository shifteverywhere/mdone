"""
Tests for notification backends — unit tests using mocks/patches.
No real HTTP calls, SMTP connections, or OS commands are made.
"""

import json
import sys
import pytest
from unittest.mock import patch, MagicMock, call

from todo.notify.backends import get_backend, BaseBackend
from todo.notify.backends.stdout import StdoutBackend
from todo.notify.backends.os_notif import OSBackend
from todo.notify.backends.email import EmailBackend, EmailBackend as _Email
from todo.notify.backends.slack import SlackBackend
from todo.notify.backends.webhook import WebhookBackend, _expand_env


PAYLOAD = {
    "id": "abc12345",
    "title": "Fix production bug",
    "due": "2026-04-13T14:00",
    "notify": "30m",
    "priority": 1,
    "tags": ["work"],
    "overdue": False,
    "minutes_until_due": 28,
}

CONFIG: dict = {
    "notifications": {
        "backend": "stdout",
        "poll_interval": 60,
        "email": {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "from": "bot@example.com",
            "to": "user@example.com",
            "username_env": "SMTP_USER",
            "password_env": "SMTP_PASS",
        },
        "slack": {"webhook_url_env": "SLACK_WEBHOOK_URL"},
        "webhook": {
            "url": "https://hooks.example.com/notify",
            "method": "POST",
            "headers": {"Authorization": "Bearer $NOTIFY_TOKEN"},
        },
    }
}


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

class TestGetBackend:
    def test_returns_stdout(self):
        assert isinstance(get_backend("stdout", CONFIG), StdoutBackend)

    def test_returns_os(self):
        assert isinstance(get_backend("os", CONFIG), OSBackend)

    def test_returns_email(self):
        assert isinstance(get_backend("email", CONFIG), EmailBackend)

    def test_returns_slack(self):
        assert isinstance(get_backend("slack", CONFIG), SlackBackend)

    def test_returns_webhook(self):
        assert isinstance(get_backend("webhook", CONFIG), WebhookBackend)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            get_backend("carrier-pigeon", CONFIG)

    def test_all_backends_are_base_subclass(self):
        for name in ("stdout", "os", "email", "slack", "webhook"):
            assert isinstance(get_backend(name, CONFIG), BaseBackend)


# ---------------------------------------------------------------------------
# StdoutBackend
# ---------------------------------------------------------------------------

class TestStdoutBackend:
    def test_returns_true(self, capsys):
        be = StdoutBackend()
        result = be.send(PAYLOAD, CONFIG)
        assert result is True

    def test_prints_json(self, capsys):
        be = StdoutBackend()
        be.send(PAYLOAD, CONFIG)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["id"] == PAYLOAD["id"]
        assert data["title"] == PAYLOAD["title"]


# ---------------------------------------------------------------------------
# OSBackend
# ---------------------------------------------------------------------------

class TestOSBackend:
    def test_macos_success(self):
        be = OSBackend()
        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = be.send(PAYLOAD, CONFIG)
        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "osascript" in cmd

    def test_macos_failure_returns_false(self):
        import subprocess
        be = OSBackend()
        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "osascript")):
            result = be.send(PAYLOAD, CONFIG)
        assert result is False

    def test_linux_calls_notify_send(self):
        be = OSBackend()
        with patch("platform.system", return_value="Linux"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = be.send(PAYLOAD, CONFIG)
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "notify-send" in cmd

    def test_unsupported_platform_returns_false(self):
        be = OSBackend()
        with patch("platform.system", return_value="FreeBSD"):
            result = be.send(PAYLOAD, CONFIG)
        assert result is False

    def test_overdue_label_in_body(self):
        be = OSBackend()
        overdue_payload = {**PAYLOAD, "overdue": True}
        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            be.send(overdue_payload, CONFIG)
        script_arg = mock_run.call_args[0][0][2]   # the -e argument
        assert "OVERDUE" in script_arg


# ---------------------------------------------------------------------------
# EmailBackend
# ---------------------------------------------------------------------------

class TestEmailBackend:
    def test_sends_email(self, monkeypatch):
        monkeypatch.setenv("SMTP_USER", "user@example.com")
        monkeypatch.setenv("SMTP_PASS", "secret")

        mock_smtp = MagicMock()
        mock_smtp.__enter__ = lambda s: s
        mock_smtp.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", return_value=mock_smtp):
            be = EmailBackend()
            result = be.send(PAYLOAD, CONFIG)

        assert result is True
        mock_smtp.sendmail.assert_called_once()

    def test_missing_config_returns_false(self):
        be = EmailBackend()
        result = be.send(PAYLOAD, {"notifications": {"email": {}}})
        assert result is False

    def test_smtp_error_returns_false(self, monkeypatch):
        import smtplib
        monkeypatch.setenv("SMTP_USER", "u")
        monkeypatch.setenv("SMTP_PASS", "p")

        with patch("smtplib.SMTP", side_effect=smtplib.SMTPException("fail")):
            be = EmailBackend()
            result = be.send(PAYLOAD, CONFIG)
        assert result is False

    def test_subject_contains_title(self):
        subject, _ = EmailBackend._format(PAYLOAD)
        assert "Fix production bug" in subject

    def test_subject_overdue_label(self):
        subject, _ = EmailBackend._format({**PAYLOAD, "overdue": True})
        assert "OVERDUE" in subject

    def test_body_contains_all_fields(self):
        _, body = EmailBackend._format(PAYLOAD)
        assert "Fix production bug" in body
        assert "2026-04-13T14:00" in body
        assert "p1" in body
        assert "@work" in body
        assert "abc12345" in body

    def test_credentials_read_from_env(self, monkeypatch):
        monkeypatch.setenv("SMTP_USER", "envuser")
        monkeypatch.setenv("SMTP_PASS", "envpass")
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = lambda s: s
        mock_smtp.__exit__ = MagicMock(return_value=False)
        with patch("smtplib.SMTP", return_value=mock_smtp):
            EmailBackend().send(PAYLOAD, CONFIG)
        mock_smtp.login.assert_called_once_with("envuser", "envpass")


# ---------------------------------------------------------------------------
# SlackBackend
# ---------------------------------------------------------------------------

class TestSlackBackend:
    def _mock_response(self, status=200):
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_sends_to_webhook(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        with patch("urllib.request.urlopen", return_value=self._mock_response(200)):
            result = SlackBackend().send(PAYLOAD, CONFIG)
        assert result is True

    def test_missing_env_var_returns_false(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        result = SlackBackend().send(PAYLOAD, CONFIG)
        assert result is False

    def test_http_error_returns_false(self, monkeypatch):
        import urllib.error
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("connection refused")):
            result = SlackBackend().send(PAYLOAD, CONFIG)
        assert result is False

    def test_blocks_contain_title(self):
        blocks = SlackBackend._build_blocks(PAYLOAD)
        header_text = blocks["blocks"][0]["text"]["text"]
        assert "Fix production bug" in header_text

    def test_blocks_overdue_label(self):
        blocks = SlackBackend._build_blocks({**PAYLOAD, "overdue": True})
        fields_text = str(blocks["blocks"][1]["fields"])
        assert "OVERDUE" in fields_text

    def test_blocks_contain_id(self):
        blocks = SlackBackend._build_blocks(PAYLOAD)
        context_text = str(blocks["blocks"][2]["elements"])
        assert "abc12345" in context_text

    def test_posted_body_is_valid_json(self, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        captured = {}
        def fake_urlopen(req, timeout=None):
            captured["data"] = json.loads(req.data)
            return self._mock_response(200)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            SlackBackend().send(PAYLOAD, CONFIG)
        assert "blocks" in captured["data"]


# ---------------------------------------------------------------------------
# WebhookBackend
# ---------------------------------------------------------------------------

class TestWebhookBackend:
    def _mock_response(self, status=200):
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_sends_post(self):
        with patch("urllib.request.urlopen", return_value=self._mock_response(200)):
            result = WebhookBackend().send(PAYLOAD, CONFIG)
        assert result is True

    def test_no_url_returns_false(self):
        cfg = {"notifications": {"webhook": {}}}
        result = WebhookBackend().send(PAYLOAD, cfg)
        assert result is False

    def test_http_error_returns_false(self):
        import urllib.error
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError(
                       "url", 500, "Internal Server Error", {}, None)):
            result = WebhookBackend().send(PAYLOAD, CONFIG)
        assert result is False

    def test_posted_body_contains_full_payload(self):
        captured = {}
        def fake_urlopen(req, timeout=None):
            captured["data"] = json.loads(req.data)
            return self._mock_response(200)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            WebhookBackend().send(PAYLOAD, CONFIG)
        assert captured["data"]["id"] == PAYLOAD["id"]
        assert captured["data"]["title"] == PAYLOAD["title"]

    def test_env_var_interpolation_in_headers(self, monkeypatch):
        monkeypatch.setenv("NOTIFY_TOKEN", "secret-token")
        captured = {}
        def fake_urlopen(req, timeout=None):
            captured["headers"] = dict(req.headers)
            return self._mock_response(200)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            WebhookBackend().send(PAYLOAD, CONFIG)
        assert "Bearer secret-token" in captured["headers"].get("Authorization", "")

    def test_expand_env_replaces_vars(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "abc")
        assert _expand_env("Bearer $MY_TOKEN") == "Bearer abc"

    def test_expand_env_missing_var_gives_empty(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        assert _expand_env("Bearer $MISSING_VAR") == "Bearer "

    def test_2xx_response_is_success(self):
        with patch("urllib.request.urlopen", return_value=self._mock_response(201)):
            result = WebhookBackend().send(PAYLOAD, CONFIG)
        assert result is True

    def test_3xx_response_is_failure(self):
        with patch("urllib.request.urlopen", return_value=self._mock_response(302)):
            result = WebhookBackend().send(PAYLOAD, CONFIG)
        assert result is False
