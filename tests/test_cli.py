"""Integration tests for the CLI commands via click's CliRunner."""

import json
import pytest
from click.testing import CliRunner
from todo.cli import cli, SCHEMA_VERSION
from todo.storage import add_task, read_tasks, _archive_file
from todo.models import Task


@pytest.fixture(autouse=True)
def isolated_todo_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TODO_DIR", str(tmp_path))


@pytest.fixture
def runner():
    return CliRunner()


def _unwrap(output: str) -> object:
    """Parse a --json response and return the data payload after asserting the envelope."""
    response = json.loads(output)
    assert response["schema_version"] == SCHEMA_VERSION
    return response["data"]


def _add(runner, task_string, as_json=True):
    """Helper: add a task and return the parsed data payload."""
    args = ["add", task_string]
    if as_json:
        args.append("--json")
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    return _unwrap(result.output) if as_json else result.output


# ---------------------------------------------------------------------------
# JSON envelope contract
# ---------------------------------------------------------------------------

class TestJsonEnvelope:
    def test_envelope_has_schema_version(self, runner):
        _add(runner, "Task")  # triggers _unwrap which asserts schema_version

    def test_envelope_compact_by_default(self, runner):
        _add(runner, "Compact task")
        result = runner.invoke(cli, ["add", "Another task", "--json"])
        assert result.exit_code == 0
        # Compact JSON has no newlines inside the payload
        assert "\n" not in result.output.strip()

    def test_json_pretty_is_indented(self, runner):
        result = runner.invoke(cli, ["add", "Pretty task", "--json-pretty"])
        assert result.exit_code == 0
        # Indented JSON has multiple lines
        assert result.output.count("\n") > 1
        # Still a valid envelope
        data = _unwrap(result.output)
        assert "id" in data

    def test_json_pretty_implies_json(self, runner):
        """--json-pretty should produce machine-readable output even without --json."""
        result = runner.invoke(cli, ["list", "--json-pretty"])
        # exit 3 when empty, but the flag is accepted
        assert result.exit_code in (0, 3)


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

class TestAdd:
    def test_add_prints_id_and_title(self, runner):
        result = runner.invoke(cli, ["add", "Buy milk @shopping"])
        assert result.exit_code == 0
        assert "Buy milk" in result.output

    def test_add_json_contains_id(self, runner):
        data = _add(runner, "Buy milk @shopping")
        assert "id" in data
        assert len(data["id"]) == 8

    def test_add_json_fields(self, runner):
        data = _add(runner, "Submit report @work due:2026-04-15 priority:1")
        assert data["title"] == "Submit report"
        assert "work" in data["tags"]
        assert data["due"] == "2026-04-15"
        assert data["priority"] == 1

    def test_add_persists_to_disk(self, runner):
        _add(runner, "Persisted task @test")
        tasks = read_tasks()
        assert any(t.title == "Persisted task" for t in tasks)

    def test_add_assigns_unique_ids(self, runner):
        d1 = _add(runner, "Task one")
        d2 = _add(runner, "Task two")
        assert d1["id"] != d2["id"]


# ---------------------------------------------------------------------------
# list / ls
# ---------------------------------------------------------------------------

class TestList:
    def test_list_shows_tasks(self, runner):
        _add(runner, "Task A")
        _add(runner, "Task B")
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "Task A" in result.output
        assert "Task B" in result.output

    def test_ls_alias(self, runner):
        _add(runner, "Alias task")
        result = runner.invoke(cli, ["ls"])
        assert result.exit_code == 0
        assert "Alias task" in result.output

    def test_list_empty_exits_3(self, runner):
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 3

    def test_list_json_output(self, runner):
        _add(runner, "JSON task @work")
        result = runner.invoke(cli, ["list", "--json"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert isinstance(data, list)
        assert data[0]["title"] == "JSON task"

    def test_list_filter_by_tag(self, runner):
        _add(runner, "Work task @work")
        _add(runner, "Home task @home")
        result = runner.invoke(cli, ["list", "--tag", "work", "--json"])
        data = _unwrap(result.output)
        assert len(data) == 1
        assert "work" in data[0]["tags"]

    def test_list_filter_by_priority(self, runner):
        _add(runner, "Urgent task priority:1")
        _add(runner, "Normal task priority:4")
        result = runner.invoke(cli, ["list", "--priority", "1", "--json"])
        data = _unwrap(result.output)
        assert len(data) == 1
        assert data[0]["priority"] == 1

    def test_list_filter_overdue(self, runner):
        _add(runner, "Old task due:2020-01-01")
        _add(runner, "Future task due:2099-12-31")
        result = runner.invoke(cli, ["list", "--overdue", "--json"])
        data = _unwrap(result.output)
        assert len(data) == 1
        assert data[0]["due"] == "2020-01-01"

    def test_list_hides_done_by_default(self, runner):
        d = _add(runner, "Will be done")
        runner.invoke(cli, ["done", d["id"]])
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 3  # no open tasks

    def test_list_sort_by_priority(self, runner):
        _add(runner, "Low priority priority:4")
        _add(runner, "High priority priority:1")
        result = runner.invoke(cli, ["list", "--sort", "priority", "--json"])
        data = _unwrap(result.output)
        assert data[0]["priority"] == 1

    def test_list_sort_by_due(self, runner):
        _add(runner, "Later task due:2026-12-01")
        _add(runner, "Earlier task due:2026-01-01")
        result = runner.invoke(cli, ["list", "--sort", "due", "--json"])
        data = _unwrap(result.output)
        assert data[0]["due"] == "2026-01-01"


# ---------------------------------------------------------------------------
# done
# ---------------------------------------------------------------------------

class TestDone:
    def test_done_removes_from_active(self, runner):
        d = _add(runner, "Finish report")
        runner.invoke(cli, ["done", d["id"]])
        tasks = read_tasks()
        assert not any(t.id == d["id"] for t in tasks)

    def test_done_archives_task(self, runner, tmp_path):
        d = _add(runner, "Archive me")
        runner.invoke(cli, ["done", d["id"]])
        content = _archive_file().read_text()
        assert d["id"] in content
        assert "- [x]" in content

    def test_done_json_output(self, runner):
        d = _add(runner, "JSON done")
        result = runner.invoke(cli, ["done", d["id"], "--json"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        # Shape: [{"completed": {...}, "spawned": null}]
        assert data[0]["completed"]["id"] == d["id"]
        assert data[0]["completed"]["done"] is True
        assert data[0]["spawned"] is None

    def test_done_bulk(self, runner):
        d1 = _add(runner, "Task 1")
        d2 = _add(runner, "Task 2")
        result = runner.invoke(cli, ["done", d1["id"], d2["id"]])
        assert result.exit_code == 0
        assert read_tasks() == []

    def test_done_nonexistent_exits_1(self, runner):
        result = runner.invoke(cli, ["done", "notreal1"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# delete / rm
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_removes_task(self, runner):
        d = _add(runner, "To delete")
        result = runner.invoke(cli, ["delete", d["id"]])
        assert result.exit_code == 0
        assert read_tasks() == []

    def test_rm_alias(self, runner):
        d = _add(runner, "RM task")
        result = runner.invoke(cli, ["rm", d["id"]])
        assert result.exit_code == 0
        assert read_tasks() == []

    def test_delete_json_output(self, runner):
        d = _add(runner, "JSON delete")
        result = runner.invoke(cli, ["delete", d["id"], "--json"])
        data = _unwrap(result.output)
        assert data["deleted"] == d["id"]

    def test_delete_nonexistent_exits_1(self, runner):
        result = runner.invoke(cli, ["delete", "notreal1"])
        assert result.exit_code == 1

    def test_delete_does_not_archive(self, runner, tmp_path):
        d = _add(runner, "No archive")
        runner.invoke(cli, ["delete", d["id"]])
        assert not _archive_file().exists()


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------

class TestEdit:
    def test_edit_full_string(self, runner):
        d = _add(runner, "Old title @oldtag")
        result = runner.invoke(
            cli, ["edit", d["id"], "New title @newtag due:2026-05-01", "--json"]
        )
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["title"] == "New title"
        assert "newtag" in data["tags"]
        assert data["due"] == "2026-05-01"

    def test_edit_preserves_id(self, runner):
        d = _add(runner, "Task")
        runner.invoke(cli, ["edit", d["id"], "Renamed task"])
        tasks = read_tasks()
        assert tasks[0].id == d["id"]

    def test_edit_set_priority(self, runner):
        d = _add(runner, "Normal task")
        result = runner.invoke(cli, ["edit", d["id"], "--set", "priority:1", "--json"])
        data = _unwrap(result.output)
        assert data["priority"] == 1

    def test_edit_set_due(self, runner):
        d = _add(runner, "Undated task")
        result = runner.invoke(cli, ["edit", d["id"], "--set", "due:2026-09-01", "--json"])
        data = _unwrap(result.output)
        assert data["due"] == "2026-09-01"

    def test_edit_set_multiple_fields(self, runner):
        d = _add(runner, "Task")
        result = runner.invoke(
            cli,
            ["edit", d["id"], "--set", "priority:2", "--set", "due:2026-06-01", "--json"],
        )
        data = _unwrap(result.output)
        assert data["priority"] == 2
        assert data["due"] == "2026-06-01"

    def test_edit_unknown_field_exits_2(self, runner):
        d = _add(runner, "Task")
        result = runner.invoke(cli, ["edit", d["id"], "--set", "bogus:value"])
        assert result.exit_code == 2

    def test_edit_nonexistent_exits_1(self, runner):
        result = runner.invoke(cli, ["edit", "notreal1", "New title"])
        assert result.exit_code == 1

    def test_edit_preserves_done_status(self, runner):
        """Editing a task must not accidentally un-complete it."""
        d = _add(runner, "Task")
        # Manually mark done via storage to keep it in tasks.md for editing
        from todo.storage import find_task, update_task
        task = find_task(d["id"])
        task.done = True
        update_task(task)
        result = runner.invoke(
            cli, ["edit", d["id"], "Still done task", "--json"]
        )
        data = _unwrap(result.output)
        assert data["done"] is True

    def test_edit_set_due_relative_normalised(self, runner):
        """--set due:tomorrow should be stored as an ISO date, not the word."""
        d = _add(runner, "Relative due task")
        result = runner.invoke(cli, ["edit", d["id"], "--set", "due:tomorrow", "--json"])
        data = _unwrap(result.output)
        from datetime import date, timedelta
        assert data["due"] == (date.today() + timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# Phase 2 — due date normalisation on add
# ---------------------------------------------------------------------------

class TestDueDateNormalisation:
    def test_add_tomorrow_stored_as_iso(self, runner):
        from datetime import date, timedelta
        data = _add(runner, "Task due:tomorrow")
        assert data["due"] == (date.today() + timedelta(days=1)).isoformat()

    def test_add_iso_date_unchanged(self, runner):
        data = _add(runner, "Task due:2026-08-01")
        assert data["due"] == "2026-08-01"

    def test_add_relative_interval(self, runner):
        from datetime import date, timedelta
        data = _add(runner, "Task due:in-7-days")
        assert data["due"] == (date.today() + timedelta(days=7)).isoformat()


# ---------------------------------------------------------------------------
# Phase 2 — recurrence
# ---------------------------------------------------------------------------

class TestRecurrence:
    def test_done_non_recurring_spawns_nothing(self, runner):
        d = _add(runner, "One-off task")
        result = runner.invoke(cli, ["done", d["id"], "--json"])
        data = _unwrap(result.output)
        assert data[0]["spawned"] is None
        assert len(read_tasks()) == 0

    def test_done_daily_spawns_next(self, runner):
        d = _add(runner, "Stand-up @work due:2026-04-13 recur:daily")
        runner.invoke(cli, ["done", d["id"]])
        tasks = read_tasks()
        assert len(tasks) == 1
        assert tasks[0].due == "2026-04-14"
        assert tasks[0].recur == "daily"
        assert tasks[0].id != d["id"]

    def test_done_weekly_correct_date(self, runner):
        d = _add(runner, "Weekly review due:2026-04-13 recur:weekly")
        runner.invoke(cli, ["done", d["id"]])
        tasks = read_tasks()
        assert tasks[0].due == "2026-04-20"

    def test_done_monthly_correct_date(self, runner):
        d = _add(runner, "Monthly report due:2026-04-13 recur:monthly")
        runner.invoke(cli, ["done", d["id"]])
        tasks = read_tasks()
        assert tasks[0].due == "2026-05-13"

    def test_done_recurring_json_has_spawned(self, runner):
        d = _add(runner, "Daily task due:2026-04-13 recur:daily")
        result = runner.invoke(cli, ["done", d["id"], "--json"])
        data = _unwrap(result.output)
        assert data[0]["spawned"] is not None
        assert data[0]["spawned"]["due"] == "2026-04-14"

    def test_spawned_task_clears_snooze(self, runner):
        from todo.storage import find_task, update_task
        d = _add(runner, "Weekly due:2026-04-13 recur:weekly")
        # Manually set a snooze before completing
        task = find_task(d["id"])
        task.snooze = "2099-01-01T00:00"
        update_task(task)
        runner.invoke(cli, ["done", d["id"]])
        tasks = read_tasks()
        assert tasks[0].snooze is None

    def test_recurring_task_preserved_in_archive(self, runner):
        d = _add(runner, "Weekly due:2026-04-13 recur:weekly")
        runner.invoke(cli, ["done", d["id"]])
        content = _archive_file().read_text()
        assert d["id"] in content


# ---------------------------------------------------------------------------
# Phase 2 — snooze command
# ---------------------------------------------------------------------------

class TestSnoozeCommand:
    def test_snooze_sets_field(self, runner):
        from todo.storage import find_task
        d = _add(runner, "Snoozable task")
        result = runner.invoke(cli, ["snooze", d["id"], "2099-12-31T23:59", "--json"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["snooze"] == "2099-12-31T23:59"

    def test_snoozed_task_hidden_from_list(self, runner):
        d = _add(runner, "Hidden task")
        runner.invoke(cli, ["snooze", d["id"], "2099-12-31T23:59"])
        result = runner.invoke(cli, ["list", "--json"])
        data = _unwrap(result.output)
        assert not any(t["id"] == d["id"] for t in data)

    def test_snoozed_task_visible_with_all_flag(self, runner):
        d = _add(runner, "Snoozed task")
        runner.invoke(cli, ["snooze", d["id"], "2099-12-31T23:59"])
        result = runner.invoke(cli, ["list", "--all", "--json"])
        data = _unwrap(result.output)
        assert any(t["id"] == d["id"] for t in data)

    def test_past_snooze_visible_in_list(self, runner):
        from todo.storage import find_task, update_task
        d = _add(runner, "Past snooze task")
        task = find_task(d["id"])
        task.snooze = "2020-01-01T00:00"  # already past
        update_task(task)
        result = runner.invoke(cli, ["list", "--json"])
        data = _unwrap(result.output)
        assert any(t["id"] == d["id"] for t in data)

    def test_snooze_clear_removes_field(self, runner):
        d = _add(runner, "Task to unsnooze")
        runner.invoke(cli, ["snooze", d["id"], "2099-12-31T23:59"])
        result = runner.invoke(cli, ["snooze", d["id"], "--clear", "--json"])
        data = _unwrap(result.output)
        assert data["snooze"] is None

    def test_snooze_nonexistent_exits_1(self, runner):
        result = runner.invoke(cli, ["snooze", "notreal1", "1h"])
        assert result.exit_code == 1

    def test_snooze_no_duration_no_clear_exits_2(self, runner):
        d = _add(runner, "Task")
        result = runner.invoke(cli, ["snooze", d["id"]])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Phase 2 — recap command
# ---------------------------------------------------------------------------

class TestRecap:
    def test_recap_json_keys(self, runner):
        result = runner.invoke(cli, ["recap", "--json"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert "overdue" in data
        assert "today" in data

    def test_recap_week_json_keys(self, runner):
        result = runner.invoke(cli, ["recap", "--week", "--json"])
        data = _unwrap(result.output)
        assert "overdue" in data
        assert "upcoming" in data
        assert "no_due_date" in data

    def test_recap_shows_overdue(self, runner):
        _add(runner, "Old task due:2020-01-01")
        _add(runner, "Future task due:2099-12-31")
        result = runner.invoke(cli, ["recap", "--json"])
        data = _unwrap(result.output)
        assert len(data["overdue"]) == 1
        assert data["overdue"][0]["due"] == "2020-01-01"

    def test_recap_shows_today(self, runner):
        from datetime import date
        today = date.today().isoformat()
        _add(runner, f"Today task due:{today}")
        _add(runner, "Future task due:2099-12-31")
        result = runner.invoke(cli, ["recap", "--json"])
        data = _unwrap(result.output)
        assert len(data["today"]) == 1
        assert data["today"][0]["due"] == today

    def test_recap_week_upcoming(self, runner):
        from datetime import date, timedelta
        in_3 = (date.today() + timedelta(days=3)).isoformat()
        _add(runner, f"Soon task due:{in_3}")
        _add(runner, "Far future task due:2099-12-31")
        result = runner.invoke(cli, ["recap", "--week", "--json"])
        data = _unwrap(result.output)
        assert any(t["due"] == in_3 for t in data["upcoming"])
        assert not any(t["due"] == "2099-12-31" for t in data["upcoming"])

    def test_recap_excludes_snoozed(self, runner):
        from datetime import date
        from todo.storage import find_task, update_task
        today = date.today().isoformat()
        d = _add(runner, f"Snoozed today task due:{today}")
        task = find_task(d["id"])
        task.snooze = "2099-01-01T00:00"
        update_task(task)
        result = runner.invoke(cli, ["recap", "--json"])
        data = _unwrap(result.output)
        assert not any(t["id"] == d["id"] for t in data["today"])

    def test_recap_text_output(self, runner):
        result = runner.invoke(cli, ["recap"])
        assert result.exit_code == 0
        assert "OVERDUE" in result.output
        assert "TODAY" in result.output


# ---------------------------------------------------------------------------
# Phase 3 — --natural flag on add
# ---------------------------------------------------------------------------

class TestNaturalLanguageAdd:
    """
    These tests mock todo.nlp._search_dates so date extraction is deterministic
    regardless of what dateparser version is installed or today's date.
    """

    def test_natural_flag_sets_title(self, runner):
        from unittest.mock import patch
        with patch("todo.nlp._search_dates", return_value=[]):
            result = runner.invoke(cli, ["add", "--natural", "buy some milk"])
        assert result.exit_code == 0
        tasks = read_tasks()
        assert tasks[0].title == "Buy some milk"

    def test_natural_strips_filler_from_title(self, runner):
        from unittest.mock import patch
        with patch("todo.nlp._search_dates", return_value=[]):
            result = runner.invoke(cli, ["add", "-n", "remind me to call Alice", "--json"])
        data = _unwrap(result.output)
        assert data["title"] == "Call Alice"

    def test_natural_infers_priority(self, runner):
        from unittest.mock import patch
        with patch("todo.nlp._search_dates", return_value=[]):
            result = runner.invoke(
                cli, ["add", "-n", "urgent: fix the server", "--json"]
            )
        data = _unwrap(result.output)
        assert data["priority"] == 1
        assert data["title"] == "Fix the server"

    def test_natural_infers_tags(self, runner):
        from unittest.mock import patch
        with patch("todo.nlp._search_dates", return_value=[]):
            result = runner.invoke(
                cli, ["add", "-n", "dentist appointment on Thursday", "--json"]
            )
        data = _unwrap(result.output)
        assert "health" in data["tags"]

    def test_natural_extracts_date(self, runner):
        from unittest.mock import patch
        from datetime import datetime
        mock_dt = datetime(2026, 4, 17, 0, 0)
        with patch("todo.nlp._search_dates", return_value=[("next Friday", mock_dt)]):
            result = runner.invoke(
                cli, ["add", "-n", "call Alice next Friday", "--json"]
            )
        data = _unwrap(result.output)
        assert data["due"] == "2026-04-17"
        assert "Friday" not in data["title"]

    def test_natural_extracts_datetime(self, runner):
        from unittest.mock import patch
        from datetime import datetime
        mock_dt = datetime(2026, 4, 17, 15, 0)
        with patch("todo.nlp._search_dates", return_value=[("next Friday at 3pm", mock_dt)]):
            result = runner.invoke(
                cli, ["add", "-n", "call Alice next Friday at 3pm", "--json"]
            )
        data = _unwrap(result.output)
        assert data["due"] == "2026-04-17T15:00"

    def test_natural_persists_to_disk(self, runner):
        from unittest.mock import patch
        with patch("todo.nlp._search_dates", return_value=[]):
            runner.invoke(cli, ["add", "-n", "buy some milk"])
        assert len(read_tasks()) == 1

    def test_dry_run_does_not_save(self, runner):
        from unittest.mock import patch
        with patch("todo.nlp._search_dates", return_value=[]):
            result = runner.invoke(
                cli, ["add", "-n", "buy groceries", "--dry-run"]
            )
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["action"] == "add"
        assert data["after"]["title"] == "Buy groceries"
        assert read_tasks() == []   # nothing saved

    def test_dry_run_mini_syntax(self, runner):
        """--dry-run also works without --natural."""
        result = runner.invoke(
            cli, ["add", "Review docs @work priority:2", "--dry-run"]
        )
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["action"] == "add"
        assert data["after"]["title"] == "Review docs"
        assert data["after"]["priority"] == 2
        assert read_tasks() == []

    def test_natural_json_output(self, runner):
        from unittest.mock import patch
        with patch("todo.nlp._search_dates", return_value=[]):
            result = runner.invoke(
                cli, ["add", "-n", "write the report", "--json"]
            )
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert "id" in data
        assert data["title"] == "Write the report"


# ---------------------------------------------------------------------------
# Phase 3 — triage command
# ---------------------------------------------------------------------------

class TestTriage:
    def _add_untriaged(self, runner, title="Untriaged task"):
        """Add a task with no due date and default priority (needs triage)."""
        return _add(runner, title)

    def _add_triaged(self, runner, title="Triaged task"):
        """Add a task that already has priority set (does not need triage)."""
        return _add(runner, f"{title} priority:1")

    # --- non-interactive / JSON ---------------------------------------------

    def test_json_returns_only_untriaged(self, runner):
        self._add_untriaged(runner, "Needs triage")
        self._add_triaged(runner, "Already done")
        result = runner.invoke(cli, ["triage", "--json"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert len(data) == 1
        assert data[0]["title"] == "Needs triage"

    def test_json_empty_when_all_triaged(self, runner):
        self._add_triaged(runner, "Already prioritised")
        result = runner.invoke(cli, ["triage", "--json"])
        data = _unwrap(result.output)
        assert data == []

    def test_json_excludes_snoozed(self, runner):
        from todo.storage import find_task, update_task
        d = self._add_untriaged(runner, "Snoozed task")
        task = find_task(d["id"])
        task.snooze = "2099-01-01T00:00"
        update_task(task)
        result = runner.invoke(cli, ["triage", "--json"])
        data = _unwrap(result.output)
        assert not any(t["id"] == d["id"] for t in data)

    def test_json_excludes_done_tasks(self, runner):
        d = self._add_untriaged(runner, "Completed task")
        runner.invoke(cli, ["done", d["id"]])
        result = runner.invoke(cli, ["triage", "--json"])
        data = _unwrap(result.output)
        assert data == []

    def test_task_with_due_excluded(self, runner):
        """A task with a due date but no priority is not considered untriaged."""
        _add(runner, "Has due but no priority due:2026-09-01")
        result = runner.invoke(cli, ["triage", "--json"])
        data = _unwrap(result.output)
        # due is set, so it's not in the triage list
        assert data == []

    # --- interactive --------------------------------------------------------

    def test_interactive_skip_exits_cleanly(self, runner):
        self._add_untriaged(runner, "Task to skip")
        result = runner.invoke(cli, ["triage"], input="s\n")
        assert result.exit_code == 0
        assert "Triage complete" in result.output

    def test_interactive_quit_exits_early(self, runner):
        self._add_untriaged(runner, "Task A")
        self._add_untriaged(runner, "Task B")
        result = runner.invoke(cli, ["triage"], input="q\n")
        assert result.exit_code == 0
        assert "Triage stopped" in result.output

    def test_interactive_no_tasks_exits_cleanly(self, runner):
        result = runner.invoke(cli, ["triage"])
        assert result.exit_code == 0
        assert "No tasks need triage" in result.output

    def test_interactive_set_due(self, runner):
        self._add_untriaged(runner, "Task needing due date")
        # d → action, 2026-05-01 → date value, s → skip (move on)
        result = runner.invoke(cli, ["triage"], input="d\n2026-05-01\ns\n")
        assert result.exit_code == 0
        tasks = read_tasks()
        assert tasks[0].due == "2026-05-01"

    def test_interactive_set_due_relative(self, runner):
        from datetime import date, timedelta
        self._add_untriaged(runner, "Relative due task")
        runner.invoke(cli, ["triage"], input="d\ntomorrow\ns\n")
        tasks = read_tasks()
        assert tasks[0].due == (date.today() + timedelta(days=1)).isoformat()

    def test_interactive_set_priority(self, runner):
        self._add_untriaged(runner, "Task needing priority")
        result = runner.invoke(cli, ["triage"], input="p\n1\ns\n")
        assert result.exit_code == 0
        tasks = read_tasks()
        assert tasks[0].priority == 1

    def test_interactive_set_tag(self, runner):
        self._add_untriaged(runner, "Task needing tag")
        result = runner.invoke(cli, ["triage"], input="t\nwork health\ns\n")
        assert result.exit_code == 0
        tasks = read_tasks()
        assert "work" in tasks[0].tags
        assert "health" in tasks[0].tags

    def test_interactive_unknown_action_loops(self, runner):
        """An unrecognised character should print an error and re-prompt."""
        self._add_untriaged(runner, "Task")
        result = runner.invoke(cli, ["triage"], input="x\ns\n")
        assert result.exit_code == 0
        assert "Unknown action" in result.output

    def test_interactive_multiple_actions_same_task(self, runner):
        """Set both due and priority before moving on."""
        self._add_untriaged(runner, "Multi-action task")
        runner.invoke(cli, ["triage"], input="d\n2026-06-01\np\n2\ns\n")
        tasks = read_tasks()
        assert tasks[0].due == "2026-06-01"
        assert tasks[0].priority == 2

    def test_interactive_shows_task_count(self, runner):
        self._add_untriaged(runner, "Task 1")
        self._add_untriaged(runner, "Task 2")
        result = runner.invoke(cli, ["triage"], input="s\ns\n")
        assert "2 task(s)" in result.output
