"""Tests for todo.search — scoring, normalization, hint matching, and CLI."""

import json
import pytest
from click.testing import CliRunner

from todo.cli import cli, SCHEMA_VERSION
from todo.models import Task
from todo.query import normalize
from todo.search import (
    SearchResult,
    _field_score,
    _levenshtein,
    _tokens,
    search_tasks,
)
from todo.storage import add_task, archive_task


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _task(**kwargs) -> Task:
    defaults = dict(title="Generic task", id="aaa00001")
    defaults.update(kwargs)
    return Task(**defaults)


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


# ---------------------------------------------------------------------------
# _tokens (normalize-aware)
# ---------------------------------------------------------------------------

class TestTokens:
    def test_splits_on_whitespace(self):
        assert _tokens("buy milk") == ["buy", "milk"]

    def test_splits_on_comma(self):
        assert _tokens("buy,milk") == ["buy", "milk"]

    def test_lowercases(self):
        assert _tokens("BUY MILK") == ["buy", "milk"]

    def test_filters_empty(self):
        assert _tokens("  buy   milk  ") == ["buy", "milk"]

    def test_empty_returns_empty(self):
        assert _tokens("") == []

    def test_normalizes_hyphen(self):
        # follow-up → followup (single token after normalize)
        assert _tokens("follow-up") == ["followup"]


# ---------------------------------------------------------------------------
# _field_score
# ---------------------------------------------------------------------------

class TestFieldScore:
    def test_single_match(self):
        assert _field_score("buy groceries", ["groceries"]) == 1

    def test_multiple_tokens_all_match(self):
        assert _field_score("buy fresh milk", ["buy", "milk"]) == 2

    def test_partial_token_counts(self):
        assert _field_score("buy groceries", ["grocer"]) == 1

    def test_no_match_returns_zero(self):
        assert _field_score("call dentist", ["milk"]) == 0

    def test_case_insensitive(self):
        assert _field_score("Call Dentist", ["dentist"]) == 1

    def test_normalized_hyphen(self):
        # "follow-up" is normalized to "followup", "followup" in query → match
        assert _field_score("Follow-up with vendor", ["followup"]) == 1


# ---------------------------------------------------------------------------
# _levenshtein
# ---------------------------------------------------------------------------

class TestLevenshtein:
    def test_identical_strings_zero(self):
        assert _levenshtein("meeting", "meeting") == 0

    def test_empty_vs_string(self):
        assert _levenshtein("", "abc") == 3

    def test_single_substitution(self):
        assert _levenshtein("cat", "bat") == 1

    def test_typo_transposition(self):
        # "meeitng" vs "meeting": two ops (swap i and t)
        assert _levenshtein("meeitng", "meeting") == 2

    def test_completely_different(self):
        assert _levenshtein("abc", "xyz") == 3


# ---------------------------------------------------------------------------
# Normalization — bidirectional matching
# ---------------------------------------------------------------------------

class TestNormalizationInSearch:
    """All modes normalize both query and task text before comparing."""

    def test_similar_followup_matches_hyphenated(self):
        tasks = [_task(title="Follow-up with vendor", id="aaa00001")]
        results = search_tasks("followup", tasks, mode="similar")
        assert len(results) == 1, "normalized 'followup' should match 'Follow-up'"

    def test_similar_hyphenated_matches_plain(self):
        tasks = [_task(title="Followup with vendor", id="aaa00001")]
        results = search_tasks("follow-up", tasks, mode="similar")
        assert len(results) == 1, "normalized 'follow-up' should match 'Followup'"

    def test_exact_email_matches_hyphenated(self):
        tasks = [_task(title="Send e-mail to client", id="aaa00001")]
        results = search_tasks("email", tasks, mode="exact")
        assert len(results) == 1

    def test_fuzzy_normalized_before_edit_distance(self):
        # After normalization follow-up → followup, so it's effectively exact
        tasks = [_task(title="Follow-up call", id="aaa00001")]
        results = search_tasks("followup", tasks, mode="fuzzy")
        assert len(results) == 1

    def test_case_insensitive_all_modes(self):
        tasks = [_task(title="BUY MILK", id="aaa00001")]
        for m in ("similar", "fuzzy", "exact"):
            assert search_tasks("milk", tasks, mode=m), f"mode={m} should match"


# ---------------------------------------------------------------------------
# search_tasks — common behaviour across modes
# ---------------------------------------------------------------------------

class TestSearchTasksCommon:
    def test_empty_query_returns_empty(self):
        tasks = [_task(title="Anything")]
        assert search_tasks("", tasks) == []

    def test_returns_search_result_objects(self):
        tasks = [_task(title="Buy milk")]
        results = search_tasks("milk", tasks)
        assert isinstance(results[0], SearchResult)

    def test_score_is_float_between_0_and_1(self):
        tasks = [_task(title="Buy milk")]
        results = search_tasks("milk", tasks)
        assert isinstance(results[0].score, float)
        assert 0.0 <= results[0].score <= 1.0

    def test_sorted_by_score_descending(self):
        t_high = _task(title="Buy fresh milk", id="aaa00001")
        t_low  = _task(title="Buy something",  id="bbb00002")
        results = search_tasks("buy milk", [t_low, t_high])
        assert results[0].task.id == "aaa00001"

    def test_done_tasks_still_searchable(self):
        tasks = [_task(title="Done task", done=True)]
        results = search_tasks("done", tasks)
        assert len(results) == 1

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode must be one of"):
            search_tasks("milk", [], mode="magic")

    def test_no_hints_disables_tag_matching(self):
        # Without hints=, tag matching is disabled (backward compat)
        tasks = [_task(title="Unrelated title", id="aaa00001", tags=["work"])]
        results = search_tasks("work", tasks, mode="similar", hints=None)
        # "work" has no token overlap with "unrelated title" in similar mode
        assert all(r.task.id != "aaa00001" or "tag" not in r.matched_fields
                   for r in results)


# ---------------------------------------------------------------------------
# similar mode (Jaccard + normalization)
# ---------------------------------------------------------------------------

class TestSimilarMode:
    def test_title_match(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("milk", tasks)
        assert len(results) == 1

    def test_no_common_tokens_excluded(self):
        tasks = [_task(title="Buy milk")]
        results = search_tasks("dentist", tasks)
        assert results == []

    def test_case_insensitive(self):
        tasks = [_task(title="Buy Milk")]
        assert len(search_tasks("MILK", tasks, mode="similar")) == 1

    def test_score_is_jaccard(self):
        tasks = [_task(title="Buy milk")]
        results = search_tasks("milk", tasks, mode="similar")
        assert abs(results[0].score - 0.5) < 0.01

    def test_more_overlap_scores_higher(self):
        t1 = _task(title="Buy fresh milk", id="aaa00001")
        t2 = _task(title="Buy eggs",       id="bbb00002")
        results = search_tasks("buy milk", [t1, t2], mode="similar")
        assert results[0].task.id == "aaa00001"

    def test_multiple_matches_all_returned(self):
        tasks = [
            _task(title="Call dentist",       id="aaa00001"),
            _task(title="Dentist appointment", id="bbb00002"),
        ]
        results = search_tasks("dentist", tasks, mode="similar")
        assert len(results) == 2

    def test_title_in_matched_fields(self):
        tasks = [_task(title="Fix bug")]
        results = search_tasks("bug", tasks, mode="similar")
        assert "title" in results[0].matched_fields

    def test_due_match_included(self):
        tasks = [_task(title="Something", due="2026-04-15")]
        results = search_tasks("2026-04-15", tasks, mode="similar")
        assert len(results) == 1
        assert "due" in results[0].matched_fields

    def test_due_only_match_high_score(self):
        tasks = [_task(title="Something unrelated", due="2026-04-15")]
        results = search_tasks("2026-04", tasks, mode="similar")
        assert len(results) == 1
        assert results[0].score >= 0.8

    def test_both_title_and_due_boosts_score(self):
        t_both  = _task(title="April reminder", id="aaa00001", due="2026-04-15")
        t_title = _task(title="April reminder", id="bbb00002")
        r_both  = search_tasks("april", [t_both],  mode="similar")[0]
        r_title = search_tasks("april", [t_title], mode="similar")[0]
        assert r_both.score >= r_title.score


# ---------------------------------------------------------------------------
# exact mode
# ---------------------------------------------------------------------------

class TestExactMode:
    def test_substring_match(self):
        tasks = [_task(title="Buy milk today")]
        assert len(search_tasks("milk", tasks, mode="exact")) == 1

    def test_no_substring_excluded(self):
        tasks = [_task(title="Buy milk")]
        assert search_tasks("dentist", tasks, mode="exact") == []

    def test_case_insensitive(self):
        tasks = [_task(title="Buy Milk")]
        assert len(search_tasks("MILK", tasks, mode="exact")) == 1

    def test_score_is_1_for_match(self):
        tasks = [_task(title="Buy milk")]
        results = search_tasks("milk", tasks, mode="exact")
        assert results[0].score == 1.0

    def test_due_exact_match(self):
        tasks = [_task(title="Something", due="2026-05-15")]
        results = search_tasks("2026-05", tasks, mode="exact")
        assert "due" in results[0].matched_fields

    def test_phrase_match(self):
        tasks = [
            _task(title="Team meeting today", id="aaa00001"),
            _task(title="Cancel meeting",     id="bbb00002"),
        ]
        results = search_tasks("team meeting", tasks, mode="exact")
        assert len(results) == 1
        assert results[0].task.id == "aaa00001"

    def test_normalized_hyphen_exact(self):
        tasks = [_task(title="Follow-up with vendor", id="aaa00001")]
        results = search_tasks("followup", tasks, mode="exact")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# fuzzy mode (edit-distance)
# ---------------------------------------------------------------------------

class TestFuzzyMode:
    def test_exact_match(self):
        tasks = [_task(title="Team meeting")]
        assert len(search_tasks("meeting", tasks, mode="fuzzy")) == 1

    def test_single_char_typo(self):
        tasks = [_task(title="Team meeting")]
        results = search_tasks("meeitng", tasks, mode="fuzzy")
        assert len(results) == 1

    def test_completely_unrelated_excluded(self):
        tasks = [_task(title="Buy milk")]
        assert search_tasks("xyz", tasks, mode="fuzzy") == []

    def test_case_insensitive(self):
        tasks = [_task(title="Buy Milk")]
        assert len(search_tasks("MILK", tasks, mode="fuzzy")) == 1

    def test_score_range(self):
        tasks = [_task(title="Meeting notes")]
        results = search_tasks("meeitng", tasks, mode="fuzzy")
        assert 0.0 < results[0].score <= 1.0

    def test_due_exact_match_included(self):
        tasks = [_task(title="Something", due="2026-05-15")]
        results = search_tasks("2026-05-15", tasks, mode="fuzzy")
        assert "due" in results[0].matched_fields

    def test_normalized_before_fuzzy(self):
        # After normalization follow-up → followup; fuzzy on normalized text
        tasks = [_task(title="Follow-up call")]
        results = search_tasks("followup", tasks, mode="fuzzy")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Hint matching (additive field matching)
# ---------------------------------------------------------------------------

class TestHintMatching:
    """hints= enables additive tag/section/priority/due matching."""

    def test_tag_hint_includes_tagged_task(self):
        tasks = [_task(title="Unrelated", id="aaa00001", tags=["work"])]
        results = search_tasks("work", tasks, mode="similar", hints={})
        assert any(r.task.id == "aaa00001" for r in results)

    def test_tag_in_matched_fields(self):
        tasks = [_task(title="Unrelated", tags=["work"])]
        results = search_tasks("work", tasks, mode="similar", hints={})
        r = results[0]
        assert "tag" in r.matched_fields

    def test_both_title_and_tag_results_returned(self):
        # A tag-only match (0.7) can outscore a poor title match (0.5 Jaccard),
        # which is fine — explicit categorisation is high-confidence.
        # Verify both tasks are returned with the right matched_fields.
        t_title = _task(title="Work task",  id="aaa00001")
        t_tag   = _task(title="Unrelated", id="bbb00002", tags=["work"])
        results = search_tasks("work", [t_title, t_tag], mode="similar", hints={})
        fields = {r.task.id: r.matched_fields for r in results}
        assert "title" in fields["aaa00001"]
        assert "tag"   in fields["bbb00002"]

    def test_section_hint(self):
        tasks = [
            _task(title="Vendor call", id="aaa00001", section="waiting"),
            _task(title="Buy eggs",    id="bbb00002", section="inbox"),
        ]
        hints = {"maybe_sections": ["waiting"]}
        results = search_tasks("waiting vendor", tasks, mode="similar", hints=hints)
        ids = {r.task.id for r in results}
        # aaa00001 matches "vendor" in title AND section hint
        assert "aaa00001" in ids

    def test_priority_hint(self):
        tasks = [
            _task(title="High task",  id="aaa00001", priority=1),
            _task(title="Low task",   id="bbb00002", priority=4),
        ]
        hints = {"maybe_priorities": [1]}
        results = search_tasks("high priority", tasks, mode="similar", hints=hints)
        ids = {r.task.id for r in results}
        assert "aaa00001" in ids

    def test_due_hint(self):
        from datetime import date, timedelta
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        tasks = [
            _task(title="Something", id="aaa00001", due=tomorrow),
            _task(title="Something", id="bbb00002", due=None),
        ]
        hints = {"maybe_due": [tomorrow]}
        results = search_tasks("tomorrow", tasks, mode="similar", hints=hints)
        ids = {r.task.id for r in results}
        assert "aaa00001" in ids

    def test_hint_only_match_score_is_0_7(self):
        # Task title has no overlap with query; only tag matches
        tasks = [_task(title="XYZ irrelevant", tags=["work"])]
        results = search_tasks("work", tasks, mode="similar", hints={})
        assert results[0].score == pytest.approx(0.7)

    def test_no_hints_excludes_tag_only_task(self):
        tasks = [_task(title="Unrelated", tags=["work"])]
        results = search_tasks("work", tasks, mode="similar", hints=None)
        # similar mode: Jaccard("work", "unrelated") = 0 → excluded
        assert results == []


# ---------------------------------------------------------------------------
# JSON output shape (new structure)
# ---------------------------------------------------------------------------

class TestJsonOutput:
    def test_envelope_has_match_mode(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001"))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        data = _unwrap(result.output)
        assert "match_mode" in data

    def test_envelope_has_resolved_filters(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001"))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        data = _unwrap(result.output)
        assert "resolved_filters" in data

    def test_envelope_has_residual_query(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001"))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        data = _unwrap(result.output)
        assert "residual_query" in data

    def test_results_is_a_list(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001"))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        data = _unwrap(result.output)
        assert isinstance(data["results"], list)

    def test_result_has_score_float(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001"))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        data = _unwrap(result.output)
        assert isinstance(data["results"][0]["score"], float)

    def test_result_has_matched_fields(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001"))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        data = _unwrap(result.output)
        assert isinstance(data["results"][0]["matched_fields"], list)

    def test_result_has_task(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001"))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        data = _unwrap(result.output)
        assert data["results"][0]["task"]["id"] == "aaa00001"

    def test_results_sorted_highest_first(self, runner):
        add_task(Task(title="Urgent meeting today", id="aaa00001"))
        add_task(Task(title="Meeting later",        id="bbb00002"))
        result = runner.invoke(cli, ["search", "urgent meeting", "--json"])
        data = _unwrap(result.output)
        assert data["results"][0]["task"]["id"] == "aaa00001"
        scores = [r["score"] for r in data["results"]]
        assert scores == sorted(scores, reverse=True)

    def test_no_score_in_text_output(self, runner):
        add_task(Task(title="Buy milk", id="aaa00001"))
        result = runner.invoke(cli, ["search", "milk"])
        assert "score" not in result.output
        assert "matched_fields" not in result.output


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestSearchCommand:
    def test_basic_search_finds_match(self, runner):
        add_task(Task(title="Buy milk", id="aaa00001"))
        result = runner.invoke(cli, ["search", "milk"])
        assert result.exit_code == 0
        assert "aaa00001" in result.output

    def test_no_match_exits_3(self, runner):
        add_task(Task(title="Buy milk", id="aaa00001"))
        result = runner.invoke(cli, ["search", "dentist"])
        assert result.exit_code == 3

    def test_mode_similar_is_default(self, runner):
        add_task(Task(title="Team meeting", id="aaa00001"))
        r1 = runner.invoke(cli, ["search", "meeting", "--json"])
        r2 = runner.invoke(cli, ["search", "meeting", "--mode", "similar", "--json"])
        assert r1.output == r2.output

    def test_mode_exact(self, runner):
        add_task(Task(title="Team meeting", id="aaa00001"))
        add_task(Task(title="Unrelated",    id="bbb00002"))
        result = runner.invoke(cli, ["search", "meeting", "--mode", "exact", "--json"])
        data = _unwrap(result.output)
        assert len(data["results"]) == 1
        assert data["results"][0]["task"]["id"] == "aaa00001"

    def test_mode_fuzzy_tolerates_typo(self, runner):
        add_task(Task(title="Team meeting", id="aaa00001"))
        result = runner.invoke(cli, ["search", "meeitng", "--mode", "fuzzy", "--json"])
        data = _unwrap(result.output)
        assert any(r["task"]["id"] == "aaa00001" for r in data["results"])

    def test_cli_tag_filter(self, runner):
        add_task(Task(title="Work meeting",     id="aaa00001", tags=["work"]))
        add_task(Task(title="Personal meeting", id="bbb00002", tags=["personal"]))
        result = runner.invoke(cli, ["search", "meeting", "--tag", "work", "--json"])
        data = _unwrap(result.output)
        assert len(data["results"]) == 1
        assert data["results"][0]["task"]["id"] == "aaa00001"

    def test_cli_priority_filter(self, runner):
        add_task(Task(title="Urgent meeting", id="aaa00001", priority=1))
        add_task(Task(title="Normal meeting", id="bbb00002", priority=4))
        result = runner.invoke(cli, ["search", "meeting", "--priority", "1", "--json"])
        data = _unwrap(result.output)
        assert len(data["results"]) == 1
        assert data["results"][0]["task"]["id"] == "aaa00001"

    def test_archive_flag_includes_done_tasks(self, runner):
        task = Task(title="Old meeting", id="arc00001")
        add_task(task)
        runner.invoke(cli, ["done", "arc00001"])
        r1 = runner.invoke(cli, ["search", "old meeting"])
        assert r1.exit_code == 3
        r2 = runner.invoke(cli, ["search", "old meeting", "--archive"])
        assert r2.exit_code == 0

    def test_due_match_in_json(self, runner):
        add_task(Task(title="Something unrelated", id="aaa00001", due="2026-05-20"))
        result = runner.invoke(cli, ["search", "2026-05", "--mode", "exact", "--json"])
        data = _unwrap(result.output)
        assert len(data["results"]) == 1
        assert "due" in data["results"][0]["matched_fields"]

    def test_query_tag_syntax_in_json(self, runner):
        add_task(Task(title="Work meeting", id="aaa00001", tags=["work"]))
        add_task(Task(title="Home task",    id="bbb00002", tags=["home"]))
        result = runner.invoke(cli, ["search", "@work meeting", "--json"])
        data = _unwrap(result.output)
        # resolved_filters should show tag was extracted
        assert data["resolved_filters"].get("tag") == "work"
        # residual_query should not contain @work
        assert "@work" not in data["residual_query"]

    def test_overdue_query_filter(self, runner):
        from datetime import date, timedelta
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow  = (date.today() + timedelta(days=1)).isoformat()
        add_task(Task(title="Old invoice", id="aaa00001", due=yesterday))
        add_task(Task(title="New invoice", id="bbb00002", due=tomorrow))
        result = runner.invoke(cli, ["search", "overdue invoice", "--json"])
        data = _unwrap(result.output)
        assert data["resolved_filters"].get("overdue") is True
        ids = {r["task"]["id"] for r in data["results"]}
        assert "aaa00001" in ids
        assert "bbb00002" not in ids

    def test_structured_query_residual_in_json(self, runner):
        add_task(Task(title="Vendor call", id="aaa00001", section="waiting"))
        result = runner.invoke(cli, ["search", "in waiting vendor", "--json"])
        data = _unwrap(result.output)
        assert data["resolved_filters"].get("section") == "waiting"
        assert "vendor" in data["residual_query"]

    def test_purely_structural_query_returns_all_filtered(self, runner):
        add_task(Task(title="Work A", id="aaa00001", tags=["work"]))
        add_task(Task(title="Work B", id="bbb00002", tags=["work"]))
        add_task(Task(title="Home",   id="ccc00003", tags=["home"]))
        result = runner.invoke(cli, ["search", "@work", "--json"])
        data = _unwrap(result.output)
        ids = {r["task"]["id"] for r in data["results"]}
        assert "aaa00001" in ids
        assert "bbb00002" in ids
        assert "ccc00003" not in ids
