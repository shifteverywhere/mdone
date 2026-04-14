"""Tests for todo.dates — parse_due_date, parse_snooze_duration, recurrence."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from todo.dates import (
    _add_months,
    is_snoozed,
    next_recurrence,
    parse_due_date,
    parse_snooze_duration,
    spawn_next_occurrence,
)
from todo.models import Task

TODAY = date(2026, 4, 13)   # Monday — fixed reference date for all tests
NOW   = datetime(2026, 4, 13, 10, 0)


def _fixed_today(monkeypatch):
    """Patch date.today() to always return TODAY."""
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return TODAY
    monkeypatch.setattr("todo.dates.date", _FixedDate)


def _fixed_now(monkeypatch):
    """Patch datetime.now() to always return NOW."""
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr("todo.dates.datetime", _FixedDatetime)


# ---------------------------------------------------------------------------
# _add_months
# ---------------------------------------------------------------------------

class TestAddMonths:
    def test_simple(self):
        assert _add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)

    def test_crosses_year_boundary(self):
        assert _add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)

    def test_end_of_month_clamped(self):
        # Jan 31 + 1 month → Feb 28 (2026 is not a leap year)
        assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)

    def test_leap_year(self):
        # Jan 31, 2024 + 1 month → Feb 29 (2024 IS a leap year)
        assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)

    def test_multiple_months(self):
        assert _add_months(date(2026, 1, 1), 6) == date(2026, 7, 1)


# ---------------------------------------------------------------------------
# parse_due_date
# ---------------------------------------------------------------------------

class TestParseDueDate:
    def test_iso_date_passthrough(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("2026-04-15") == "2026-04-15"

    def test_iso_datetime_passthrough(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("2026-04-15T09:00") == "2026-04-15T09:00"

    def test_today(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("today") == "2026-04-13"

    def test_tomorrow(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("tomorrow") == "2026-04-14"

    def test_yesterday(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("yesterday") == "2026-04-12"

    def test_next_monday_from_monday(self, monkeypatch):
        # TODAY is Monday (weekday 0); next-monday should give +7 days
        _fixed_today(monkeypatch)
        assert parse_due_date("next-monday") == "2026-04-20"

    def test_next_friday_from_monday(self, monkeypatch):
        # Monday → Friday = +4 days
        _fixed_today(monkeypatch)
        assert parse_due_date("next-friday") == "2026-04-17"

    def test_next_sunday_from_monday(self, monkeypatch):
        # Monday → Sunday = +6 days
        _fixed_today(monkeypatch)
        assert parse_due_date("next-sunday") == "2026-04-19"

    def test_in_3_days(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("in-3-days") == "2026-04-16"

    def test_in_1_week(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("in-1-week") == "2026-04-20"

    def test_in_2_weeks(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("in-2-weeks") == "2026-04-27"

    def test_in_1_month(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("in-1-month") == "2026-05-13"

    def test_in_1_month_end_of_month(self, monkeypatch):
        class _Jan31(date):
            @classmethod
            def today(cls):
                return date(2026, 1, 31)
        monkeypatch.setattr("todo.dates.date", _Jan31)
        assert parse_due_date("in-1-month") == "2026-02-28"

    def test_unknown_returns_original(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("someday") == "someday"

    def test_case_insensitive_keyword(self, monkeypatch):
        _fixed_today(monkeypatch)
        assert parse_due_date("Tomorrow") == "2026-04-14"
        assert parse_due_date("TOMORROW") == "2026-04-14"


# ---------------------------------------------------------------------------
# parse_snooze_duration
# ---------------------------------------------------------------------------

class TestParseSnooze:
    def test_minutes(self, monkeypatch):
        _fixed_now(monkeypatch)
        assert parse_snooze_duration("30m") == "2026-04-13T10:30"

    def test_hours(self, monkeypatch):
        _fixed_now(monkeypatch)
        assert parse_snooze_duration("2h") == "2026-04-13T12:00"

    def test_days(self, monkeypatch):
        _fixed_now(monkeypatch)
        assert parse_snooze_duration("1d") == "2026-04-14T10:00"

    def test_absolute_datetime(self, monkeypatch):
        _fixed_now(monkeypatch)
        assert parse_snooze_duration("2026-04-20T09:00") == "2026-04-20T09:00"

    def test_case_insensitive(self, monkeypatch):
        _fixed_now(monkeypatch)
        assert parse_snooze_duration("1H") == "2026-04-13T11:00"

    def test_invalid_raises(self, monkeypatch):
        _fixed_now(monkeypatch)
        with pytest.raises(ValueError):
            parse_snooze_duration("next-week")


# ---------------------------------------------------------------------------
# is_snoozed
# ---------------------------------------------------------------------------

class TestIsSnoozed:
    def _task(self, snooze=None):
        return Task(title="T", id="aaa00001", snooze=snooze)

    def test_no_snooze_is_false(self):
        assert is_snoozed(self._task()) is False

    def test_past_snooze_is_false(self):
        assert is_snoozed(self._task(snooze="2020-01-01T00:00")) is False

    def test_future_snooze_is_true(self):
        assert is_snoozed(self._task(snooze="2099-12-31T23:59")) is True

    def test_invalid_snooze_is_false(self):
        assert is_snoozed(self._task(snooze="not-a-date")) is False


# ---------------------------------------------------------------------------
# next_recurrence
# ---------------------------------------------------------------------------

class TestNextRecurrence:
    def test_daily(self):
        assert next_recurrence("2026-04-13", "daily") == "2026-04-14"

    def test_weekly(self):
        assert next_recurrence("2026-04-13", "weekly") == "2026-04-20"

    def test_monthly(self):
        assert next_recurrence("2026-04-13", "monthly") == "2026-05-13"

    def test_monthly_end_of_month(self):
        # Jan 31 + 1 month → Feb 28
        assert next_recurrence("2026-01-31", "monthly") == "2026-02-28"

    def test_due_with_time_component(self):
        # Time part is stripped; only the date is used
        assert next_recurrence("2026-04-13T09:00", "daily") == "2026-04-14"

    def test_no_due_uses_today(self, monkeypatch):
        class _FixedDate(date):
            @classmethod
            def today(cls):
                return date(2026, 4, 13)
        monkeypatch.setattr("todo.dates.date", _FixedDate)
        assert next_recurrence(None, "daily") == "2026-04-14"

    def test_unknown_rule_returns_none(self):
        assert next_recurrence("2026-04-13", "RRULE:FREQ=YEARLY") is None


# ---------------------------------------------------------------------------
# spawn_next_occurrence
# ---------------------------------------------------------------------------

class TestSpawnNextOccurrence:
    def _recurring_task(self, recur="weekly", due="2026-04-13"):
        return Task(
            title="Water plants",
            id="orig0001",
            tags=["home"],
            contexts=["garden"],
            due=due,
            recur=recur,
            priority=2,
            notify="1h",
            snooze="2026-04-12T08:00",  # should be cleared on spawn
        )

    def test_returns_none_without_recur(self):
        task = Task(title="One-off", id="aaa00001")
        assert spawn_next_occurrence(task) is None

    def test_new_id_is_different(self):
        task = self._recurring_task()
        nxt = spawn_next_occurrence(task)
        assert nxt is not None
        assert nxt.id != task.id

    def test_next_due_is_correct(self):
        task = self._recurring_task(recur="weekly", due="2026-04-13")
        nxt = spawn_next_occurrence(task)
        assert nxt.due == "2026-04-20"

    def test_preserves_title_and_tags(self):
        task = self._recurring_task()
        nxt = spawn_next_occurrence(task)
        assert nxt.title == task.title
        assert nxt.tags == task.tags
        assert nxt.contexts == task.contexts
        assert nxt.priority == task.priority
        assert nxt.notify == task.notify
        assert nxt.recur == task.recur

    def test_snooze_is_cleared(self):
        task = self._recurring_task()
        nxt = spawn_next_occurrence(task)
        assert nxt.snooze is None

    def test_done_is_false(self):
        task = self._recurring_task()
        nxt = spawn_next_occurrence(task)
        assert nxt.done is False

    def test_unknown_rule_returns_none(self):
        task = Task(title="T", id="aaa00001", recur="RRULE:FREQ=YEARLY")
        assert spawn_next_occurrence(task) is None
