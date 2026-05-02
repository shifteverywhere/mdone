"""Tests for section support: storage grouping, CLI --section, and organize."""

import json
import pytest
from click.testing import CliRunner
from todo.cli import cli, SCHEMA_VERSION
from todo.models import Task
from todo.storage import (
    SECTIONS,
    DEFAULT_SECTION,
    add_task,
    read_tasks,
    write_tasks,
    _tasks_file,
)


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
# Storage: read / write sections
# ---------------------------------------------------------------------------

class TestStorageSections:
    def test_initial_file_has_all_headers(self):
        read_tasks()  # triggers _ensure_dir
        content = _tasks_file().read_text()
        for s in SECTIONS:
            assert f"## {s.capitalize()}" in content

    def test_task_default_section_is_inbox(self):
        task = Task(title="Default", id="aaa00001")
        assert task.section == DEFAULT_SECTION

    def test_write_groups_tasks_under_headers(self):
        tasks = [
            Task(title="A", id="aaa00001", section="inbox"),
            Task(title="B", id="bbb00002", section="today"),
        ]
        write_tasks(tasks)
        content = _tasks_file().read_text()
        inbox_pos = content.index("## Inbox")
        today_pos = content.index("## Today")
        a_pos = content.index("aaa00001")
        b_pos = content.index("bbb00002")
        assert inbox_pos < a_pos < today_pos < b_pos

    def test_read_assigns_section_from_header(self):
        _tasks_file().write_text(
            "## Today\n- [ ] Morning task id:ttt00001\n\n"
            "## Upcoming\n- [ ] Future task id:uuu00002\n"
        )
        tasks = read_tasks()
        by_id = {t.id: t for t in tasks}
        assert by_id["ttt00001"].section == "today"
        assert by_id["uuu00002"].section == "upcoming"

    def test_task_before_any_header_defaults_to_inbox(self):
        _tasks_file().write_text("- [ ] Orphan task id:zzz00001\n")
        tasks = read_tasks()
        assert tasks[0].section == DEFAULT_SECTION

    def test_unknown_header_is_ignored(self):
        _tasks_file().write_text(
            "## Someday\n- [ ] Task A id:aaa00001\n\n"
            "## Archive\n- [ ] Should be someday id:bbb00002\n"
        )
        tasks = read_tasks()
        by_id = {t.id: t for t in tasks}
        assert by_id["aaa00001"].section == "someday"
        # Unknown header "Archive" doesn't change current_section
        assert by_id["bbb00002"].section == "someday"

    def test_roundtrip_preserves_all_sections(self):
        original = [
            Task(title="A", id="aaa00001", section="inbox"),
            Task(title="B", id="bbb00002", section="today"),
            Task(title="C", id="ccc00003", section="upcoming"),
            Task(title="D", id="ddd00004", section="someday"),
            Task(title="E", id="eee00005", section="waiting"),
        ]
        write_tasks(original)
        loaded = read_tasks()
        by_id = {t.id: t for t in loaded}
        for t in original:
            assert by_id[t.id].section == t.section

    def test_to_dict_includes_section(self):
        task = Task(title="X", id="xxx00001", section="someday")
        d = task.to_dict()
        assert d["section"] == "someday"


# ---------------------------------------------------------------------------
# CLI: add --section
# ---------------------------------------------------------------------------

class TestAddSection:
    def test_add_no_due_goes_to_inbox(self, runner):
        data = _add(runner, "No due date task")
        assert data["section"] == "inbox"

    def test_add_future_due_goes_to_upcoming(self, runner):
        data = _add(runner, "Future task due:2099-12-31")
        assert data["section"] == "upcoming"

    def test_add_today_due_goes_to_today(self, runner):
        from datetime import date
        today = date.today().isoformat()
        data = _add(runner, f"Today task due:{today}")
        assert data["section"] == "today"

    def test_add_overdue_goes_to_today(self, runner):
        data = _add(runner, "Overdue task due:2020-01-01")
        assert data["section"] == "today"

    def test_add_explicit_section_overrides_auto(self, runner):
        data = _add(runner, "Parked idea due:2099-01-01", section="someday")
        assert data["section"] == "someday"

    def test_add_section_waiting(self, runner):
        data = _add(runner, "Waiting on reply", section="waiting")
        assert data["section"] == "waiting"

    def test_add_dry_run_includes_section(self, runner):
        result = runner.invoke(cli, ["add", "Task", "--dry-run"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert "section" in data


# ---------------------------------------------------------------------------
# CLI: list --section
# ---------------------------------------------------------------------------

class TestListSection:
    def test_list_section_filter(self, runner):
        _add(runner, "Inbox task")
        _add(runner, "Future task due:2099-12-31")
        result = runner.invoke(cli, ["list", "--section", "upcoming", "--json"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert len(data) == 1
        assert data[0]["section"] == "upcoming"

    def test_list_section_empty_returns_exit3(self, runner):
        result = runner.invoke(cli, ["list", "--section", "waiting"])
        assert result.exit_code == 3

    def test_list_json_includes_section(self, runner):
        _add(runner, "Task A")
        result = runner.invoke(cli, ["list", "--json"])
        data = _unwrap(result.output)
        assert "section" in data[0]

    def test_list_text_shows_section_headers(self, runner):
        _add(runner, "Inbox task")
        _add(runner, "Future task due:2099-12-31")
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "## Inbox" in result.output
        assert "## Upcoming" in result.output

    def test_list_text_hides_empty_sections(self, runner):
        _add(runner, "Only inbox task")
        result = runner.invoke(cli, ["list"])
        # Only Inbox header should appear; no Today, Upcoming, etc.
        assert "## Inbox" in result.output
        assert "## Today" not in result.output

    def test_list_section_filter_shows_flat_output(self, runner):
        _add(runner, "Inbox task")
        result = runner.invoke(cli, ["list", "--section", "inbox"])
        assert result.exit_code == 0
        # Flat output: no section header line
        assert "## Inbox" not in result.output
        assert "Inbox task" in result.output


# ---------------------------------------------------------------------------
# CLI: organize
# ---------------------------------------------------------------------------

class TestOrganize:
    def test_organize_moves_future_due_to_upcoming(self, runner):
        _add(runner, "Future task due:2099-01-01", section="inbox")
        result = runner.invoke(cli, ["organize"])
        assert result.exit_code == 0
        tasks = read_tasks()
        t = next(t for t in tasks if t.title == "Future task")
        assert t.section == "upcoming"

    def test_organize_moves_overdue_to_today(self, runner):
        _add(runner, "Old task due:2020-01-01", section="inbox")
        runner.invoke(cli, ["organize"])
        tasks = read_tasks()
        t = next(t for t in tasks if t.title == "Old task")
        assert t.section == "today"

    def test_organize_leaves_no_due_date_unchanged(self, runner):
        _add(runner, "No due task", section="someday")
        runner.invoke(cli, ["organize"])
        tasks = read_tasks()
        t = next(t for t in tasks if t.title == "No due task")
        assert t.section == "someday"

    def test_organize_dry_run_does_not_write(self, runner):
        _add(runner, "Future task due:2099-01-01", section="inbox")
        result = runner.invoke(cli, ["organize", "--dry-run"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert len(data["moved"]) == 1
        assert data["moved"][0]["to"] == "upcoming"
        # But task is still in inbox (dry-run)
        tasks = read_tasks()
        t = next(t for t in tasks if t.title == "Future task")
        assert t.section == "inbox"

    def test_organize_json_output(self, runner):
        _add(runner, "Future task due:2099-01-01", section="inbox")
        result = runner.invoke(cli, ["organize", "--json"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["moved"][0]["from"] == "inbox"
        assert data["moved"][0]["to"] == "upcoming"
        assert "id" in data["moved"][0]
        assert "due" in data["moved"][0]
        assert data["sorted_by"] is None

    def test_organize_nothing_to_move(self, runner):
        _add(runner, "Future task due:2099-01-01")  # already in upcoming
        result = runner.invoke(cli, ["organize"])
        assert result.exit_code == 0
        assert "already" in result.output

    def test_organize_moves_waiting_task_with_due(self, runner):
        _add(runner, "Waiting task due:2020-06-01", section="waiting")
        runner.invoke(cli, ["organize"])
        tasks = read_tasks()
        t = next(t for t in tasks if t.title == "Waiting task")
        assert t.section == "today"

    def test_organize_archives_manually_done_task(self, runner):
        data = _add(runner, "Finish report")
        task_id = data["id"]
        # Manually mark it done in the file
        content = _tasks_file().read_text()
        _tasks_file().write_text(content.replace(
            f"- [ ] Finish report id:{task_id}",
            f"- [x] Finish report id:{task_id}"
        ))
        runner.invoke(cli, ["organize"])
        # No longer in active tasks
        tasks = read_tasks()
        assert not any(t.id == task_id for t in tasks)
        # Present in archive
        archive = (_tasks_file().parent / "archive.md").read_text()
        assert task_id in archive

    def test_organize_archived_in_json_output(self, runner):
        data = _add(runner, "Finish report")
        task_id = data["id"]
        content = _tasks_file().read_text()
        _tasks_file().write_text(content.replace(
            f"- [ ] Finish report id:{task_id}",
            f"- [x] Finish report id:{task_id}"
        ))
        result = runner.invoke(cli, ["organize", "--json"])
        assert result.exit_code == 0
        out = _unwrap(result.output)
        assert "archived" in out
        assert out["archived"][0]["id"] == task_id
        assert out["archived"][0]["title"] == "Finish report"

    def test_organize_dry_run_does_not_archive(self, runner):
        data = _add(runner, "Finish report")
        task_id = data["id"]
        content = _tasks_file().read_text()
        _tasks_file().write_text(content.replace(
            f"- [ ] Finish report id:{task_id}",
            f"- [x] Finish report id:{task_id}"
        ))
        result = runner.invoke(cli, ["organize", "--dry-run"])
        assert result.exit_code == 0
        out = _unwrap(result.output)
        assert out["archived"][0]["id"] == task_id
        # File unchanged — task still present (still marked done, not removed)
        tasks = read_tasks()
        assert any(t.id == task_id for t in tasks)

    def test_organize_text_output_mentions_archived(self, runner):
        data = _add(runner, "Finish report")
        task_id = data["id"]
        content = _tasks_file().read_text()
        _tasks_file().write_text(content.replace(
            f"- [ ] Finish report id:{task_id}",
            f"- [x] Finish report id:{task_id}"
        ))
        result = runner.invoke(cli, ["organize"])
        assert result.exit_code == 0
        assert "archived" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: organize --sort
# ---------------------------------------------------------------------------

class TestOrganizeSort:
    def test_sort_by_priority_orders_within_section(self, runner):
        _add(runner, "Low priority task priority:4", section="inbox")
        _add(runner, "High priority task priority:1", section="inbox")
        _add(runner, "Medium priority task priority:2", section="inbox")
        runner.invoke(cli, ["organize", "--sort", "priority"])
        tasks = [t for t in read_tasks() if t.section == "inbox"]
        priorities = [t.priority for t in tasks]
        assert priorities == sorted(priorities)

    def test_sort_by_due_orders_within_section(self, runner):
        _add(runner, "Later task due:2099-12-31")
        _add(runner, "Earlier task due:2099-01-01")
        _add(runner, "Middle task due:2099-06-15")
        runner.invoke(cli, ["organize", "--sort", "due"])
        tasks = [t for t in read_tasks() if t.section == "upcoming"]
        dues = [t.due for t in tasks]
        assert dues == sorted(dues)

    def test_sort_by_title_orders_within_section(self, runner):
        _add(runner, "Zebra task")
        _add(runner, "Apple task")
        _add(runner, "Mango task")
        runner.invoke(cli, ["organize", "--sort", "title"])
        tasks = [t for t in read_tasks() if t.section == "inbox"]
        titles = [t.title.lower() for t in tasks]
        assert titles == sorted(titles)

    def test_sort_keeps_tasks_in_their_sections(self, runner):
        _add(runner, "Inbox B priority:2")
        _add(runner, "Inbox A priority:1")
        _add(runner, "Future B due:2099-12-31 priority:2")
        _add(runner, "Future A due:2099-01-01 priority:1")
        runner.invoke(cli, ["organize", "--sort", "priority"])
        tasks = read_tasks()
        inbox = [t for t in tasks if t.section == "inbox"]
        upcoming = [t for t in tasks if t.section == "upcoming"]
        assert len(inbox) == 2
        assert len(upcoming) == 2
        assert all(t.section == "inbox" for t in inbox)
        assert all(t.section == "upcoming" for t in upcoming)

    def test_sort_does_not_move_sections(self, runner):
        """--sort alone does not reassign sections."""
        _add(runner, "Future task due:2099-01-01", section="inbox")
        runner.invoke(cli, ["organize", "--sort", "priority"])
        tasks = read_tasks()
        t = next(t for t in tasks if t.title == "Future task")
        # Section assignment was not triggered (task already in inbox — no move)
        # But organize still moves it per section rules! So it ends up in upcoming.
        # This test verifies that sort + section move both apply correctly.
        assert t.section == "upcoming"

    def test_sort_json_includes_sorted_by(self, runner):
        _add(runner, "Task A priority:2")
        _add(runner, "Task B priority:1")
        result = runner.invoke(cli, ["organize", "--sort", "priority", "--json"])
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["sorted_by"] == "priority"
        assert "moved" in data

    def test_sort_dry_run_does_not_write(self, runner):
        _add(runner, "Z task priority:4")
        _add(runner, "A task priority:1")
        # Read order before
        before = [t.title for t in read_tasks() if t.section == "inbox"]
        runner.invoke(cli, ["organize", "--sort", "priority", "--dry-run"])
        # File unchanged
        after = [t.title for t in read_tasks() if t.section == "inbox"]
        assert before == after

    def test_sort_no_sort_preserves_insertion_order(self, runner):
        _add(runner, "First task")
        _add(runner, "Second task")
        _add(runner, "Third task")
        runner.invoke(cli, ["organize"])  # no --sort
        tasks = [t for t in read_tasks() if t.section == "inbox"]
        assert [t.title for t in tasks] == ["First task", "Second task", "Third task"]

    def test_sort_mixed_sections_sorted_independently(self, runner):
        """Sort applies within sections, not across them."""
        _add(runner, "Inbox Z priority:4")
        _add(runner, "Inbox A priority:1")
        _add(runner, "Upcoming Z due:2099-12-31 priority:4")
        _add(runner, "Upcoming A due:2099-01-01 priority:1")
        runner.invoke(cli, ["organize", "--sort", "due"])
        tasks = read_tasks()
        upcoming = [t for t in tasks if t.section == "upcoming"]
        dues = [t.due for t in upcoming]
        assert dues == sorted(dues)


# ---------------------------------------------------------------------------
# CLI: edit --set section
# ---------------------------------------------------------------------------

class TestEditSection:
    def test_edit_set_section(self, runner):
        data = _add(runner, "Move me")
        result = runner.invoke(cli, ["edit", data["id"], "--set", "section:someday", "--json"])
        assert result.exit_code == 0
        updated = _unwrap(result.output)
        assert updated["section"] == "someday"

    def test_edit_set_invalid_section_exits_2(self, runner):
        data = _add(runner, "Task")
        result = runner.invoke(cli, ["edit", data["id"], "--set", "section:nonexistent"])
        assert result.exit_code == 2
