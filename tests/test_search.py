"""Tests for todo.search — search_tasks scoring and ranking."""

import json
import pytest
from click.testing import CliRunner

from todo.cli import cli, SCHEMA_VERSION
from todo.models import Task
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
# _tokens
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


# ---------------------------------------------------------------------------
# _field_score (keyword helper — still exported for backward compat)
# ---------------------------------------------------------------------------

class TestFieldScore:
    def test_single_match(self):
        assert _field_score("buy groceries", ["groceries"]) == 1

    def test_multiple_tokens_all_match(self):
        assert _field_score("buy fresh milk", ["buy", "milk"]) == 2

    def test_partial_token_counts(self):
        # "grocer" is a substring of "groceries"
        assert _field_score("buy groceries", ["grocer"]) == 1

    def test_no_match_returns_zero(self):
        assert _field_score("call dentist", ["milk"]) == 0

    def test_case_insensitive(self):
        assert _field_score("Call Dentist", ["dentist"]) == 1


# ---------------------------------------------------------------------------
# _levenshtein
# ---------------------------------------------------------------------------

class TestLevenshtein:
    def test_identical_strings_zero(self):
        assert _levenshtein("meeting", "meeting") == 0

    def test_empty_vs_string(self):
        assert _levenshtein("", "abc") == 3

    def test_single_substitution(self):
        # "cat" → "bat": one substitution
        assert _levenshtein("cat", "bat") == 1

    def test_typo_transposition(self):
        # "meeitng" vs "meeting": positions 4-5 are swapped (i↔t),
        # which costs 2 ops in standard Levenshtein (no transposition primitive)
        assert _levenshtein("meeitng", "meeting") == 2

    def test_completely_different(self):
        assert _levenshtein("abc", "xyz") == 3


# ---------------------------------------------------------------------------
# search_tasks — common behaviour across modes
# ---------------------------------------------------------------------------

class TestSearchTasksCommon:
    def test_empty_query_returns_empty(self):
        tasks = [_task(title="Anything", id="aaa00001")]
        assert search_tasks("", tasks) == []

    def test_returns_search_result_objects(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("milk", tasks)
        assert isinstance(results[0], SearchResult)

    def test_score_is_float_between_0_and_1(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("milk", tasks)
        assert isinstance(results[0].score, float)
        assert 0.0 <= results[0].score <= 1.0

    def test_matched_fields_is_list(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("milk", tasks)
        assert isinstance(results[0].matched_fields, list)

    def test_sorted_by_score_descending(self):
        # "Buy fresh milk" shares both query tokens; "Buy something" shares one
        t_high = _task(title="Buy fresh milk", id="aaa00001")
        t_low  = _task(title="Buy something",  id="bbb00002")
        results = search_tasks("buy milk", [t_low, t_high])
        assert results[0].task.id == "aaa00001"

    def test_done_tasks_still_searchable(self):
        tasks = [_task(title="Done task", id="aaa00001", done=True)]
        results = search_tasks("done", tasks)
        assert len(results) == 1

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode must be one of"):
            search_tasks("milk", [], mode="typo_mode")


# ---------------------------------------------------------------------------
# similar mode (Jaccard, default)
# ---------------------------------------------------------------------------

class TestSimilarMode:
    def test_title_match(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("milk", tasks)  # default mode = similar
        assert len(results) == 1
        assert results[0].task.id == "aaa00001"

    def test_no_common_tokens_excluded(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("dentist", tasks)
        assert results == []

    def test_case_insensitive(self):
        tasks = [_task(title="Buy Milk", id="aaa00001")]
        results = search_tasks("MILK", tasks, mode="similar")
        assert len(results) == 1

    def test_score_is_jaccard(self):
        # query {"milk"}, title {"buy","milk"}: Jaccard = 1/2 = 0.5
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("milk", tasks, mode="similar")
        assert abs(results[0].score - 0.5) < 0.01

    def test_more_overlap_scores_higher(self):
        # query {"buy","milk"}: "Buy fresh milk" ∩ = 2, union = 3 → 0.667
        #                       "Buy eggs"       ∩ = 1, union = 3 → 0.333
        t1 = _task(title="Buy fresh milk", id="aaa00001")
        t2 = _task(title="Buy eggs",       id="bbb00002")
        results = search_tasks("buy milk", [t1, t2], mode="similar")
        assert results[0].task.id == "aaa00001"

    def test_below_threshold_excluded(self):
        # threshold 0.2: single-token query matching one word in a long title
        # "a" vs a 10-word title → Jaccard will be 1/10 = 0.1 < 0.2
        tasks = [_task(title="one two three four five six seven eight nine ten")]
        results = search_tasks("a", tasks, mode="similar")
        assert results == []

    def test_multiple_matches_all_returned(self):
        tasks = [
            _task(title="Call dentist", id="aaa00001"),
            _task(title="Dentist appointment", id="bbb00002"),
        ]
        results = search_tasks("dentist", tasks, mode="similar")
        assert len(results) == 2

    def test_title_in_matched_fields(self):
        tasks = [_task(title="Fix bug", id="aaa00001")]
        results = search_tasks("bug", tasks, mode="similar")
        assert "title" in results[0].matched_fields

    def test_due_match_included(self):
        tasks = [_task(title="Something", id="aaa00001", due="2026-04-15")]
        results = search_tasks("2026-04-15", tasks, mode="similar")
        assert len(results) == 1
        assert "due" in results[0].matched_fields

    def test_due_only_match_has_high_score(self):
        # Title has no overlap with "2026-04"; due matches exactly
        tasks = [_task(title="Something unrelated", id="aaa00001", due="2026-04-15")]
        results = search_tasks("2026-04", tasks, mode="similar")
        assert len(results) == 1
        assert results[0].score >= 0.8

    def test_both_title_and_due_match_boosts_score(self):
        # title and due both match; score should be higher than title alone
        t_both = _task(title="April reminder",  id="aaa00001", due="2026-04-15")
        t_title = _task(title="April reminder", id="bbb00002", due=None)
        r_both  = search_tasks("april", [t_both],  mode="similar")[0]
        r_title = search_tasks("april", [t_title], mode="similar")[0]
        assert r_both.score >= r_title.score


# ---------------------------------------------------------------------------
# exact mode (case-insensitive substring)
# ---------------------------------------------------------------------------

class TestExactMode:
    def test_substring_match(self):
        tasks = [_task(title="Buy milk today", id="aaa00001")]
        results = search_tasks("milk", tasks, mode="exact")
        assert len(results) == 1

    def test_no_substring_excluded(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("dentist", tasks, mode="exact")
        assert results == []

    def test_case_insensitive(self):
        tasks = [_task(title="Buy Milk", id="aaa00001")]
        results = search_tasks("MILK", tasks, mode="exact")
        assert len(results) == 1

    def test_partial_word_matches(self):
        # "grocer" is a substring of "groceries"
        tasks = [_task(title="Buy groceries", id="aaa00001")]
        results = search_tasks("grocer", tasks, mode="exact")
        assert len(results) == 1

    def test_score_is_1_for_match(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("milk", tasks, mode="exact")
        assert results[0].score == 1.0

    def test_due_exact_match(self):
        tasks = [_task(title="Something", id="aaa00001", due="2026-05-15")]
        # Partial date string matches due
        results = search_tasks("2026-05", tasks, mode="exact")
        assert len(results) == 1
        assert "due" in results[0].matched_fields

    def test_multi_word_query_as_phrase(self):
        # Exact mode matches the whole query as a phrase
        tasks = [
            _task(title="Team meeting today", id="aaa00001"),
            _task(title="Cancel meeting",     id="bbb00002"),
        ]
        results = search_tasks("team meeting", tasks, mode="exact")
        assert len(results) == 1
        assert results[0].task.id == "aaa00001"


# ---------------------------------------------------------------------------
# fuzzy mode (edit-distance)
# ---------------------------------------------------------------------------

class TestFuzzyMode:
    def test_exact_title_match(self):
        tasks = [_task(title="Team meeting", id="aaa00001")]
        results = search_tasks("meeting", tasks, mode="fuzzy")
        assert len(results) == 1

    def test_single_char_typo(self):
        # "meeitng" → "meeting": Levenshtein distance 1 out of 7 chars → 0.857
        tasks = [_task(title="Team meeting", id="aaa00001")]
        results = search_tasks("meeitng", tasks, mode="fuzzy")
        assert len(results) == 1

    def test_score_reflects_similarity(self):
        # Exact query word should score higher than a typo
        tasks = [
            _task(title="Team meeting", id="aaa00001"),
            _task(title="Team meeXing", id="bbb00002"),
        ]
        r_exact = search_tasks("meeting", [tasks[0]], mode="fuzzy")[0]
        r_typo  = search_tasks("meeting", [tasks[1]], mode="fuzzy")[0]
        assert r_exact.score >= r_typo.score

    def test_completely_unrelated_excluded(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("xyz", tasks, mode="fuzzy")
        # "xyz" vs "buy","milk": max similarity is low → excluded
        assert results == []

    def test_case_insensitive(self):
        tasks = [_task(title="Buy Milk", id="aaa00001")]
        results = search_tasks("MILK", tasks, mode="fuzzy")
        assert len(results) == 1

    def test_score_range(self):
        tasks = [_task(title="Meeting notes", id="aaa00001")]
        results = search_tasks("meeitng", tasks, mode="fuzzy")
        assert len(results) == 1
        assert 0.0 < results[0].score <= 1.0

    def test_due_exact_match_included(self):
        tasks = [_task(title="Something", id="aaa00001", due="2026-05-15")]
        results = search_tasks("2026-05-15", tasks, mode="fuzzy")
        assert len(results) == 1
        assert "due" in results[0].matched_fields


# ---------------------------------------------------------------------------
# JSON output shape
# ---------------------------------------------------------------------------

class TestJsonOutput:
    def test_score_is_float(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001", tags=["health"]))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        data = _unwrap(result.output)
        assert isinstance(data[0]["score"], float)

    def test_matched_fields_present(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001", tags=[]))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        data = _unwrap(result.output)
        assert "matched_fields" in data[0]
        assert isinstance(data[0]["matched_fields"], list)

    def test_task_object_present(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001", tags=[]))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        data = _unwrap(result.output)
        assert data[0]["task"]["id"] == "aaa00001"

    def test_results_sorted_highest_first(self, runner):
        add_task(Task(title="Urgent meeting today", id="aaa00001", tags=[]))
        add_task(Task(title="Meeting later",        id="bbb00002", tags=[]))
        result = runner.invoke(cli, ["search", "urgent meeting", "--json"])
        data = _unwrap(result.output)
        assert data[0]["task"]["id"] == "aaa00001"
        scores = [r["score"] for r in data]
        assert scores == sorted(scores, reverse=True)

    def test_no_score_in_text_output(self, runner):
        add_task(Task(title="Buy milk", id="aaa00001", tags=[]))
        result = runner.invoke(cli, ["search", "milk"])
        assert "score" not in result.output
        assert "matched_fields" not in result.output


# ---------------------------------------------------------------------------
# CLI integration — mode flag and filters
# ---------------------------------------------------------------------------

class TestSearchCommand:
    def test_basic_search_finds_match(self, runner):
        add_task(Task(title="Buy milk", id="aaa00001", tags=[]))
        result = runner.invoke(cli, ["search", "milk"])
        assert result.exit_code == 0
        assert "aaa00001" in result.output

    def test_no_match_exits_3(self, runner):
        add_task(Task(title="Buy milk", id="aaa00001", tags=[]))
        result = runner.invoke(cli, ["search", "dentist"])
        assert result.exit_code == 3

    def test_mode_similar_is_default(self, runner):
        add_task(Task(title="Team meeting", id="aaa00001", tags=[]))
        r1 = runner.invoke(cli, ["search", "meeting", "--json"])
        r2 = runner.invoke(cli, ["search", "meeting", "--mode", "similar", "--json"])
        assert r1.output == r2.output

    def test_mode_exact(self, runner):
        add_task(Task(title="Team meeting", id="aaa00001", tags=[]))
        add_task(Task(title="Unrelated",    id="bbb00002", tags=[]))
        result = runner.invoke(cli, ["search", "meeting", "--mode", "exact", "--json"])
        data = _unwrap(result.output)
        assert len(data) == 1
        assert data[0]["task"]["id"] == "aaa00001"

    def test_mode_fuzzy_tolerates_typo(self, runner):
        add_task(Task(title="Team meeting", id="aaa00001", tags=[]))
        result = runner.invoke(cli, ["search", "meeitng", "--mode", "fuzzy", "--json"])
        data = _unwrap(result.output)
        assert any(r["task"]["id"] == "aaa00001" for r in data)

    def test_filter_by_tag(self, runner):
        add_task(Task(title="Work meeting",     id="aaa00001", tags=["work"]))
        add_task(Task(title="Personal meeting", id="bbb00002", tags=["personal"]))
        result = runner.invoke(cli, ["search", "meeting", "--tag", "work", "--json"])
        data = _unwrap(result.output)
        assert len(data) == 1
        assert data[0]["task"]["id"] == "aaa00001"

    def test_filter_by_priority(self, runner):
        add_task(Task(title="Urgent meeting", id="aaa00001", priority=1))
        add_task(Task(title="Normal meeting", id="bbb00002", priority=4))
        result = runner.invoke(cli, ["search", "meeting", "--priority", "1", "--json"])
        data = _unwrap(result.output)
        assert len(data) == 1
        assert data[0]["task"]["id"] == "aaa00001"

    def test_archive_flag_includes_done_tasks(self, runner):
        task = Task(title="Old meeting", id="arc00001", tags=[])
        add_task(task)
        runner.invoke(cli, ["done", "arc00001"])
        # Without --archive: not found
        r1 = runner.invoke(cli, ["search", "old meeting"])
        assert r1.exit_code == 3
        # With --archive: found
        r2 = runner.invoke(cli, ["search", "old meeting", "--archive"])
        assert r2.exit_code == 0
        assert "arc00001" in r2.output

    def test_due_match_in_json(self, runner):
        add_task(Task(title="Something unrelated", id="aaa00001", due="2026-05-20"))
        result = runner.invoke(cli, ["search", "2026-05", "--mode", "exact", "--json"])
        data = _unwrap(result.output)
        assert len(data) == 1
        assert "due" in data[0]["matched_fields"]
