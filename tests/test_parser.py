"""Tests for todo.parser — parse_line, serialize_task, generate_id."""

import pytest
from todo.parser import generate_id, parse_line, serialize_task
from todo.models import Task


# ---------------------------------------------------------------------------
# parse_line
# ---------------------------------------------------------------------------

class TestParseLine:
    def test_returns_none_for_non_task_line(self):
        assert parse_line("# Header") is None
        assert parse_line("") is None
        assert parse_line("plain text") is None

    def test_simple_open_task(self):
        task = parse_line("- [ ] Buy milk id:abc12345")
        assert task is not None
        assert task.title == "Buy milk"
        assert task.done is False
        assert task.id == "abc12345"

    def test_done_task(self):
        task = parse_line("- [x] Call dentist id:xyz99999")
        assert task is not None
        assert task.done is True
        assert task.title == "Call dentist"

    def test_single_tag(self):
        task = parse_line("- [ ] Buy milk @shopping id:aaa11111")
        assert task.tags == ["shopping"]

    def test_multiple_tags(self):
        task = parse_line("- [ ] Renew passport @admin @personal id:bbb22222")
        assert set(task.tags) == {"admin", "personal"}

    def test_context(self):
        task = parse_line("- [ ] Buy milk @shopping +errand id:ccc33333")
        assert task.contexts == ["errand"]

    def test_due_date(self):
        task = parse_line("- [ ] Submit report due:2026-04-15 id:ddd44444")
        assert task.due == "2026-04-15"

    def test_due_datetime(self):
        task = parse_line("- [ ] Stand-up due:2026-04-15T09:00 id:eee55555")
        assert task.due == "2026-04-15T09:00"

    def test_priority(self):
        task = parse_line("- [ ] Urgent fix priority:1 id:fff66666")
        assert task.priority == 1

    def test_default_priority_is_4(self):
        task = parse_line("- [ ] Low-key task id:ggg77777")
        assert task.priority == 4

    def test_recur(self):
        task = parse_line("- [ ] Water plants recur:weekly id:hhh88888")
        assert task.recur == "weekly"

    def test_notify(self):
        task = parse_line("- [ ] Meeting due:2026-04-15T10:00 notify:30m id:iii99999")
        assert task.notify == "30m"

    def test_snooze(self):
        task = parse_line("- [ ] Read book snooze:2026-04-20T08:00 id:jjj00000")
        assert task.snooze == "2026-04-20T08:00"

    def test_title_extracted_cleanly(self):
        """Tags, contexts, and key:value fields must not bleed into the title."""
        task = parse_line(
            "- [ ] Buy groceries @shopping +errand due:2026-04-15 priority:2 id:kkk11111"
        )
        assert task.title == "Buy groceries"

    def test_title_with_multiple_words_and_fields(self):
        task = parse_line(
            "- [ ] Review quarterly report @work priority:1 due:2026-04-30 id:lll22222"
        )
        assert task.title == "Review quarterly report"

    def test_generates_id_if_missing(self):
        task = parse_line("- [ ] No id here")
        assert task is not None
        assert len(task.id) == 8

    def test_full_task(self):
        line = (
            "- [ ] Buy groceries @shopping @food +errand "
            "due:2026-04-15 recur:weekly priority:2 notify:1h "
            "snooze:2026-04-14T08:00 id:mmm33333"
        )
        task = parse_line(line)
        assert task.title == "Buy groceries"
        assert task.done is False
        assert set(task.tags) == {"shopping", "food"}
        assert task.contexts == ["errand"]
        assert task.due == "2026-04-15"
        assert task.recur == "weekly"
        assert task.priority == 2
        assert task.notify == "1h"
        assert task.snooze == "2026-04-14T08:00"
        assert task.id == "mmm33333"


# ---------------------------------------------------------------------------
# serialize_task
# ---------------------------------------------------------------------------

class TestSerializeTask:
    def test_open_task(self):
        task = Task(title="Buy milk", id="abc12345")
        line = serialize_task(task)
        assert line.startswith("- [ ] ")
        assert "Buy milk" in line
        assert "id:abc12345" in line

    def test_done_task(self):
        task = Task(title="Done thing", id="xyz00000", done=True)
        assert serialize_task(task).startswith("- [x] ")

    def test_priority_4_not_serialized(self):
        task = Task(title="Low", id="aaa00001", priority=4)
        assert "priority:" not in serialize_task(task)

    def test_priority_1_serialized(self):
        task = Task(title="Urgent", id="bbb00002", priority=1)
        assert "priority:1" in serialize_task(task)

    def test_tags_serialized(self):
        task = Task(title="Buy milk", id="ccc00003", tags=["shopping"])
        assert "@shopping" in serialize_task(task)

    def test_contexts_serialized(self):
        task = Task(title="Errand", id="ddd00004", contexts=["home"])
        assert "+home" in serialize_task(task)

    def test_due_serialized(self):
        task = Task(title="Task", id="eee00005", due="2026-04-15")
        assert "due:2026-04-15" in serialize_task(task)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def _round_trip(self, line: str) -> str:
        task = parse_line(line)
        assert task is not None
        return serialize_task(task)

    def test_simple(self):
        line = "- [ ] Buy milk @shopping id:abc12345"
        task = parse_line(self._round_trip(line))
        assert task.title == "Buy milk"
        assert task.tags == ["shopping"]
        assert task.id == "abc12345"

    def test_full_task_preserves_all_fields(self):
        line = (
            "- [ ] Buy groceries @shopping +errand "
            "due:2026-04-15 recur:weekly priority:2 notify:1h id:mmm33333"
        )
        task = parse_line(self._round_trip(line))
        assert task.title == "Buy groceries"
        assert task.tags == ["shopping"]
        assert task.contexts == ["errand"]
        assert task.due == "2026-04-15"
        assert task.recur == "weekly"
        assert task.priority == 2
        assert task.notify == "1h"
        assert task.id == "mmm33333"

    def test_done_preserved(self):
        line = "- [x] Done task id:zzz99999"
        task = parse_line(self._round_trip(line))
        assert task.done is True


# ---------------------------------------------------------------------------
# generate_id
# ---------------------------------------------------------------------------

class TestGenerateId:
    def test_length(self):
        assert len(generate_id()) == 8

    def test_alphanumeric(self):
        id_ = generate_id()
        assert id_.isalnum()
        assert id_.islower()

    def test_uniqueness(self):
        ids = {generate_id() for _ in range(1000)}
        assert len(ids) == 1000
