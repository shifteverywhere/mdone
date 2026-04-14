"""Tests for todo.storage — file-backed task persistence."""

import os
import pytest
from todo.models import Task
from todo.storage import (
    add_task,
    archive_task,
    delete_task,
    find_task,
    read_tasks,
    update_task,
    write_tasks,
    _tasks_file,
    _archive_file,
)


@pytest.fixture(autouse=True)
def isolated_todo_dir(tmp_path, monkeypatch):
    """Point TODO_DIR at a temp directory for every test."""
    monkeypatch.setenv("TODO_DIR", str(tmp_path))


def _make_task(**kwargs) -> Task:
    defaults = dict(title="Test task", id="test0001")
    defaults.update(kwargs)
    return Task(**defaults)


# ---------------------------------------------------------------------------
# read / write
# ---------------------------------------------------------------------------

class TestReadWrite:
    def test_empty_file_returns_empty_list(self):
        assert read_tasks() == []

    def test_write_and_read_back(self):
        task = _make_task(title="Buy milk", id="aaa00001")
        write_tasks([task])
        tasks = read_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Buy milk"
        assert tasks[0].id == "aaa00001"

    def test_multiple_tasks(self):
        tasks = [
            _make_task(title="Task A", id="aaa00001"),
            _make_task(title="Task B", id="bbb00002"),
        ]
        write_tasks(tasks)
        result = read_tasks()
        assert len(result) == 2
        assert {t.title for t in result} == {"Task A", "Task B"}

    def test_non_task_lines_are_ignored(self):
        """Lines that don't match the task format are silently skipped."""
        _tasks_file().write_text("# Header\n\n- [ ] Real task id:aaa00001\n\nsome note\n")
        tasks = read_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "aaa00001"


# ---------------------------------------------------------------------------
# add_task
# ---------------------------------------------------------------------------

class TestAddTask:
    def test_add_single(self):
        task = _make_task(title="New task", id="nnn00001")
        add_task(task)
        assert len(read_tasks()) == 1

    def test_add_multiple_accumulates(self):
        add_task(_make_task(title="A", id="aaa00001"))
        add_task(_make_task(title="B", id="bbb00002"))
        assert len(read_tasks()) == 2


# ---------------------------------------------------------------------------
# find_task
# ---------------------------------------------------------------------------

class TestFindTask:
    def test_find_existing(self):
        add_task(_make_task(title="Findable", id="fff00001"))
        task = find_task("fff00001")
        assert task is not None
        assert task.title == "Findable"

    def test_find_nonexistent_returns_none(self):
        assert find_task("doesnotexist") is None


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------

class TestUpdateTask:
    def test_update_title(self):
        task = _make_task(title="Old title", id="uuu00001")
        add_task(task)
        task.title = "New title"
        assert update_task(task) is True
        assert find_task("uuu00001").title == "New title"

    def test_update_priority(self):
        task = _make_task(title="Task", id="uuu00002", priority=4)
        add_task(task)
        task.priority = 1
        update_task(task)
        assert find_task("uuu00002").priority == 1

    def test_update_nonexistent_returns_false(self):
        task = _make_task(title="Ghost", id="zzz99999")
        assert update_task(task) is False

    def test_update_does_not_change_other_tasks(self):
        t1 = _make_task(title="Task 1", id="ttt00001")
        t2 = _make_task(title="Task 2", id="ttt00002")
        add_task(t1)
        add_task(t2)
        t1.title = "Task 1 updated"
        update_task(t1)
        assert find_task("ttt00002").title == "Task 2"


# ---------------------------------------------------------------------------
# delete_task
# ---------------------------------------------------------------------------

class TestDeleteTask:
    def test_delete_removes_task(self):
        add_task(_make_task(title="To delete", id="ddd00001"))
        assert delete_task("ddd00001") is True
        assert find_task("ddd00001") is None

    def test_delete_nonexistent_returns_false(self):
        assert delete_task("doesnotexist") is False

    def test_delete_does_not_affect_others(self):
        add_task(_make_task(title="Keep", id="kkk00001"))
        add_task(_make_task(title="Remove", id="rrr00001"))
        delete_task("rrr00001")
        assert find_task("kkk00001") is not None
        assert len(read_tasks()) == 1


# ---------------------------------------------------------------------------
# archive_task
# ---------------------------------------------------------------------------

class TestArchiveTask:
    def test_archive_writes_to_archive_file(self):
        task = _make_task(title="Archived task", id="arc00001")
        archive_task(task)
        content = _archive_file().read_text()
        assert "arc00001" in content
        assert "Archived task" in content

    def test_archive_marks_done(self):
        task = _make_task(title="Task", id="arc00002", done=False)
        archive_task(task)
        content = _archive_file().read_text()
        assert "- [x]" in content

    def test_archive_appends(self):
        archive_task(_make_task(title="First", id="arc00003"))
        archive_task(_make_task(title="Second", id="arc00004"))
        content = _archive_file().read_text()
        assert "arc00003" in content
        assert "arc00004" in content
