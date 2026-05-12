"""Tests for mdone doctor — validation and repair."""

import json
import pytest
from click.testing import CliRunner

from todo.cli import cli, SCHEMA_VERSION
from todo.models import Task
from todo.storage import _tasks_file, write_tasks, read_tasks
from todo.metadata import create_task_meta, read_all_meta


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


def _add(runner, task_string, **flags):
    args = ["add", task_string, "--json"]
    for k, v in flags.items():
        args += [f"--{k}", v]
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    return _unwrap(result.output)


# ---------------------------------------------------------------------------
# Helpers to inject malformed data directly into tasks.md
# ---------------------------------------------------------------------------

def _write_raw_task(title, task_id, extra_fields="", section="inbox"):
    """Write a raw task line under the given section header."""
    content = (
        f"## {section.capitalize()}\n"
        f"- [ ] {title} {extra_fields} id:{task_id}\n"
        "\n## Today\n\n## Upcoming\n\n## Someday\n\n## Waiting\n"
    )
    _tasks_file().write_text(content)


# ---------------------------------------------------------------------------
# Clean file
# ---------------------------------------------------------------------------

class TestDoctorClean:
    def test_clean_file_exits_0(self, runner):
        _add(runner, "Normal task")
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0

    def test_clean_file_no_issues_json(self, runner):
        _add(runner, "Normal task")
        result = runner.invoke(cli, ["doctor", "--json"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["issues"] == []
        assert data["summary"]["total"] == 0

    def test_clean_file_text_says_no_issues(self, runner):
        _add(runner, "Normal task")
        result = runner.invoke(cli, ["doctor"])
        assert "No issues" in result.output


# ---------------------------------------------------------------------------
# Malformed dates
# ---------------------------------------------------------------------------

class TestMalformedDates:
    def test_detects_bad_due_date(self, runner):
        _write_raw_task("Bad date task", "aaa00001", extra_fields="due:not-a-date")
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        types = [i["type"] for i in data["issues"]]
        assert "malformed_date" in types

    def test_normalizable_date_is_fixable(self, runner):
        _write_raw_task("Task", "aaa00001", extra_fields="due:tomorrow")
        # 'tomorrow' passes through parse_due_date fine — inject truly weird value
        # Use a value parse_due_date passes through unchanged but dateparser CAN handle
        content = _tasks_file().read_text()
        _tasks_file().write_text(
            content.replace("due:tomorrow", "due:April-15-2099")
        )
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        date_issues = [i for i in data["issues"] if i["type"] == "malformed_date"]
        assert len(date_issues) == 1
        assert date_issues[0]["fixable"] is True

    def test_unparseable_date_is_unfixable(self, runner):
        _write_raw_task("Bad task", "aaa00001", extra_fields="due:xyzzy99")
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        date_issues = [i for i in data["issues"] if i["type"] == "malformed_date"]
        assert len(date_issues) == 1
        assert date_issues[0]["fixable"] is False

    def test_unfixable_date_exits_2(self, runner):
        _write_raw_task("Bad task", "aaa00001", extra_fields="due:xyzzy99")
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 2

    def test_fix_normalizes_date(self, runner):
        _write_raw_task("Task", "aaa00001", extra_fields="due:2099-13-01")
        # Inject a parseable-but-wrong-format due date
        content = _tasks_file().read_text()
        _tasks_file().write_text(content.replace("due:2099-13-01", "due:April-15-2099"))
        runner.invoke(cli, ["doctor", "--fix"])
        tasks = read_tasks()
        t = next(t for t in tasks if t.id == "aaa00001")
        # Should now be valid ISO
        import re
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", t.due)

    def test_dry_run_does_not_fix_date(self, runner):
        content = (
            "## Inbox\n- [ ] Task due:April-15-2099 id:aaa00001\n\n"
            "## Today\n\n## Upcoming\n\n## Someday\n\n## Waiting\n"
        )
        _tasks_file().write_text(content)
        runner.invoke(cli, ["doctor", "--dry-run"])
        tasks = read_tasks()
        t = next(t for t in tasks if t.id == "aaa00001")
        assert t.due == "April-15-2099"  # unchanged


# ---------------------------------------------------------------------------
# Malformed notify
# ---------------------------------------------------------------------------

class TestMalformedNotify:
    def test_detects_bad_notify(self, runner):
        _write_raw_task("Task", "aaa00001", extra_fields="notify:2hours")
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        types = [i["type"] for i in data["issues"]]
        assert "malformed_notify" in types

    def test_normalizable_notify_is_fixable(self, runner):
        _write_raw_task("Task", "aaa00001", extra_fields="notify:2hours")
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        notify_issues = [i for i in data["issues"] if i["type"] == "malformed_notify"]
        assert notify_issues[0]["fixable"] is True
        assert notify_issues[0]["after"] == "2h"

    def test_fix_normalizes_notify(self, runner):
        _write_raw_task("Task", "aaa00001", extra_fields="notify:30minutes")
        runner.invoke(cli, ["doctor", "--fix"])
        tasks = read_tasks()
        t = next(t for t in tasks if t.id == "aaa00001")
        assert t.notify == "30m"

    def test_unnormalizable_notify_is_removed(self, runner):
        _write_raw_task("Task", "aaa00001", extra_fields="notify:soon")
        runner.invoke(cli, ["doctor", "--fix"])
        tasks = read_tasks()
        t = next(t for t in tasks if t.id == "aaa00001")
        assert t.notify is None

    def test_valid_notify_not_flagged(self, runner):
        _write_raw_task("Task", "aaa00001", extra_fields="notify:2h")
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        notify_issues = [i for i in data["issues"] if i["type"] == "malformed_notify"]
        assert notify_issues == []


# ---------------------------------------------------------------------------
# Duplicate IDs
# ---------------------------------------------------------------------------

class TestDuplicateIds:
    def test_detects_duplicate_id(self, runner):
        content = (
            "## Inbox\n"
            "- [ ] First task id:dup00001\n"
            "- [ ] Second task id:dup00001\n"
            "\n## Today\n\n## Upcoming\n\n## Someday\n\n## Waiting\n"
        )
        _tasks_file().write_text(content)
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        dup_issues = [i for i in data["issues"] if i["type"] == "duplicate_id"]
        assert len(dup_issues) == 1
        assert dup_issues[0]["fixable"] is True

    def test_fix_reassigns_second_occurrence(self, runner):
        content = (
            "## Inbox\n"
            "- [ ] First task id:dup00001\n"
            "- [ ] Second task id:dup00001\n"
            "\n## Today\n\n## Upcoming\n\n## Someday\n\n## Waiting\n"
        )
        _tasks_file().write_text(content)
        runner.invoke(cli, ["doctor", "--fix"])
        tasks = read_tasks()
        ids = [t.id for t in tasks]
        assert len(ids) == len(set(ids)), "IDs should all be unique after fix"
        # First task keeps original ID
        assert tasks[0].id == "dup00001"
        # Second task has a new ID
        assert tasks[1].id != "dup00001"

    def test_duplicate_exits_1_before_fix(self, runner):
        content = (
            "## Inbox\n"
            "- [ ] First task id:dup00001\n"
            "- [ ] Second task id:dup00001\n"
            "\n## Today\n\n## Upcoming\n\n## Someday\n\n## Waiting\n"
        )
        _tasks_file().write_text(content)
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 1

    def test_duplicate_exits_0_after_fix(self, runner):
        content = (
            "## Inbox\n"
            "- [ ] First task id:dup00001\n"
            "- [ ] Second task id:dup00001\n"
            "\n## Today\n\n## Upcoming\n\n## Someday\n\n## Waiting\n"
        )
        _tasks_file().write_text(content)
        result = runner.invoke(cli, ["doctor", "--fix"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Invalid priorities
# ---------------------------------------------------------------------------

class TestInvalidPriority:
    def test_detects_invalid_priority(self, runner):
        t = Task(title="Bad priority", id="bbb00001", priority=9)
        write_tasks([t])
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        pri_issues = [i for i in data["issues"] if i["type"] == "invalid_priority"]
        assert len(pri_issues) == 1
        assert pri_issues[0]["after"] == 4

    def test_fix_resets_priority_to_4(self, runner):
        t = Task(title="Bad priority", id="bbb00001", priority=9)
        write_tasks([t])
        runner.invoke(cli, ["doctor", "--fix"])
        tasks = read_tasks()
        assert tasks[0].priority == 4

    def test_valid_priorities_not_flagged(self, runner):
        for p in (1, 2, 3, 4):
            write_tasks([Task(title=f"P{p} task", id=f"ppp0000{p}", priority=p)])
            result = runner.invoke(cli, ["doctor", "--json"])
            data = _unwrap(result.output)
            pri_issues = [i for i in data["issues"] if i["type"] == "invalid_priority"]
            assert pri_issues == [], f"Priority {p} should be valid"


# ---------------------------------------------------------------------------
# Structural orphans
# ---------------------------------------------------------------------------

class TestStructuralOrphans:
    def test_detects_task_before_header(self, runner):
        _tasks_file().parent.mkdir(parents=True, exist_ok=True)
        _tasks_file().write_text(
            "- [ ] Orphan task id:zzz00001\n\n"
            "## Inbox\n\n## Today\n\n## Upcoming\n\n## Someday\n\n## Waiting\n"
        )
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        orphan_issues = [i for i in data["issues"] if i["type"] == "structural_orphan"]
        assert len(orphan_issues) == 1
        assert orphan_issues[0]["task_id"] == "zzz00001"
        assert orphan_issues[0]["fixable"] is True

    def test_fix_moves_orphan_to_inbox(self, runner):
        _tasks_file().parent.mkdir(parents=True, exist_ok=True)
        _tasks_file().write_text(
            "- [ ] Orphan task id:zzz00001\n\n"
            "## Inbox\n\n## Today\n\n## Upcoming\n\n## Someday\n\n## Waiting\n"
        )
        runner.invoke(cli, ["doctor", "--fix"])
        # Read back: should no longer appear before any header
        content = _tasks_file().read_text()
        inbox_pos = content.index("## Inbox")
        task_pos = content.index("zzz00001")
        assert task_pos > inbox_pos


# ---------------------------------------------------------------------------
# Invalid recurrence
# ---------------------------------------------------------------------------

class TestInvalidRecurrence:
    def test_detects_bad_recurrence(self, runner):
        t = Task(title="Bad recur", id="ccc00001", recur="fortnightly")
        write_tasks([t])
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        recur_issues = [i for i in data["issues"] if i["type"] == "invalid_recurrence"]
        assert len(recur_issues) == 1
        assert recur_issues[0]["fixable"] is True

    def test_fix_removes_bad_recurrence(self, runner):
        t = Task(title="Bad recur", id="ccc00001", recur="fortnightly")
        write_tasks([t])
        runner.invoke(cli, ["doctor", "--fix"])
        tasks = read_tasks()
        assert tasks[0].recur is None

    def test_valid_recurrences_not_flagged(self, runner):
        for recur in ("daily", "weekly", "monthly"):
            write_tasks([Task(title="R task", id="rrr00001", recur=recur)])
            result = runner.invoke(cli, ["doctor", "--json"])
            data = _unwrap(result.output)
            recur_issues = [i for i in data["issues"] if i["type"] == "invalid_recurrence"]
            assert recur_issues == [], f"recur:{recur} should be valid"


# ---------------------------------------------------------------------------
# Orphaned metadata
# ---------------------------------------------------------------------------

class TestOrphanedMetadata:
    def test_detects_orphaned_metadata(self, runner):
        # Create metadata for a non-existent task
        create_task_meta("ghost001", {"source": "manual"})
        _add(runner, "Real task")
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        orphan_meta = [i for i in data["issues"] if i["type"] == "orphaned_metadata"]
        assert any(i["task_id"] == "ghost001" for i in orphan_meta)

    def test_fix_removes_orphaned_metadata(self, runner):
        create_task_meta("ghost001", {"source": "manual"})
        _add(runner, "Real task")
        runner.invoke(cli, ["doctor", "--fix"])
        assert "ghost001" not in read_all_meta()

    def test_archived_task_metadata_not_orphaned(self, runner):
        data = _add(runner, "Task to complete")
        task_id = data["id"]
        runner.invoke(cli, ["done", task_id])
        result = runner.invoke(cli, ["doctor", "--json"])
        out = _unwrap(result.output)
        orphan_meta = [i for i in out["issues"] if i["type"] == "orphaned_metadata"]
        assert not any(i["task_id"] == task_id for i in orphan_meta)


# ---------------------------------------------------------------------------
# Single task ID filtering
# ---------------------------------------------------------------------------

class TestSingleTaskFilter:
    def test_checks_only_specified_task(self, runner):
        t1 = Task(title="Good task",  id="good0001", priority=2)
        t2 = Task(title="Bad task",   id="bad00002", priority=9)
        write_tasks([t1, t2])
        result = runner.invoke(cli, ["doctor", "good0001", "--json"])
        data = _unwrap(result.output)
        assert data["issues"] == []

    def test_finds_issue_in_specified_task(self, runner):
        t = Task(title="Bad priority", id="bad00001", priority=9)
        write_tasks([t])
        result = runner.invoke(cli, ["doctor", "bad00001", "--json"])
        data = _unwrap(result.output)
        assert len(data["issues"]) == 1

    def test_fixes_only_specified_task(self, runner):
        t1 = Task(title="Bad 1", id="bad00001", priority=9)
        t2 = Task(title="Bad 2", id="bad00002", priority=0)
        write_tasks([t1, t2])
        # After the write+read round-trip the parser regex (priority:[1-4]) leaves
        # out-of-range values as literal text in the title.  Doctor detects them
        # there and cleans the title on fix.  We verify only bad00001 was touched.
        runner.invoke(cli, ["doctor", "bad00001", "--fix"])
        tasks = {t.id: t for t in read_tasks()}
        assert tasks["bad00001"].priority == 4              # fixed
        assert "priority:9" not in tasks["bad00001"].title  # token cleaned
        assert "priority:0" in tasks["bad00002"].title      # untouched

    def test_unknown_task_id_exits_1(self, runner):
        _add(runner, "Some task")
        result = runner.invoke(cli, ["doctor", "nonexistent"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

class TestExitCodes:
    def test_exit_0_when_clean(self, runner):
        _add(runner, "Normal task")
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0

    def test_exit_1_when_fixable_issues(self, runner):
        t = Task(title="Bad priority", id="aaa00001", priority=9)
        write_tasks([t])
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 1

    def test_exit_2_when_unfixable_issues(self, runner):
        _write_raw_task("Task", "aaa00001", extra_fields="due:xyzzy99")
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 2

    def test_exit_0_after_successful_fix(self, runner):
        t = Task(title="Bad priority", id="aaa00001", priority=9)
        write_tasks([t])
        result = runner.invoke(cli, ["doctor", "--fix"])
        assert result.exit_code == 0

    def test_exit_2_after_fix_with_unfixable_remaining(self, runner):
        # Mix of fixable (bad priority) and unfixable (bad date)
        _write_raw_task("Task", "aaa00001",
                        extra_fields="priority:9 due:xyzzy99")
        result = runner.invoke(cli, ["doctor", "--fix"])
        assert result.exit_code == 2

    def test_dry_run_does_not_write(self, runner):
        t = Task(title="Bad priority", id="aaa00001", priority=9)
        write_tasks([t])
        # After the round-trip the parser leaves priority:9 in the title text.
        # Dry-run must not clean it.
        runner.invoke(cli, ["doctor", "--dry-run"])
        tasks = read_tasks()
        assert "priority:9" in tasks[0].title  # unchanged by dry-run


# ---------------------------------------------------------------------------
# JSON output shape
# ---------------------------------------------------------------------------

class TestJsonShape:
    def test_json_envelope_present(self, runner):
        _add(runner, "Normal task")
        result = runner.invoke(cli, ["doctor", "--json"])
        raw = json.loads(result.output)
        assert "schema_version" in raw
        assert "data" in raw

    def test_json_has_issues_and_summary(self, runner):
        _add(runner, "Normal task")
        result = runner.invoke(cli, ["doctor", "--json"])
        data = _unwrap(result.output)
        assert "issues" in data
        assert "summary" in data
        assert "total" in data["summary"]
        assert "fixable" in data["summary"]
        assert "unfixable" in data["summary"]
        assert "fixed" in data["summary"]

    def test_fix_json_has_fixed_and_unfixable(self, runner):
        t = Task(title="Bad priority", id="aaa00001", priority=9)
        write_tasks([t])
        result = runner.invoke(cli, ["doctor", "--fix", "--json"])
        data = _unwrap(result.output)
        assert "fixed" in data
        assert "unfixable" in data
        assert data["summary"]["fixed"] == 1

    def test_dry_run_json_fixed_is_zero(self, runner):
        t = Task(title="Bad priority", id="aaa00001", priority=9)
        write_tasks([t])
        result = runner.invoke(cli, ["doctor", "--dry-run", "--json"])
        data = _unwrap(result.output)
        assert data["dry_run"] is True
        assert data["summary"]["fixed"] == 0
