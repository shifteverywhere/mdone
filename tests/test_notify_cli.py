"""
Integration tests for the `notify` and `config` CLI commands.
"""

import json
import pytest
from click.testing import CliRunner
from todo.cli import cli, SCHEMA_VERSION
from todo.storage import add_task
from todo.models import Task
from todo.notify.checker import mark_sent, load_notified


@pytest.fixture(autouse=True)
def isolated_todo_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TODO_DIR", str(tmp_path))


@pytest.fixture
def runner():
    return CliRunner()


def _unwrap(output: str) -> object:
    response = json.loads(output)
    assert response["schema_version"] == SCHEMA_VERSION
    return response["data"]


def _add_task(runner, task_string):
    result = runner.invoke(cli, ["add", task_string, "--json"])
    assert result.exit_code == 0
    return _unwrap(result.output)


# ---------------------------------------------------------------------------
# notify --check
# ---------------------------------------------------------------------------

class TestNotifyCheck:
    def test_no_pending_exits_3(self, runner):
        result = runner.invoke(cli, ["notify", "--check"])
        assert result.exit_code == 3

    def test_no_pending_json_returns_empty_list(self, runner):
        result = runner.invoke(cli, ["notify", "--check", "--json"])
        assert result.exit_code == 0
        assert _unwrap(result.output) == []

    def test_overdue_task_appears_in_check(self, runner):
        # No notify field but overdue → still surfaces
        add_task(Task(title="Old task", id="old00001", due="2020-01-01"))
        result = runner.invoke(cli, ["notify", "--check", "--json"])
        data = _unwrap(result.output)
        assert any(p["id"] == "old00001" for p in data)

    def test_in_window_task_appears(self, runner):
        # due in the past, has notify field
        add_task(Task(title="Past task", id="pst00001",
                      due="2020-01-01", notify="1d"))
        result = runner.invoke(cli, ["notify", "--check", "--json"])
        data = _unwrap(result.output)
        assert any(p["id"] == "pst00001" for p in data)

    def test_future_task_not_in_window(self, runner):
        add_task(Task(title="Far future", id="fut00001",
                      due="2099-12-31", notify="30m"))
        result = runner.invoke(cli, ["notify", "--check", "--json"])
        data = _unwrap(result.output)
        assert not any(p["id"] == "fut00001" for p in data)

    def test_already_notified_not_in_check(self, runner):
        add_task(Task(title="Old task", id="old00002", due="2020-01-01"))
        mark_sent(["old00002"])
        result = runner.invoke(cli, ["notify", "--check", "--json"])
        data = _unwrap(result.output)
        assert not any(p["id"] == "old00002" for p in data)

    def test_check_payload_fields(self, runner):
        add_task(Task(title="Old task", id="old00003", due="2020-01-01",
                      notify="1d", priority=1, tags=["work"]))
        result = runner.invoke(cli, ["notify", "--check", "--json"])
        p = _unwrap(result.output)[0]
        for field in ("id", "title", "due", "priority", "tags",
                      "overdue", "minutes_until_due"):
            assert field in p

    def test_check_human_output(self, runner):
        add_task(Task(title="Old task", id="old00004", due="2020-01-01"))
        result = runner.invoke(cli, ["notify", "--check"])
        assert result.exit_code == 0
        assert "old00004" in result.output


# ---------------------------------------------------------------------------
# notify --mark-sent
# ---------------------------------------------------------------------------

class TestMarkSent:
    def test_mark_single(self, runner):
        result = runner.invoke(cli, ["notify", "--mark-sent", "abc12345"])
        assert result.exit_code == 0
        assert "abc12345" in load_notified()

    def test_mark_multiple(self, runner):
        result = runner.invoke(
            cli, ["notify", "--mark-sent", "aaa00001", "--mark-sent", "bbb00002"]
        )
        assert result.exit_code == 0
        notified = load_notified()
        assert "aaa00001" in notified
        assert "bbb00002" in notified

    def test_mark_sent_json_output(self, runner):
        result = runner.invoke(
            cli, ["notify", "--mark-sent", "abc12345", "--json"]
        )
        data = _unwrap(result.output)
        assert "abc12345" in data["marked_sent"]

    def test_marked_task_excluded_from_check(self, runner):
        add_task(Task(title="Old task", id="old00001", due="2020-01-01"))
        runner.invoke(cli, ["notify", "--mark-sent", "old00001"])
        result = runner.invoke(cli, ["notify", "--check", "--json"])
        data = _unwrap(result.output)
        assert not any(p["id"] == "old00001" for p in data)


# ---------------------------------------------------------------------------
# notify --reset / --reset-all
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_all_clears_state(self, runner):
        mark_sent(["aaa00001", "bbb00002"])
        runner.invoke(cli, ["notify", "--reset-all"])
        assert load_notified() == {}

    def test_reset_single_id(self, runner):
        mark_sent(["aaa00001", "bbb00002"])
        runner.invoke(cli, ["notify", "--reset", "aaa00001"])
        notified = load_notified()
        assert "aaa00001" not in notified
        assert "bbb00002" in notified

    def test_reset_rearms_check(self, runner):
        add_task(Task(title="Old task", id="old00001", due="2020-01-01"))
        mark_sent(["old00001"])
        runner.invoke(cli, ["notify", "--reset-all"])
        result = runner.invoke(cli, ["notify", "--check", "--json"])
        data = _unwrap(result.output)
        assert any(p["id"] == "old00001" for p in data)


# ---------------------------------------------------------------------------
# notify --send
# ---------------------------------------------------------------------------

class TestNotifySend:
    def test_send_calls_backend(self, runner):
        from unittest.mock import patch, MagicMock
        add_task(Task(title="Task to send", id="snd00001", due="2020-01-01"))
        mock_be = MagicMock()
        mock_be.send.return_value = True
        with patch("todo.cli.get_backend", return_value=mock_be):
            result = runner.invoke(cli, ["notify", "--send", "snd00001"])
        assert result.exit_code == 0
        mock_be.send.assert_called_once()

    def test_send_marks_sent_on_success(self, runner):
        from unittest.mock import patch, MagicMock
        add_task(Task(title="Task", id="snd00002", due="2020-01-01"))
        mock_be = MagicMock()
        mock_be.send.return_value = True
        with patch("todo.cli.get_backend", return_value=mock_be):
            runner.invoke(cli, ["notify", "--send", "snd00002"])
        assert "snd00002" in load_notified()

    def test_send_failed_delivery_exits_1(self, runner):
        from unittest.mock import patch, MagicMock
        add_task(Task(title="Task", id="snd00003", due="2020-01-01"))
        mock_be = MagicMock()
        mock_be.send.return_value = False
        with patch("todo.cli.get_backend", return_value=mock_be):
            result = runner.invoke(cli, ["notify", "--send", "snd00003"])
        assert result.exit_code == 1

    def test_send_nonexistent_exits_1(self, runner):
        result = runner.invoke(cli, ["notify", "--send", "doesnotexist"])
        assert result.exit_code == 1

    def test_send_unknown_backend_exits_2(self, runner):
        add_task(Task(title="Task", id="snd00004", due="2020-01-01"))
        result = runner.invoke(
            cli, ["notify", "--send", "snd00004", "--backend", "carrier-pigeon"]
        )
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# config command
# ---------------------------------------------------------------------------

class TestConfigCommand:
    def test_init_creates_file(self, runner, tmp_path):
        result = runner.invoke(cli, ["config", "--init"])
        assert result.exit_code == 0
        assert (tmp_path / "config.toml").exists()

    def test_init_idempotent(self, runner, tmp_path):
        runner.invoke(cli, ["config", "--init"])
        runner.invoke(cli, ["config", "--init"])
        # Second call must not crash and file must still exist
        assert (tmp_path / "config.toml").exists()

    def test_show_outputs_defaults(self, runner):
        result = runner.invoke(cli, ["config", "--show"])
        assert result.exit_code == 0
        assert "notifications" in result.output

    def test_show_json_is_valid(self, runner):
        result = runner.invoke(cli, ["config", "--show", "--json"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert "notifications" in data

    def test_show_json_has_backend_key(self, runner):
        result = runner.invoke(cli, ["config", "--show", "--json"])
        data = _unwrap(result.output)
        assert "backend" in data["notifications"]

    def test_show_reflects_custom_config(self, runner, tmp_path):
        (tmp_path / "config.toml").write_text(
            '[notifications]\nbackend = "slack"\npoll_interval = 30\n'
        )
        result = runner.invoke(cli, ["config", "--show", "--json"])
        data = _unwrap(result.output)
        assert data["notifications"]["backend"] == "slack"
        assert data["notifications"]["poll_interval"] == 30
