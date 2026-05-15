"""
Tests for todo.notify.checker — pending detection, lead-time parsing,
.notified state management, multi-offset, quiet hours.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path

from todo.models import Task
from todo.notify.checker import (
    _parse_lead,
    _parse_due,
    build_pending,
    is_quiet_hours,
    load_notified,
    mark_sent,
    parse_notify_offsets,
    reset_notified,
)


@pytest.fixture(autouse=True)
def isolated_todo_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TODO_DIR", str(tmp_path))


NOW = datetime(2026, 4, 13, 10, 0)   # fixed reference


def _task(**kwargs) -> Task:
    defaults = dict(title="Task", id="aaa00001", due="2026-04-13T10:30", notify="30m")
    defaults.update(kwargs)
    return Task(**defaults)


# ---------------------------------------------------------------------------
# parse_notify_offsets
# ---------------------------------------------------------------------------

class TestParseNotifyOffsets:
    def test_single_offset(self):
        assert parse_notify_offsets("30m") == ["30m"]

    def test_multiple_offsets(self):
        assert parse_notify_offsets("30m,2h,1d") == ["30m", "2h", "1d"]

    def test_whitespace_stripped(self):
        assert parse_notify_offsets("30m, 2h , 1d") == ["30m", "2h", "1d"]

    def test_empty_string(self):
        assert parse_notify_offsets("") == []

    def test_none_returns_empty(self):
        assert parse_notify_offsets(None or "") == []


# ---------------------------------------------------------------------------
# _parse_lead
# ---------------------------------------------------------------------------

class TestParseLead:
    def test_minutes(self):
        assert _parse_lead("30m") == timedelta(minutes=30)

    def test_hours(self):
        assert _parse_lead("2h") == timedelta(hours=2)

    def test_days(self):
        assert _parse_lead("1d") == timedelta(days=1)

    def test_case_insensitive(self):
        assert _parse_lead("1H") == timedelta(hours=1)
        assert _parse_lead("30M") == timedelta(minutes=30)

    def test_invalid_returns_none(self):
        assert _parse_lead("soon") is None
        assert _parse_lead("") is None


# ---------------------------------------------------------------------------
# _parse_due
# ---------------------------------------------------------------------------

class TestParseDue:
    def test_date_becomes_midnight(self):
        dt = _parse_due("2026-04-13")
        assert dt == datetime(2026, 4, 13, 0, 0)

    def test_datetime_preserved(self):
        dt = _parse_due("2026-04-13T14:30")
        assert dt == datetime(2026, 4, 13, 14, 30)

    def test_invalid_returns_none(self):
        assert _parse_due("not-a-date") is None


# ---------------------------------------------------------------------------
# is_quiet_hours
# ---------------------------------------------------------------------------

class TestIsQuietHours:
    def test_same_day_inside_window(self):
        now = datetime(2026, 4, 13, 14, 0)
        assert is_quiet_hours("09:00-17:00", now) is True

    def test_same_day_before_window(self):
        now = datetime(2026, 4, 13, 8, 0)
        assert is_quiet_hours("09:00-17:00", now) is False

    def test_same_day_after_window(self):
        now = datetime(2026, 4, 13, 18, 0)
        assert is_quiet_hours("09:00-17:00", now) is False

    def test_same_day_at_start_boundary(self):
        now = datetime(2026, 4, 13, 9, 0)
        assert is_quiet_hours("09:00-17:00", now) is True

    def test_same_day_at_end_boundary(self):
        # End is exclusive
        now = datetime(2026, 4, 13, 17, 0)
        assert is_quiet_hours("09:00-17:00", now) is False

    def test_cross_midnight_inside_evening(self):
        now = datetime(2026, 4, 13, 23, 0)
        assert is_quiet_hours("22:00-08:00", now) is True

    def test_cross_midnight_inside_morning(self):
        now = datetime(2026, 4, 13, 7, 0)
        assert is_quiet_hours("22:00-08:00", now) is True

    def test_cross_midnight_outside_window(self):
        now = datetime(2026, 4, 13, 12, 0)
        assert is_quiet_hours("22:00-08:00", now) is False

    def test_empty_string_returns_false(self):
        now = datetime(2026, 4, 13, 2, 0)
        assert is_quiet_hours("", now) is False

    def test_invalid_format_returns_false(self):
        now = datetime(2026, 4, 13, 2, 0)
        assert is_quiet_hours("not-a-range", now) is False


# ---------------------------------------------------------------------------
# build_pending
# ---------------------------------------------------------------------------

class TestBuildPending:
    def test_task_in_window_is_pending(self):
        # due 10:30, notify 30m → window opens at 10:00 → NOW is exactly 10:00
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        result = build_pending([task], {}, now=NOW)
        assert any(p["id"] == "aaa00001" for p in result)

    def test_task_before_window_not_pending(self):
        # due 11:30, notify 30m → window opens at 11:00 → NOW=10:00 too early
        task = _task(id="aaa00001", due="2026-04-13T11:30", notify="30m")
        result = build_pending([task], {}, now=NOW)
        assert result == []

    def test_already_notified_legacy_bare_key_excluded(self):
        # Legacy bare task_id suppresses all offsets for that task
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        result = build_pending([task], {"aaa00001": "2026-04-13T10:00"}, now=NOW)
        assert result == []

    def test_already_notified_per_offset_excluded(self):
        # Composite key suppresses that specific offset
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        result = build_pending([task], {"aaa00001:30m": "2026-04-13T10:00"}, now=NOW)
        assert not any(p["offset"] == "30m" for p in result)

    def test_done_task_excluded(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m", done=True)
        result = build_pending([task], {}, now=NOW)
        assert result == []

    def test_snoozed_task_excluded(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m",
                     snooze="2099-12-31T23:59")
        result = build_pending([task], {}, now=NOW)
        assert result == []

    def test_no_due_excluded(self):
        task = _task(id="aaa00001", due=None, notify="30m")
        result = build_pending([task], {}, now=NOW)
        assert result == []

    def test_overdue_no_notify_surfaces(self):
        # No notify field but task is overdue → still surfaces via "overdue" sentinel
        task = _task(id="aaa00001", due="2026-04-12", notify=None)
        result = build_pending([task], {}, now=NOW)
        assert len(result) == 1
        assert result[0]["overdue"] is True
        assert result[0]["offset"] == "overdue"

    def test_future_no_notify_not_pending(self):
        task = _task(id="aaa00001", due="2099-12-31", notify=None)
        result = build_pending([task], {}, now=NOW)
        assert result == []

    def test_payload_fields(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m",
                     priority=1, tags=["work"])
        result = build_pending([task], {}, now=NOW)
        p = result[0]
        assert p["id"] == "aaa00001"
        assert p["title"] == "Task"
        assert p["due"] == "2026-04-13T10:30"
        assert p["notify"] == "30m"
        assert p["priority"] == 1
        assert p["tags"] == ["work"]
        assert isinstance(p["overdue"], bool)
        assert isinstance(p["minutes_until_due"], int)
        assert "offset" in p
        assert "notify_key" in p

    def test_payload_notify_key_format(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        result = build_pending([task], {}, now=NOW)
        p = result[0]
        assert p["offset"] == "30m"
        assert p["notify_key"] == "aaa00001:30m"

    def test_overdue_payload_notify_key(self):
        task = _task(id="aaa00001", due="2026-04-12", notify=None)
        result = build_pending([task], {}, now=NOW)
        p = result[0]
        assert p["offset"] == "overdue"
        assert p["notify_key"] == "aaa00001:overdue"

    def test_overdue_flag_true_when_past(self):
        task = _task(id="aaa00001", due="2026-04-13T09:00", notify="30m")
        result = build_pending([task], {}, now=NOW)
        assert result[0]["overdue"] is True

    def test_overdue_flag_false_when_future(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        result = build_pending([task], {}, now=NOW)
        offset_result = next(p for p in result if p["offset"] == "30m")
        assert offset_result["overdue"] is False

    def test_minutes_until_due_negative_when_overdue(self):
        task = _task(id="aaa00001", due="2026-04-13T09:00", notify="1h")
        result = build_pending([task], {}, now=NOW)
        assert result[0]["minutes_until_due"] < 0

    def test_sorted_overdue_first(self):
        t1 = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")  # not yet overdue
        t2 = _task(id="bbb00002", due="2026-04-13T09:00", notify="1h")   # overdue
        result = build_pending([t1, t2], {}, now=NOW)
        assert result[0]["overdue"] is True  # overdue item comes first

    def test_multiple_tasks(self):
        tasks = [
            _task(id="aaa00001", due="2026-04-13T10:30", notify="30m"),
            _task(id="bbb00002", due="2026-04-13T10:30", notify="30m"),
        ]
        result = build_pending(tasks, {}, now=NOW)
        ids = {p["id"] for p in result}
        assert "aaa00001" in ids
        assert "bbb00002" in ids


# ---------------------------------------------------------------------------
# Multiple offsets
# ---------------------------------------------------------------------------

class TestMultipleOffsets:
    def test_all_offsets_fire_independently(self):
        # Task with two offsets; both windows are open
        # due 10:30, notify "30m,2h": 30m window opens at 10:00, 2h window
        # opens at 08:30 — both before NOW=10:00
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m,2h")
        result = build_pending([task], {}, now=NOW)
        offsets = {p["offset"] for p in result}
        assert "30m" in offsets
        assert "2h" in offsets

    def test_first_offset_suppressed_second_still_fires(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m,2h")
        notified = {"aaa00001:30m": "2026-04-13T10:00"}
        result = build_pending([task], notified, now=NOW)
        offsets = {p["offset"] for p in result}
        assert "30m" not in offsets
        assert "2h" in offsets

    def test_second_offset_not_yet_open(self):
        # due 12:30; 30m window opens at 12:00 (open), 3h window opens at 09:30 (open);
        # but 24h window opens yesterday (open) — use a tight due to test "not open yet"
        # due 11:30, notify 30m,2h: 30m opens at 11:00 (not open, NOW=10:00)
        #                             2h opens at 09:30 (open)
        task = _task(id="aaa00001", due="2026-04-13T11:30", notify="30m,2h")
        result = build_pending([task], {}, now=NOW)
        offsets = {p["offset"] for p in result}
        assert "30m" not in offsets  # 11:00 > NOW
        assert "2h" in offsets       # 09:30 <= NOW

    def test_each_offset_gets_unique_notify_key(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m,2h")
        result = build_pending([task], {}, now=NOW)
        keys = {p["notify_key"] for p in result}
        assert "aaa00001:30m" in keys
        assert "aaa00001:2h" in keys

    def test_overdue_fires_alongside_offsets(self):
        # Overdue task with notify: both the offset AND the overdue sentinel fire
        task = _task(id="aaa00001", due="2026-04-13T09:00", notify="30m")
        result = build_pending([task], {}, now=NOW)
        offsets = {p["offset"] for p in result}
        assert "30m" in offsets
        assert "overdue" in offsets


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

class TestQuietHours:
    def test_quiet_hours_suppresses_all_pending(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        # NOW=10:00 is inside quiet window 09:00-17:00
        config = {"notifications": {"quiet_hours": "09:00-17:00"}}
        result = build_pending([task], {}, now=NOW, config=config)
        assert result == []

    def test_outside_quiet_hours_returns_pending(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        # NOW=10:00 is outside quiet window 22:00-08:00
        config = {"notifications": {"quiet_hours": "22:00-08:00"}}
        result = build_pending([task], {}, now=NOW, config=config)
        assert any(p["id"] == "aaa00001" for p in result)

    def test_no_config_no_quiet_hours(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        result = build_pending([task], {}, now=NOW, config=None)
        assert any(p["id"] == "aaa00001" for p in result)

    def test_empty_quiet_hours_no_suppression(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        config = {"notifications": {"quiet_hours": ""}}
        result = build_pending([task], {}, now=NOW, config=config)
        assert any(p["id"] == "aaa00001" for p in result)

    def test_cross_midnight_quiet_hours(self):
        # NOW = 23:30, inside 22:00-08:00 window
        now_night = datetime(2026, 4, 13, 23, 30)
        task = _task(id="aaa00001", due="2026-04-14T00:00", notify="30m")
        config = {"notifications": {"quiet_hours": "22:00-08:00"}}
        result = build_pending([task], {}, now=now_night, config=config)
        assert result == []


# ---------------------------------------------------------------------------
# .notified state — mark_sent / load_notified / reset_notified
# ---------------------------------------------------------------------------

class TestNotifiedState:
    def test_mark_then_load(self):
        mark_sent(["abc12345"])
        notified = load_notified()
        assert "abc12345" in notified

    def test_mark_composite_key(self):
        mark_sent(["abc12345:30m"])
        notified = load_notified()
        assert "abc12345:30m" in notified

    def test_mark_multiple(self):
        mark_sent(["aaa00001", "bbb00002"])
        notified = load_notified()
        assert "aaa00001" in notified
        assert "bbb00002" in notified

    def test_load_empty(self):
        assert load_notified() == {}

    def test_reset_all(self):
        mark_sent(["aaa00001", "bbb00002"])
        reset_notified()
        assert load_notified() == {}

    def test_reset_single_bare_key(self):
        mark_sent(["aaa00001", "bbb00002"])
        reset_notified("aaa00001")
        notified = load_notified()
        assert "aaa00001" not in notified
        assert "bbb00002" in notified

    def test_reset_removes_composite_keys(self):
        mark_sent(["aaa00001:30m", "aaa00001:2h", "bbb00002:1d"])
        reset_notified("aaa00001")
        notified = load_notified()
        assert "aaa00001:30m" not in notified
        assert "aaa00001:2h" not in notified
        assert "bbb00002:1d" in notified

    def test_reset_nonexistent_id_is_safe(self):
        mark_sent(["aaa00001"])
        reset_notified("zzz99999")   # does not exist — no crash
        assert "aaa00001" in load_notified()

    def test_marked_tasks_excluded_from_pending_legacy(self):
        # Bare key still suppresses via legacy compat
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        mark_sent(["aaa00001"])
        notified = load_notified()
        result = build_pending([task], notified, now=NOW)
        assert result == []

    def test_marked_composite_key_suppresses_offset(self):
        task = _task(id="aaa00001", due="2026-04-13T10:30", notify="30m")
        mark_sent(["aaa00001:30m"])
        notified = load_notified()
        result = build_pending([task], notified, now=NOW)
        assert not any(p["offset"] == "30m" for p in result)
