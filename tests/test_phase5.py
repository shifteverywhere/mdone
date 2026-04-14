"""
Phase 5 polish tests:
  - --dry-run on done / edit / delete / snooze
  - Config defaults: default_tags, default_priority, default_notify, date_format
  - shell completions command
"""

import json
import pytest
from click.testing import CliRunner
from todo.cli import cli
from todo.storage import add_task, read_tasks, _archive_file
from todo.models import Task
from todo.config import (
    load_config, get_default_tags, get_default_priority,
    get_default_notify, get_date_format,
)


@pytest.fixture(autouse=True)
def isolated_todo_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TODO_DIR", str(tmp_path))


@pytest.fixture
def runner():
    return CliRunner()


def _add(runner, task_string):
    result = runner.invoke(cli, ["add", task_string, "--json"])
    assert result.exit_code == 0
    return json.loads(result.output)


# ---------------------------------------------------------------------------
# --dry-run on done
# ---------------------------------------------------------------------------

class TestDryRunDone:
    def test_dry_run_does_not_archive(self, runner):
        d = _add(runner, "Task to complete")
        result = runner.invoke(cli, ["done", d["id"], "--dry-run"])
        assert result.exit_code == 0
        # Task still in tasks.md
        assert any(t.id == d["id"] for t in read_tasks())
        # archive.md not created
        assert not _archive_file().exists()

    def test_dry_run_returns_json(self, runner):
        d = _add(runner, "Task")
        result = runner.invoke(cli, ["done", d["id"], "--dry-run"])
        data = json.loads(result.output)
        assert data[0]["completed"]["id"] == d["id"]
        assert data[0]["dry_run"] is True

    def test_dry_run_shows_spawned_for_recurring(self, runner):
        d = _add(runner, "Weekly task due:2026-04-13 recur:weekly")
        result = runner.invoke(cli, ["done", d["id"], "--dry-run"])
        data = json.loads(result.output)
        assert data[0]["spawned"] is not None
        assert data[0]["spawned"]["due"] == "2026-04-20"
        # Original task still active
        assert any(t.id == d["id"] for t in read_tasks())

    def test_dry_run_bulk(self, runner):
        d1 = _add(runner, "Task 1")
        d2 = _add(runner, "Task 2")
        result = runner.invoke(cli, ["done", d1["id"], d2["id"], "--dry-run"])
        data = json.loads(result.output)
        assert len(data) == 2
        assert len(read_tasks()) == 2   # nothing removed


# ---------------------------------------------------------------------------
# --dry-run on edit
# ---------------------------------------------------------------------------

class TestDryRunEdit:
    def test_dry_run_does_not_persist(self, runner):
        d = _add(runner, "Original title")
        runner.invoke(cli, ["edit", d["id"], "New title", "--dry-run"])
        task = read_tasks()[0]
        assert task.title == "Original title"

    def test_dry_run_returns_preview_json(self, runner):
        d = _add(runner, "Original title")
        result = runner.invoke(cli, ["edit", d["id"], "New title", "--dry-run"])
        data = json.loads(result.output)
        assert data["title"] == "New title"
        assert data["id"] == d["id"]

    def test_dry_run_set_field_preview(self, runner):
        d = _add(runner, "Task")
        result = runner.invoke(
            cli, ["edit", d["id"], "--set", "priority:1", "--dry-run"]
        )
        data = json.loads(result.output)
        assert data["priority"] == 1
        # Still priority 4 on disk
        assert read_tasks()[0].priority == 4


# ---------------------------------------------------------------------------
# --dry-run on delete
# ---------------------------------------------------------------------------

class TestDryRunDelete:
    def test_dry_run_does_not_delete(self, runner):
        d = _add(runner, "Keep me")
        result = runner.invoke(cli, ["delete", d["id"], "--dry-run"])
        assert result.exit_code == 0
        assert any(t.id == d["id"] for t in read_tasks())

    def test_dry_run_returns_json(self, runner):
        d = _add(runner, "Task")
        result = runner.invoke(cli, ["delete", d["id"], "--dry-run"])
        data = json.loads(result.output)
        assert data["deleted"] == d["id"]
        assert data["dry_run"] is True
        assert data["task"]["id"] == d["id"]

    def test_rm_dry_run(self, runner):
        d = _add(runner, "Task")
        runner.invoke(cli, ["rm", d["id"], "--dry-run"])
        assert len(read_tasks()) == 1


# ---------------------------------------------------------------------------
# --dry-run on snooze
# ---------------------------------------------------------------------------

class TestDryRunSnooze:
    def test_dry_run_does_not_set_snooze(self, runner):
        d = _add(runner, "Alert task")
        runner.invoke(cli, ["snooze", d["id"], "2099-12-31T23:59", "--dry-run"])
        task = read_tasks()[0]
        assert task.snooze is None

    def test_dry_run_returns_preview_json(self, runner):
        d = _add(runner, "Alert task")
        result = runner.invoke(cli, ["snooze", d["id"], "2099-12-31T23:59", "--dry-run"])
        data = json.loads(result.output)
        assert data["snooze"] == "2099-12-31T23:59"

    def test_dry_run_clear_does_not_persist(self, runner):
        from todo.storage import find_task, update_task
        d = _add(runner, "Snoozed task")
        task = find_task(d["id"])
        task.snooze = "2099-12-31T23:59"
        update_task(task)
        runner.invoke(cli, ["snooze", d["id"], "--clear", "--dry-run"])
        # Snooze still set on disk
        assert find_task(d["id"]).snooze == "2099-12-31T23:59"


# ---------------------------------------------------------------------------
# Config defaults applied on add
# ---------------------------------------------------------------------------

class TestConfigDefaults:
    def _write_config(self, tmp_path, content: str):
        (tmp_path / "config.toml").write_text(content)

    def test_default_tags_applied(self, runner, tmp_path):
        self._write_config(tmp_path, '[tags]\ndefault_tags = ["work", "q2"]\n')
        result = runner.invoke(cli, ["add", "Simple task", "--json"])
        data = json.loads(result.output)
        assert "work" in data["tags"]
        assert "q2" in data["tags"]

    def test_default_tags_not_duplicated(self, runner, tmp_path):
        self._write_config(tmp_path, '[tags]\ndefault_tags = ["work"]\n')
        result = runner.invoke(cli, ["add", "Task @work", "--json"])
        data = json.loads(result.output)
        assert data["tags"].count("work") == 1

    def test_default_priority_applied(self, runner, tmp_path):
        self._write_config(tmp_path, '[general]\ndefault_priority = 2\n')
        result = runner.invoke(cli, ["add", "Task with no priority", "--json"])
        data = json.loads(result.output)
        assert data["priority"] == 2

    def test_explicit_priority_overrides_default(self, runner, tmp_path):
        self._write_config(tmp_path, '[general]\ndefault_priority = 2\n')
        result = runner.invoke(cli, ["add", "Urgent task priority:1", "--json"])
        data = json.loads(result.output)
        assert data["priority"] == 1

    def test_default_notify_applied(self, runner, tmp_path):
        self._write_config(tmp_path,
            '[notifications]\ndefault_notify = "30m"\nbackend = "stdout"\n')
        result = runner.invoke(cli, ["add", "Task due:2099-12-31", "--json"])
        data = json.loads(result.output)
        assert data["notify"] == "30m"

    def test_explicit_notify_overrides_default(self, runner, tmp_path):
        self._write_config(tmp_path,
            '[notifications]\ndefault_notify = "30m"\nbackend = "stdout"\n')
        result = runner.invoke(cli, ["add", "Task due:2099-12-31 notify:2h", "--json"])
        data = json.loads(result.output)
        assert data["notify"] == "2h"

    def test_no_default_notify_without_config(self, runner):
        result = runner.invoke(cli, ["add", "Task", "--json"])
        data = json.loads(result.output)
        assert data["notify"] is None


# ---------------------------------------------------------------------------
# Config: load_config helpers
# ---------------------------------------------------------------------------

class TestConfigHelpers:
    def test_get_default_tags_empty_by_default(self):
        assert get_default_tags({}) == []

    def test_get_default_priority_is_4(self):
        assert get_default_priority({}) == 4

    def test_get_default_notify_empty(self):
        assert get_default_notify({}) == ""

    def test_get_date_format_default(self):
        assert get_date_format({}) == "%Y-%m-%d"

    def test_get_date_format_custom(self):
        cfg = {"general": {"date_format": "%d/%m/%Y"}}
        assert get_date_format(cfg) == "%d/%m/%Y"

    def test_load_config_reads_toml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TODO_DIR", str(tmp_path))
        (tmp_path / "config.toml").write_text(
            '[general]\ndate_format = "%d/%m/%Y"\n'
        )
        cfg = load_config()
        assert cfg["general"]["date_format"] == "%d/%m/%Y"

    def test_load_config_merges_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TODO_DIR", str(tmp_path))
        (tmp_path / "config.toml").write_text('[general]\ndefault_priority = 1\n')
        cfg = load_config()
        # User value present
        assert cfg["general"]["default_priority"] == 1
        # Default value still present for unset keys
        assert cfg["notifications"]["backend"] == "stdout"

    def test_config_init_and_show(self, runner):
        runner.invoke(cli, ["config", "--init"])
        result = runner.invoke(cli, ["config", "--show", "--json"])
        data = json.loads(result.output)
        assert "general" in data
        assert "tags" in data
        assert "notifications" in data


# ---------------------------------------------------------------------------
# Shell completions command
# ---------------------------------------------------------------------------

class TestCompletionsCommand:
    def test_prints_script_for_bash(self, runner):
        from unittest.mock import patch
        with patch("todo.cli.get_script", return_value="# bash completion\n"):
            result = runner.invoke(cli, ["completions", "--shell", "bash"])
        assert result.exit_code == 0
        assert "bash completion" in result.output

    def test_prints_script_for_zsh(self, runner):
        from unittest.mock import patch
        with patch("todo.cli.get_script", return_value="# zsh completion\n"):
            result = runner.invoke(cli, ["completions", "--shell", "zsh"])
        assert result.exit_code == 0

    def test_prints_script_for_fish(self, runner):
        from unittest.mock import patch
        with patch("todo.cli.get_script", return_value="# fish completion\n"):
            result = runner.invoke(cli, ["completions", "--shell", "fish"])
        assert result.exit_code == 0

    def test_install_success(self, runner, tmp_path):
        from unittest.mock import patch
        with patch("todo.cli.install_completions",
                   return_value=(True, "Installed to /tmp/todo")):
            result = runner.invoke(cli, ["completions", "--shell", "bash", "--install"])
        assert result.exit_code == 0
        assert "Installed" in result.output

    def test_install_failure_exits_1(self, runner):
        from unittest.mock import patch
        with patch("todo.cli.install_completions",
                   return_value=(False, "Could not install")):
            result = runner.invoke(cli, ["completions", "--shell", "bash", "--install"])
        assert result.exit_code == 1

    def test_auto_detects_shell(self, runner, monkeypatch):
        from unittest.mock import patch
        monkeypatch.setenv("SHELL", "/usr/bin/zsh")
        with patch("todo.cli.get_script", return_value="# zsh\n") as mock_get:
            runner.invoke(cli, ["completions"])
        mock_get.assert_called_once_with("zsh")
