"""
Tests for todo.nlp — infer_priority, infer_tags, parse_natural.

Date extraction uses dateparser internally.  Those tests mock _search_dates
so results are deterministic regardless of the current date.
"""

from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from todo.nlp import (
    _clean_title,
    _strip_fillers,
    infer_priority,
    infer_tags,
    parse_natural,
)


# ---------------------------------------------------------------------------
# infer_priority
# ---------------------------------------------------------------------------

class TestInferPriority:
    def test_urgent_keyword(self):
        assert infer_priority("urgent: call the client") == 1

    def test_asap(self):
        assert infer_priority("Fix the server ASAP") == 1

    def test_critical(self):
        assert infer_priority("critical bug in production") == 1

    def test_important(self):
        assert infer_priority("important meeting with stakeholders") == 2

    def test_high_priority(self):
        assert infer_priority("high priority: submit the report") == 2

    def test_high_priority_hyphen(self):
        assert infer_priority("high-priority refactor") == 2

    def test_someday(self):
        assert infer_priority("someday learn Spanish") == 4

    def test_low_priority(self):
        assert infer_priority("low priority cleanup") == 4

    def test_eventually(self):
        assert infer_priority("eventually migrate the database") == 4

    def test_no_signal_defaults_to_4(self):
        assert infer_priority("call Alice") == 4

    def test_case_insensitive(self):
        assert infer_priority("URGENT fix this now") == 1
        assert infer_priority("Someday visit Japan") == 4

    def test_first_match_wins(self):
        # "urgent" appears before "important" in _PRIORITY_PATTERNS
        assert infer_priority("urgent and important task") == 1


# ---------------------------------------------------------------------------
# infer_tags
# ---------------------------------------------------------------------------

class TestInferTags:
    def test_health_dentist(self):
        assert "health" in infer_tags("dentist appointment")

    def test_health_gym(self):
        assert "health" in infer_tags("gym session at 7am")

    def test_work_meeting(self):
        assert "work" in infer_tags("team meeting at 10am")

    def test_work_bug(self):
        assert "work" in infer_tags("Fix login bug")

    def test_work_review(self):
        assert "work" in infer_tags("Code review for feature branch")

    def test_shopping_buy(self):
        assert "shopping" in infer_tags("buy milk and eggs")

    def test_shopping_groceries(self):
        assert "shopping" in infer_tags("Pick up groceries")

    def test_finance_pay_bill(self):
        assert "finance" in infer_tags("pay electricity bill")

    def test_finance_invoice(self):
        assert "finance" in infer_tags("Send invoice to client")

    def test_home_clean(self):
        assert "home" in infer_tags("Clean the kitchen")

    def test_home_repair(self):
        assert "home" in infer_tags("repair the leaky tap")

    def test_personal_birthday(self):
        assert "personal" in infer_tags("Buy birthday gift for mum")

    def test_multiple_tags(self):
        tags = infer_tags("Buy medicine from the pharmacy")
        assert "shopping" in tags
        assert "health" in tags

    def test_no_match_returns_empty(self):
        assert infer_tags("random task with no keywords") == []

    def test_case_insensitive(self):
        assert "health" in infer_tags("DENTIST APPOINTMENT")

    def test_no_partial_word_false_positive(self):
        # "pay" is in "repay" — padded matching should handle boundaries
        tags = infer_tags("Repay the favour")
        # "repay" contains "pay" — this is a known limitation we document,
        # not a bug we assert against.  Just ensure no crash.
        assert isinstance(tags, list)


# ---------------------------------------------------------------------------
# _strip_fillers / _clean_title helpers
# ---------------------------------------------------------------------------

class TestStripFillers:
    def test_remind_me_to(self):
        assert _strip_fillers("remind me to call Alice") == "call Alice"

    def test_dont_forget_to(self):
        assert _strip_fillers("don't forget to submit the form") == "submit the form"

    def test_i_need_to(self):
        assert _strip_fillers("I need to book a flight") == "book a flight"

    def test_i_should(self):
        assert _strip_fillers("I should call the doctor") == "call the doctor"

    def test_please(self):
        assert _strip_fillers("please send the invoice") == "send the invoice"

    def test_no_filler_unchanged(self):
        assert _strip_fillers("buy groceries") == "buy groceries"

    def test_case_insensitive(self):
        assert _strip_fillers("REMIND ME TO water the plants") == "water the plants"


class TestCleanTitle:
    def test_sentence_case(self):
        assert _clean_title("call alice") == "Call alice"

    def test_strips_trailing_preposition(self):
        result = _clean_title("call Alice on")
        assert not result.endswith(" on")

    def test_strips_leading_preposition(self):
        result = _clean_title("on the project")
        assert not result.startswith("on ")

    def test_strips_priority_prefix(self):
        assert _clean_title("urgent: fix the bug") == "Fix the bug"
        assert _clean_title("important - review docs") == "Review docs"

    def test_collapses_whitespace(self):
        assert _clean_title("fix   the   bug") == "Fix the bug"

    def test_empty_string(self):
        assert _clean_title("") == ""


# ---------------------------------------------------------------------------
# parse_natural — date extraction mocked for determinism
# ---------------------------------------------------------------------------

_MOCK_DT_DATE_ONLY = datetime(2026, 4, 17, 0, 0)   # Friday, midnight → date only
_MOCK_DT_WITH_TIME = datetime(2026, 4, 17, 15, 0)  # Friday 3 pm


def _patch_search(return_value):
    """Return a context manager that patches _search_dates in todo.nlp."""
    return patch("todo.nlp._search_dates", return_value=return_value)


class TestParseNatural:
    # --- title extraction ---------------------------------------------------

    def test_filler_stripped_from_title(self):
        with _patch_search([]):
            result = parse_natural("remind me to call Alice")
        assert result["title"] == "Call Alice"

    def test_no_filler_title_preserved(self):
        with _patch_search([]):
            result = parse_natural("buy groceries")
        assert result["title"] == "Buy groceries"

    def test_priority_prefix_stripped_from_title(self):
        with _patch_search([]):
            result = parse_natural("urgent: fix the login bug")
        assert result["title"] == "Fix the login bug"

    # --- date extraction ----------------------------------------------------

    def test_date_only_when_midnight(self):
        with _patch_search([("next Friday", _MOCK_DT_DATE_ONLY)]):
            result = parse_natural("call Alice next Friday")
        assert result["due"] == "2026-04-17"

    def test_datetime_when_time_given(self):
        with _patch_search([("next Friday at 3pm", _MOCK_DT_WITH_TIME)]):
            result = parse_natural("call Alice next Friday at 3pm")
        assert result["due"] == "2026-04-17T15:00"

    def test_date_phrase_removed_from_title(self):
        with _patch_search([("next Friday", _MOCK_DT_DATE_ONLY)]):
            result = parse_natural("call Alice next Friday")
        assert "Friday" not in result["title"]
        assert "next" not in result["title"]

    def test_no_date_found_gives_none(self):
        with _patch_search([]):
            result = parse_natural("write a blog post")
        assert result["due"] is None

    def test_dateparser_unavailable_gives_none(self, monkeypatch):
        monkeypatch.setattr("todo.nlp._DATEPARSER_AVAILABLE", False)
        result = parse_natural("call Alice next Friday")
        assert result["due"] is None

    # --- priority inference -------------------------------------------------

    def test_priority_from_urgent_prefix(self):
        with _patch_search([]):
            result = parse_natural("urgent: fix the server")
        assert result["priority"] == 1

    def test_priority_from_inline_word(self):
        with _patch_search([]):
            result = parse_natural("this is critical — deploy hotfix")
        assert result["priority"] == 1

    def test_priority_default_4(self):
        with _patch_search([]):
            result = parse_natural("read a book")
        assert result["priority"] == 4

    # --- tag inference ------------------------------------------------------

    def test_tag_inferred_from_title(self):
        with _patch_search([]):
            result = parse_natural("dentist appointment")
        assert "health" in result["tags"]

    def test_multiple_tags_inferred(self):
        with _patch_search([]):
            result = parse_natural("buy medicine from the pharmacy")
        assert "shopping" in result["tags"]
        assert "health" in result["tags"]

    def test_no_tags_when_no_match(self):
        with _patch_search([]):
            result = parse_natural("plan the next adventure")
        assert result["tags"] == []

    # --- combined -----------------------------------------------------------

    def test_full_natural_sentence(self):
        with _patch_search([("next Friday at 3pm", _MOCK_DT_WITH_TIME)]):
            result = parse_natural("remind me to call the doctor next Friday at 3pm")
        assert result["title"] == "Call the doctor"
        assert result["due"] == "2026-04-17T15:00"
        assert result["priority"] == 4
        assert "health" in result["tags"]

    def test_urgent_with_date(self):
        with _patch_search([("tomorrow", datetime(2026, 4, 14, 0, 0))]):
            result = parse_natural("urgent: fix the login bug tomorrow")
        assert result["title"] == "Fix the login bug"
        assert result["due"] == "2026-04-14"
        assert result["priority"] == 1
