"""Tests for todo.query — normalize, parse_query, apply_filters."""

import pytest
from datetime import date, timedelta

from todo.models import Task
from todo.query import (
    PRIORITY_EXPLICIT,
    PRIORITY_IMPLICIT,
    ParsedQuery,
    apply_filters,
    normalize,
    parse_query,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task(**kw) -> Task:
    defaults = dict(title="Task", id="aaa00001")
    defaults.update(kw)
    return Task(**defaults)


def _today() -> str:
    return date.today().isoformat()


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


# ===========================================================================
# normalize()
# ===========================================================================

class TestNormalize:
    def test_lowercases(self):
        assert normalize("HELLO") == "hello"

    def test_removes_intraword_hyphen_letters(self):
        assert normalize("follow-up") == "followup"

    def test_removes_hyphen_email(self):
        assert normalize("e-mail") == "email"

    def test_preserves_date_hyphens(self):
        # Hyphens between digits must NOT be removed
        assert normalize("2026-05-15") == "2026-05-15"

    def test_collapses_whitespace(self):
        assert normalize("buy   milk") == "buy milk"

    def test_strips_leading_trailing_whitespace(self):
        assert normalize("  hello  ") == "hello"

    def test_unicode_nfkc(self):
        # NFKC: ligature ﬁ → fi
        assert normalize("ﬁle") == "file"

    def test_bidirectional_followup(self):
        # Both sides normalize to the same form
        assert normalize("follow-up") == normalize("followup")

    def test_bidirectional_email(self):
        assert normalize("e-mail") == normalize("email")

    def test_empty_string(self):
        assert normalize("") == ""


# ===========================================================================
# parse_query() — structured filters
# ===========================================================================

class TestParseQueryExplicitTag:
    def test_at_syntax(self):
        pq = parse_query("@work meeting")
        assert pq.filters["tag"] == "work"

    def test_at_syntax_removes_from_residual(self):
        pq = parse_query("@work meeting")
        assert "@work" not in pq.residual
        assert "meeting" in pq.residual

    def test_tag_keyword(self):
        pq = parse_query("tag work meeting")
        assert pq.filters["tag"] == "work"
        assert "meeting" in pq.residual

    def test_tagged_keyword(self):
        pq = parse_query("tagged work")
        assert pq.filters["tag"] == "work"

    def test_tag_case_insensitive(self):
        pq = parse_query("@WORK")
        assert pq.filters["tag"] == "work"


class TestParseQueryExplicitSection:
    def test_in_syntax(self):
        pq = parse_query("in waiting vendor")
        assert pq.filters["section"] == "waiting"
        assert "vendor" in pq.residual

    def test_section_keyword(self):
        pq = parse_query("section inbox tasks")
        assert pq.filters["section"] == "inbox"
        assert "tasks" in pq.residual

    def test_section_case_insensitive(self):
        pq = parse_query("in WAITING")
        assert pq.filters["section"] == "waiting"

    def test_invalid_section_ignored(self):
        pq = parse_query("in limbo")
        assert "section" not in pq.filters
        assert "limbo" in pq.residual


class TestParseQueryExplicitPriority:
    def test_p1_filter(self):
        pq = parse_query("p1 login bug")
        assert pq.filters["priority"] == 1

    def test_p4_filter(self):
        pq = parse_query("p4 task")
        assert pq.filters["priority"] == 4

    def test_priority_removed_from_residual(self):
        pq = parse_query("p2 standup")
        assert "p2" not in pq.residual
        assert "standup" in pq.residual


class TestParseQueryExplicitDue:
    def test_due_tomorrow(self):
        pq = parse_query("due tomorrow report")
        assert pq.filters.get("due") == _tomorrow()
        assert "report" in pq.residual

    def test_due_today(self):
        pq = parse_query("due today")
        assert pq.filters.get("due") == _today()

    def test_due_iso_date(self):
        pq = parse_query("due 2099-06-01 invoice")
        assert pq.filters.get("due") == "2099-06-01"
        assert "invoice" in pq.residual

    def test_unparseable_date_not_extracted(self):
        pq = parse_query("due xyzzy task")
        assert "due" not in pq.filters
        # "due xyzzy task" stays in residual
        assert "task" in pq.residual


class TestParseQueryOverdue:
    def test_overdue_filter(self):
        pq = parse_query("overdue invoices")
        assert pq.filters.get("overdue") is True
        assert "invoices" in pq.residual

    def test_overdue_case_insensitive(self):
        pq = parse_query("OVERDUE items")
        assert pq.filters.get("overdue") is True


# ===========================================================================
# parse_query() — implicit hints
# ===========================================================================

class TestParseQueryImplicitHints:
    def test_section_word_generates_hint(self):
        pq = parse_query("waiting vendor")
        assert "waiting" in pq.hints.get("maybe_sections", [])

    def test_high_generates_priority_hint(self):
        pq = parse_query("high priority task")
        assert 1 in pq.hints.get("maybe_priorities", [])

    def test_urgent_generates_priority_hint(self):
        pq = parse_query("urgent fix")
        assert 1 in pq.hints.get("maybe_priorities", [])

    def test_medium_generates_priority_hint(self):
        pq = parse_query("medium effort task")
        assert 2 in pq.hints.get("maybe_priorities", [])

    def test_low_generates_priority_hint(self):
        pq = parse_query("low priority")
        assert 3 in pq.hints.get("maybe_priorities", [])

    def test_today_generates_due_hint(self):
        pq = parse_query("finish today")
        assert _today() in pq.hints.get("maybe_due", [])

    def test_tomorrow_generates_due_hint(self):
        pq = parse_query("call tomorrow")
        assert _tomorrow() in pq.hints.get("maybe_due", [])

    def test_explicit_priority_suppresses_hint(self):
        # p1 is explicit → no implicit priority hint
        pq = parse_query("p1 high task")
        assert "priority" in pq.filters
        assert "maybe_priorities" not in pq.hints

    def test_explicit_section_suppresses_hint(self):
        pq = parse_query("in waiting vendor")
        # "waiting" was consumed as explicit section filter
        assert "section" in pq.filters
        assert "maybe_sections" not in pq.hints

    def test_residual_preserved_with_hints(self):
        pq = parse_query("high priority meeting")
        # All words stay in residual (hints are additive)
        assert "high" in pq.residual
        assert "meeting" in pq.residual


class TestParseQueryEdgeCases:
    def test_empty_query(self):
        pq = parse_query("")
        assert pq.filters == {}
        assert pq.hints == {}
        assert pq.residual == ""

    def test_purely_structural_query(self):
        pq = parse_query("@work p1")
        assert pq.filters["tag"] == "work"
        assert pq.filters["priority"] == 1
        assert pq.residual == ""

    def test_raw_preserved(self):
        raw = "  @work meeting  "
        pq = parse_query(raw)
        assert pq.raw == raw

    def test_to_report_shape(self):
        pq = parse_query("@work meeting")
        report = pq.to_report()
        assert "resolved_filters" in report
        assert "residual_query" in report
        assert report["resolved_filters"]["tag"] == "work"


# ===========================================================================
# apply_filters()
# ===========================================================================

class TestApplyFilters:
    def _parsed(self, **filters) -> ParsedQuery:
        return ParsedQuery(raw="", residual="", filters=filters)

    def test_tag_filter(self):
        tasks = [
            _task(id="aaa", tags=["work"]),
            _task(id="bbb", tags=["home"]),
        ]
        result = apply_filters(tasks, self._parsed(tag="work"))
        assert len(result) == 1
        assert result[0].id == "aaa"

    def test_priority_filter(self):
        tasks = [
            _task(id="aaa", priority=1),
            _task(id="bbb", priority=4),
        ]
        result = apply_filters(tasks, self._parsed(priority=1))
        assert len(result) == 1
        assert result[0].id == "aaa"

    def test_section_filter(self):
        tasks = [
            _task(id="aaa", section="waiting"),
            _task(id="bbb", section="inbox"),
        ]
        result = apply_filters(tasks, self._parsed(section="waiting"))
        assert len(result) == 1
        assert result[0].id == "aaa"

    def test_due_filter(self):
        tasks = [
            _task(id="aaa", due="2099-01-01"),
            _task(id="bbb", due="2099-06-15"),
        ]
        result = apply_filters(tasks, self._parsed(due="2099-01-01"))
        assert len(result) == 1
        assert result[0].id == "aaa"

    def test_overdue_filter(self):
        tasks = [
            _task(id="aaa", due=_yesterday()),   # overdue
            _task(id="bbb", due=_tomorrow()),    # not overdue
            _task(id="ccc", due=None),           # no due date
        ]
        result = apply_filters(tasks, self._parsed(overdue=True))
        assert len(result) == 1
        assert result[0].id == "aaa"

    def test_cli_tag_overrides_query_tag(self):
        tasks = [
            _task(id="aaa", tags=["work"]),
            _task(id="bbb", tags=["personal"]),
        ]
        pq = self._parsed(tag="personal")
        # CLI flag says "work"; should override query-embedded "personal"
        result = apply_filters(tasks, pq, cli_tag="work")
        assert len(result) == 1
        assert result[0].id == "aaa"

    def test_cli_priority_overrides_query_priority(self):
        tasks = [
            _task(id="aaa", priority=1),
            _task(id="bbb", priority=2),
        ]
        pq = self._parsed(priority=2)
        result = apply_filters(tasks, pq, cli_priority=1)
        assert len(result) == 1
        assert result[0].id == "aaa"

    def test_no_filters_returns_all(self):
        tasks = [_task(id="aaa"), _task(id="bbb")]
        result = apply_filters(tasks, self._parsed())
        assert len(result) == 2

    def test_multiple_filters_combined(self):
        tasks = [
            _task(id="aaa", tags=["work"], priority=1),
            _task(id="bbb", tags=["work"], priority=4),
            _task(id="ccc", tags=["home"], priority=1),
        ]
        result = apply_filters(tasks, self._parsed(tag="work", priority=1))
        assert len(result) == 1
        assert result[0].id == "aaa"
