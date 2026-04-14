"""Tests for todo.search — search_tasks scoring and ranking."""

import pytest
from todo.models import Task
from todo.search import search_tasks, _tokens, _field_score, SearchResult


def _task(**kwargs) -> Task:
    defaults = dict(title="Generic task", id="aaa00001")
    defaults.update(kwargs)
    return Task(**defaults)


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
# _field_score
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
# search_tasks — scoring
# ---------------------------------------------------------------------------

class TestSearchTasks:
    def test_empty_query_returns_empty(self):
        tasks = [_task(title="Anything", id="aaa00001")]
        assert search_tasks("", tasks) == []

    def test_no_match_returns_empty(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        assert search_tasks("dentist", tasks) == []

    def test_title_match_returns_result(self):
        tasks = [_task(title="Buy milk", id="aaa00001")]
        results = search_tasks("milk", tasks)
        assert len(results) == 1
        assert results[0].task.id == "aaa00001"

    def test_title_has_higher_weight_than_tag(self):
        # "dentist" in title (×3) vs "dentist" only in tag (×2)
        t_title = _task(title="Dentist appointment", id="aaa00001")
        t_tag   = _task(title="Health checkup", id="bbb00002", tags=["dentist"])
        results = search_tasks("dentist", [t_title, t_tag])
        assert results[0].task.id == "aaa00001"

    def test_tag_match(self):
        tasks = [_task(title="Random task", id="aaa00001", tags=["work"])]
        results = search_tasks("work", tasks)
        assert len(results) == 1
        assert "tags" in results[0].matched_fields

    def test_due_match(self):
        tasks = [_task(title="Something", id="aaa00001", due="2026-04-15")]
        results = search_tasks("2026-04-15", tasks)
        assert len(results) == 1
        assert "due" in results[0].matched_fields

    def test_recur_match(self):
        tasks = [_task(title="Something", id="aaa00001", recur="weekly")]
        results = search_tasks("weekly", tasks)
        assert len(results) == 1
        assert "recur" in results[0].matched_fields

    def test_context_match(self):
        tasks = [_task(title="Something", id="aaa00001", contexts=["errand"])]
        results = search_tasks("errand", tasks)
        assert len(results) == 1
        assert "contexts" in results[0].matched_fields

    def test_case_insensitive(self):
        tasks = [_task(title="Buy Milk", id="aaa00001")]
        results = search_tasks("MILK", tasks)
        assert len(results) == 1

    def test_sorted_by_score_descending(self):
        # Two title words match → higher score
        t_high = _task(title="Buy fresh milk", id="aaa00001")
        # One word matches
        t_low  = _task(title="Buy something", id="bbb00002")
        results = search_tasks("buy milk", [t_low, t_high])
        assert results[0].task.id == "aaa00001"

    def test_multiple_matches_all_returned(self):
        tasks = [
            _task(title="Call dentist", id="aaa00001"),
            _task(title="Dentist appointment", id="bbb00002"),
        ]
        results = search_tasks("dentist", tasks)
        assert len(results) == 2

    def test_matched_fields_reported(self):
        tasks = [_task(title="Fix bug", id="aaa00001", tags=["work"])]
        results = search_tasks("bug", tasks)
        assert "title" in results[0].matched_fields

    def test_score_gt_zero_required(self):
        tasks = [
            _task(title="Match this", id="aaa00001"),
            _task(title="No relation", id="bbb00002"),
        ]
        results = search_tasks("match", tasks)
        assert all(r.score > 0 for r in results)
        assert len(results) == 1

    def test_multi_word_query(self):
        tasks = [
            _task(title="Buy fresh milk", id="aaa00001"),
            _task(title="Buy eggs", id="bbb00002"),
        ]
        results = search_tasks("fresh milk", tasks)
        # "fresh milk" only matches the first task on both tokens
        assert results[0].task.id == "aaa00001"

    def test_done_tasks_still_searchable(self):
        tasks = [_task(title="Done task", id="aaa00001", done=True)]
        results = search_tasks("done", tasks)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# search CLI integration
# ---------------------------------------------------------------------------

import json
import pytest
from click.testing import CliRunner
from todo.cli import cli
from todo.storage import add_task, archive_task


@pytest.fixture(autouse=True)
def isolated_todo_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TODO_DIR", str(tmp_path))


@pytest.fixture
def runner():
    return CliRunner()


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

    def test_json_output(self, runner):
        add_task(Task(title="Call dentist", id="aaa00001", tags=["health"]))
        result = runner.invoke(cli, ["search", "dentist", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["task"]["id"] == "aaa00001"
        assert "score" in data[0]
        assert "matched_fields" in data[0]

    def test_filter_by_tag(self, runner):
        add_task(Task(title="Work meeting", id="aaa00001", tags=["work"]))
        add_task(Task(title="Personal meeting", id="bbb00002", tags=["personal"]))
        result = runner.invoke(cli, ["search", "meeting", "--tag", "work", "--json"])
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["task"]["id"] == "aaa00001"

    def test_filter_by_priority(self, runner):
        add_task(Task(title="Urgent meeting", id="aaa00001", priority=1))
        add_task(Task(title="Normal meeting", id="bbb00002", priority=4))
        result = runner.invoke(cli, ["search", "meeting", "--priority", "1", "--json"])
        data = json.loads(result.output)
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

    def test_results_sorted_by_score(self, runner):
        # Both match "meeting" but first also matches "urgent"
        add_task(Task(title="Urgent meeting today", id="aaa00001", tags=[]))
        add_task(Task(title="Meeting later", id="bbb00002", tags=[]))
        result = runner.invoke(cli, ["search", "urgent meeting", "--json"])
        data = json.loads(result.output)
        assert data[0]["task"]["id"] == "aaa00001"
