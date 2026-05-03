"""
Tests for structured dry-run diffs on `add` and `edit`.

Shape returned by --dry-run (no --dedup):
{
  "schema_version": 1,
  "data": {
    "dry_run": True,
    "action": "add" | "edit",
    "before": null | {...task dict...},
    "after": {...task dict with metadata...},
    "changes": [{"field": ..., "before": ..., "after": ..., "inferred_from"?: ..., "reason"?: ...}],
    "warnings": [...],
    "ambiguities": [...]
  }
}
"""

import json
import pytest
from unittest.mock import patch
from click.testing import CliRunner
from todo.cli import cli, SCHEMA_VERSION
from todo.storage import add_task, read_tasks
from todo.models import Task


@pytest.fixture(autouse=True)
def isolated_todo_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TODO_DIR", str(tmp_path))


@pytest.fixture
def runner():
    return CliRunner()


def _unwrap(output: str) -> dict:
    response = json.loads(output)
    assert response["schema_version"] == SCHEMA_VERSION
    return response["data"]


def _add(runner, task_string, extra_args=()):
    args = ["add", task_string, "--json"] + list(extra_args)
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    return _unwrap(result.output)


def _dry_add(runner, task_string, extra_args=()):
    args = ["add", task_string, "--dry-run"] + list(extra_args)
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    return _unwrap(result.output)


def _dry_edit(runner, task_id, *args):
    result = runner.invoke(cli, ["edit", task_id, "--dry-run"] + list(args))
    assert result.exit_code == 0, result.output
    return _unwrap(result.output)


def _field(changes, name):
    """Return the change entry for a given field, or None."""
    return next((c for c in changes if c["field"] == name), None)


# ---------------------------------------------------------------------------
# Envelope and top-level shape
# ---------------------------------------------------------------------------

class TestDryRunEnvelope:
    def test_action_is_add(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert data["action"] == "add"

    def test_dry_run_flag_true(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert data["dry_run"] is True

    def test_before_is_null_for_add(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert data["before"] is None

    def test_after_is_complete_task_dict(self, runner):
        data = _dry_add(runner, "Buy milk")
        after = data["after"]
        for key in ("id", "title", "done", "tags", "due", "priority",
                    "section", "source", "edited_at"):
            assert key in after, f"missing key: {key}"

    def test_changes_is_list(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert isinstance(data["changes"], list)

    def test_warnings_is_list(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert isinstance(data["warnings"], list)

    def test_ambiguities_is_list(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert isinstance(data["ambiguities"], list)

    def test_does_not_save(self, runner):
        _dry_add(runner, "Buy milk")
        assert read_tasks() == []


# ---------------------------------------------------------------------------
# add --dry-run: changes list
# ---------------------------------------------------------------------------

class TestAddDryRunChanges:
    def test_title_always_in_changes(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert _field(data["changes"], "title") is not None

    def test_title_before_is_null(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert _field(data["changes"], "title")["before"] is None

    def test_title_after_matches_after_dict(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert _field(data["changes"], "title")["after"] == data["after"]["title"]

    def test_section_always_in_changes(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert _field(data["changes"], "section") is not None

    def test_section_has_reason_when_inferred(self, runner):
        data = _dry_add(runner, "Buy milk")
        s = _field(data["changes"], "section")
        assert "reason" in s

    def test_section_no_due_reason(self, runner):
        data = _dry_add(runner, "Buy milk")
        s = _field(data["changes"], "section")
        assert "no due date" in s["reason"]

    def test_section_future_due_reason(self, runner):
        data = _dry_add(runner, "Buy milk due:2099-12-31")
        s = _field(data["changes"], "section")
        assert "future" in s["reason"]

    def test_section_explicit_flag_reason(self, runner):
        data = _dry_add(runner, "Buy milk", extra_args=["--section", "someday"])
        s = _field(data["changes"], "section")
        assert "explicit" in s["reason"]
        assert "inferred_from" not in s

    def test_due_in_changes_when_set(self, runner):
        data = _dry_add(runner, "Buy milk due:2099-12-31")
        assert _field(data["changes"], "due") is not None

    def test_due_not_in_changes_when_absent(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert _field(data["changes"], "due") is None

    def test_due_inferred_from_relative(self, runner):
        data = _dry_add(runner, "Buy milk due:tomorrow")
        d = _field(data["changes"], "due")
        assert d is not None
        assert d["inferred_from"] == "tomorrow"

    def test_due_no_inferred_from_when_iso(self, runner):
        data = _dry_add(runner, "Buy milk due:2099-12-31")
        d = _field(data["changes"], "due")
        assert "inferred_from" not in d

    def test_priority_in_changes_when_not_default(self, runner):
        data = _dry_add(runner, "Buy milk priority:1")
        assert _field(data["changes"], "priority") is not None

    def test_priority_not_in_changes_when_default(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert _field(data["changes"], "priority") is None

    def test_tags_in_changes_when_set(self, runner):
        data = _dry_add(runner, "Buy milk @shopping")
        assert _field(data["changes"], "tags") is not None

    def test_tags_not_in_changes_when_absent(self, runner):
        data = _dry_add(runner, "Buy milk")
        assert _field(data["changes"], "tags") is None

    def test_recur_in_changes_when_set(self, runner):
        data = _dry_add(runner, "Standup due:2099-01-01 recur:daily")
        assert _field(data["changes"], "recur") is not None

    def test_notify_in_changes_when_set(self, runner):
        data = _dry_add(runner, "Task notify:1h")
        assert _field(data["changes"], "notify") is not None

    def test_idempotency_key_in_changes_when_set(self, runner):
        data = _dry_add(runner, "Task", extra_args=["--idempotency-key", "key-001"])
        assert _field(data["changes"], "idempotency_key") is not None

    def test_source_not_in_changes_when_manual(self, runner):
        data = _dry_add(runner, "Task")
        assert _field(data["changes"], "source") is None

    def test_source_in_changes_when_explicit(self, runner):
        data = _dry_add(runner, "Task", extra_args=["--source", "slack"])
        assert _field(data["changes"], "source") is not None


# ---------------------------------------------------------------------------
# add --dry-run: NLP mode
# ---------------------------------------------------------------------------

class TestAddDryRunNlp:
    def test_nlp_title_inferred_from_raw_input(self, runner):
        with patch("todo.nlp._search_dates", return_value=[]):
            data = _dry_add(runner, "remind me to buy groceries", extra_args=["-n"])
        t = _field(data["changes"], "title")
        assert t is not None
        assert t["inferred_from"] == "remind me to buy groceries"

    def test_nlp_due_inferred_from_phrase(self, runner):
        from datetime import datetime
        fake_dt = datetime(2099, 12, 31)
        with patch("todo.nlp._search_dates", return_value=[("next year", fake_dt)]):
            data = _dry_add(runner, "do something next year", extra_args=["-n"])
        d = _field(data["changes"], "due")
        assert d is not None
        assert d["inferred_from"] == "next year"

    def test_nlp_priority_inferred_from_keyword(self, runner):
        with patch("todo.nlp._search_dates", return_value=[]):
            data = _dry_add(runner, "urgent fix the bug", extra_args=["-n"])
        p = _field(data["changes"], "priority")
        assert p is not None
        assert p["inferred_from"] is not None
        assert "urgent" in p["inferred_from"]

    def test_nlp_ambiguity_when_multiple_dates(self, runner):
        from datetime import datetime
        dt1 = datetime(2099, 5, 1)
        dt2 = datetime(2099, 6, 1)
        with patch("todo.nlp._search_dates", return_value=[("May", dt1), ("June", dt2)]):
            data = _dry_add(runner, "do it in May or June", extra_args=["-n"])
        assert len(data["ambiguities"]) >= 1
        assert "2" in data["ambiguities"][0]

    def test_nlp_no_ambiguity_when_single_date(self, runner):
        from datetime import datetime
        with patch("todo.nlp._search_dates", return_value=[("Friday", datetime(2099, 5, 3))]):
            data = _dry_add(runner, "do it Friday", extra_args=["-n"])
        assert data["ambiguities"] == []


# ---------------------------------------------------------------------------
# add --dry-run: warnings
# ---------------------------------------------------------------------------

class TestAddDryRunWarnings:
    def test_past_due_triggers_warning(self, runner):
        data = _dry_add(runner, "Late task due:2020-01-01")
        assert any("past" in w for w in data["warnings"])

    def test_future_due_no_warning(self, runner):
        data = _dry_add(runner, "Future task due:2099-12-31")
        assert not any("past" in w for w in data["warnings"])

    def test_unrecognized_field_triggers_warning(self, runner):
        data = _dry_add(runner, "Task deadline:tomorrow")
        assert any("deadline:tomorrow" in w for w in data["warnings"])

    def test_known_field_does_not_trigger_warning(self, runner):
        data = _dry_add(runner, "Task due:tomorrow")
        assert not any("due:tomorrow" in w for w in data["warnings"])


# ---------------------------------------------------------------------------
# edit --dry-run: shape and changes
# ---------------------------------------------------------------------------

class TestEditDryRunShape:
    def test_action_is_edit(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "priority:1")
        assert data["action"] == "edit"

    def test_dry_run_flag_true(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "priority:1")
        assert data["dry_run"] is True

    def test_before_contains_original_task(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "priority:1")
        assert data["before"]["title"] == "Original"
        assert data["before"]["id"] == d["id"]

    def test_after_contains_updated_task(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "priority:1")
        assert data["after"]["priority"] == 1

    def test_does_not_save(self, runner):
        d = _add(runner, "Original")
        _dry_edit(runner, d["id"], "--set", "priority:1")
        assert read_tasks()[0].priority == 4

    def test_changes_only_lists_changed_fields(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "priority:1")
        fields = [c["field"] for c in data["changes"]]
        assert "priority" in fields
        assert "title" not in fields

    def test_change_shows_before_and_after(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "priority:1")
        p = _field(data["changes"], "priority")
        assert p["before"] == 4
        assert p["after"] == 1

    def test_title_change_via_task_string(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "New title")
        t = _field(data["changes"], "title")
        assert t is not None
        assert t["before"] == "Original"
        assert t["after"] == "New title"

    def test_due_change_inferred_from_relative(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "due:2099-12-31")
        due = _field(data["changes"], "due")
        assert due is not None
        # ISO date is canonical — no inferred_from
        assert "inferred_from" not in due

    def test_due_change_inferred_from_tomorrow(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "due:tomorrow")
        due = _field(data["changes"], "due")
        assert due is not None
        assert due["inferred_from"] == "tomorrow"

    def test_no_changes_when_nothing_differs(self, runner):
        d = _add(runner, "Original priority:2")
        data = _dry_edit(runner, d["id"], "--set", "priority:2")
        assert data["changes"] == []

    def test_multiple_set_changes_all_listed(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "priority:1", "--set", "title:New")
        fields = [c["field"] for c in data["changes"]]
        assert "priority" in fields
        assert "title" in fields


# ---------------------------------------------------------------------------
# edit --dry-run: warnings
# ---------------------------------------------------------------------------

class TestEditDryRunWarnings:
    def test_past_due_triggers_warning(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "due:2020-01-01")
        assert any("past" in w for w in data["warnings"])

    def test_no_warning_for_future_due(self, runner):
        d = _add(runner, "Original")
        data = _dry_edit(runner, d["id"], "--set", "due:2099-12-31")
        assert data["warnings"] == []
