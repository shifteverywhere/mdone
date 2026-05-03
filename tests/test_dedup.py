"""
Tests for deduplication: idempotency_key field, --dedup on add, --similar on search.
"""

import json
import pytest
from click.testing import CliRunner
from todo.cli import cli, SCHEMA_VERSION
from todo.storage import add_task, read_tasks
from todo.metadata import get_task_meta, read_all_meta
from todo.models import Task
from todo.dedup import _tokens, _jaccard, similar_tasks, find_by_idempotency_key, DEDUP_THRESHOLD


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


def _add(runner, task_string, extra_args=()):
    args = ["add", task_string, "--json"] + list(extra_args)
    result = runner.invoke(cli, args)
    assert result.exit_code == 0, result.output
    return _unwrap(result.output)


# ---------------------------------------------------------------------------
# Unit tests: dedup module
# ---------------------------------------------------------------------------

class TestTokens:
    def test_lowercases(self):
        assert "fix" in _tokens("Fix the Bug")

    def test_filters_short_words(self):
        assert "it" not in _tokens("do it now")

    def test_filters_stop_words(self):
        assert "the" not in _tokens("Fix the login bug")
        assert "and" not in _tokens("A and B")

    def test_returns_frozenset(self):
        assert isinstance(_tokens("hello world"), frozenset)

    def test_empty_string(self):
        assert _tokens("") == frozenset()


class TestJaccard:
    def test_identical_sets(self):
        s = frozenset({"fix", "login", "bug"})
        assert _jaccard(s, s) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard(frozenset({"fix"}), frozenset({"buy"})) == 0.0

    def test_partial_overlap(self):
        a = frozenset({"fix", "login", "bug"})
        b = frozenset({"fix", "login", "issue"})
        # intersection=2, union=4 → 0.5
        assert _jaccard(a, b) == 0.5

    def test_empty_sets(self):
        assert _jaccard(frozenset(), frozenset()) == 0.0


class TestSimilarTasks:
    def _task(self, title, tid="aaa00001"):
        return Task(title=title, id=tid)

    def test_identical_title_scores_1(self):
        t = self._task("Fix login bug")
        results = similar_tasks("Fix login bug", [t])
        assert results[0][0] == 1.0

    def test_disjoint_title_scores_0(self):
        t = self._task("Buy groceries")
        results = similar_tasks("Fix login bug", [t], threshold=0.0)
        assert results[0][0] == 0.0

    def test_threshold_filters(self):
        tasks = [
            self._task("Fix login bug", "aaa"),
            self._task("Buy groceries", "bbb"),
        ]
        results = similar_tasks("Fix login bug", tasks, threshold=0.5)
        ids = [t.id for _, t in results]
        assert "aaa" in ids
        assert "bbb" not in ids

    def test_sorted_descending(self):
        tasks = [
            self._task("Fix login issue", "aaa"),       # 2/4 = 0.5
            self._task("Fix login bug report", "bbb"),  # 2/5 = 0.4
            self._task("Fix login bug", "ccc"),          # identical = 1.0
        ]
        results = similar_tasks("Fix login bug", tasks, threshold=0.0)
        scores = [s for s, _ in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_query_returns_empty(self):
        t = self._task("Fix login bug")
        assert similar_tasks("", [t]) == []

    def test_empty_task_list(self):
        assert similar_tasks("Fix login bug", []) == []


class TestFindByIdempotencyKey:
    def test_finds_matching_task(self):
        tasks = [
            Task(title="A", id="aaa", idempotency_key="key-1"),
            Task(title="B", id="bbb", idempotency_key="key-2"),
        ]
        result = find_by_idempotency_key("key-1", tasks)
        assert result is not None
        assert result.id == "aaa"

    def test_returns_none_when_not_found(self):
        tasks = [Task(title="A", id="aaa", idempotency_key="key-1")]
        assert find_by_idempotency_key("key-99", tasks) is None

    def test_returns_none_on_empty_list(self):
        assert find_by_idempotency_key("key-1", []) is None


# ---------------------------------------------------------------------------
# idempotency_key field: parsing and storage
# ---------------------------------------------------------------------------

class TestIdempotencyKeyField:
    def test_flag_sets_key(self, runner):
        data = _add(runner, "Fix bug", extra_args=["--idempotency-key", "fix-bug-001"])
        assert data["idempotency_key"] == "fix-bug-001"

    def test_key_persisted_to_metadata(self, runner):
        result = _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        meta = get_task_meta(result["id"])
        assert meta.get("idempotency_key") == "key-001"

    def test_key_accessible_via_read_tasks(self, runner):
        _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        tasks = read_tasks()
        assert tasks[0].idempotency_key == "key-001"

    def test_key_null_by_default(self, runner):
        data = _add(runner, "Fix bug")
        assert data["idempotency_key"] is None

    def test_source_defaults_to_manual(self, runner):
        data = _add(runner, "Fix bug")
        assert data["source"] == "manual"

    def test_provenance_flags_stored(self, runner):
        result = _add(runner, "Fix bug", extra_args=[
            "--source", "slack",
            "--origin-id", "msg-001",
            "--origin-url", "https://example.com/msg/001",
            "--captured-at", "2026-05-03T10:00:00Z",
        ])
        assert result["source"] == "slack"
        assert result["origin_id"] == "msg-001"
        assert result["origin_url"] == "https://example.com/msg/001"
        assert result["captured_at"] == "2026-05-03T10:00:00Z"

    def test_provenance_immutable_after_edit(self, runner):
        data = _add(runner, "Fix bug", extra_args=["--source", "slack"])
        runner.invoke(cli, ["edit", data["id"], "--set", "priority:1"])
        meta = get_task_meta(data["id"])
        assert meta.get("source") == "slack"

    def test_edited_at_set_after_edit(self, runner):
        data = _add(runner, "Fix bug")
        runner.invoke(cli, ["edit", data["id"], "--set", "priority:1"])
        meta = get_task_meta(data["id"])
        assert meta.get("edited_at") is not None

    def test_edited_at_null_before_edit(self, runner):
        data = _add(runner, "Fix bug")
        assert data["edited_at"] is None

    def test_metadata_deleted_on_task_delete(self, runner):
        data = _add(runner, "Fix bug", extra_args=["--source", "slack"])
        runner.invoke(cli, ["delete", data["id"]])
        assert get_task_meta(data["id"]) == {}


# ---------------------------------------------------------------------------
# --dedup: exact key match
# ---------------------------------------------------------------------------

class TestDedupExactKey:
    def test_exact_key_match_exits_4(self, runner):
        _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        result = runner.invoke(
            cli, ["add", "Fix bug again", "--json",
                  "--dedup", "--idempotency-key", "key-001"]
        )
        assert result.exit_code == 4

    def test_exact_match_response_is_duplicate(self, runner):
        _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        result = runner.invoke(
            cli, ["add", "Fix bug again", "--json",
                  "--dedup", "--idempotency-key", "key-001"]
        )
        data = _unwrap(result.output)
        assert data["result"] == "duplicate"
        assert data["task"]["idempotency_key"] == "key-001"

    def test_exact_match_returns_existing_task(self, runner):
        original = _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        result = runner.invoke(
            cli, ["add", "Totally different title", "--json",
                  "--dedup", "--idempotency-key", "key-001"]
        )
        data = _unwrap(result.output)
        assert data["task"]["id"] == original["id"]

    def test_force_overrides_exact_match(self, runner):
        _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        result = runner.invoke(
            cli, ["add", "Fix bug again", "--json",
                  "--dedup", "--idempotency-key", "key-001", "--force"]
        )
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["result"] == "created"

    def test_force_actually_adds_task(self, runner):
        _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        runner.invoke(cli, ["add", "Fix bug again",
                            "--dedup", "--idempotency-key", "key-001", "--force"])
        assert len(read_tasks()) == 2

    def test_no_duplicate_is_created(self, runner):
        _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        runner.invoke(cli, ["add", "Fix bug again",
                            "--dedup", "--idempotency-key", "key-001"])
        assert len(read_tasks()) == 1

    def test_different_key_is_allowed(self, runner):
        _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        result = runner.invoke(
            cli, ["add", "Fix bug", "--json",
                  "--dedup", "--idempotency-key", "key-002"]
        )
        assert result.exit_code == 0
        assert len(read_tasks()) == 2

    def test_no_key_skips_exact_check(self, runner):
        _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        # --dedup without a key falls through to fuzzy check only
        result = runner.invoke(
            cli, ["add", "Completely unrelated task", "--dedup"]
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# --dedup: fuzzy title similarity
# ---------------------------------------------------------------------------

class TestDedupFuzzy:
    def test_similar_title_exits_4(self, runner):
        add_task(Task(title="Fix login bug", id="aaa00001"))
        result = runner.invoke(cli, ["add", "Fix login issue", "--dedup"])
        # "fix login" overlap: tokens={fix,login} vs {fix,login,issue} → 2/3 ≈ 0.67 ≥ 0.5
        assert result.exit_code == 4

    def test_similar_title_response(self, runner):
        add_task(Task(title="Fix login bug", id="aaa00001"))
        result = runner.invoke(cli, ["add", "Fix login issue", "--dedup", "--json"])
        data = _unwrap(result.output)
        assert data["result"] == "duplicate"
        assert len(data["similar"]) >= 1
        assert data["similar"][0]["task"]["id"] == "aaa00001"

    def test_similar_scores_in_response(self, runner):
        add_task(Task(title="Fix login bug", id="aaa00001"))
        result = runner.invoke(cli, ["add", "Fix login issue", "--dedup", "--json"])
        data = _unwrap(result.output)
        assert "score" in data["similar"][0]
        assert 0.0 < data["similar"][0]["score"] <= 1.0

    def test_dissimilar_title_is_created(self, runner):
        add_task(Task(title="Fix login bug", id="aaa00001"))
        result = runner.invoke(cli, ["add", "Buy groceries tomorrow", "--dedup"])
        assert result.exit_code == 0
        assert len(read_tasks()) == 2

    def test_force_overrides_fuzzy(self, runner):
        add_task(Task(title="Fix login bug", id="aaa00001"))
        result = runner.invoke(
            cli, ["add", "Fix login issue", "--dedup", "--force", "--json"]
        )
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["result"] == "created"

    def test_force_similar_list_contains_matches(self, runner):
        add_task(Task(title="Fix login bug", id="aaa00001"))
        result = runner.invoke(
            cli, ["add", "Fix login issue", "--dedup", "--force", "--json"]
        )
        data = _unwrap(result.output)
        # When forced past fuzzy dedup, similar list shows what was overridden
        assert isinstance(data["similar"], list)
        assert len(data["similar"]) >= 1

    def test_created_response_has_empty_similar_when_unique(self, runner):
        result = runner.invoke(
            cli, ["add", "Buy groceries", "--dedup", "--json"]
        )
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["result"] == "created"
        assert data["similar"] == []

    def test_dedup_without_flag_uses_old_response_shape(self, runner):
        result = runner.invoke(cli, ["add", "Buy groceries", "--json"])
        data = _unwrap(result.output)
        # Old shape: plain task dict, no result/similar keys
        assert "id" in data
        assert "result" not in data


# ---------------------------------------------------------------------------
# --dedup: --check-archive
# ---------------------------------------------------------------------------

class TestDedupCheckArchive:
    def test_completed_task_not_matched_by_default(self, runner):
        d = _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        runner.invoke(cli, ["done", d["id"]])
        result = runner.invoke(
            cli, ["add", "Fix bug", "--dedup", "--idempotency-key", "key-001"]
        )
        # Without --check-archive, completed task is not in scope → allowed
        assert result.exit_code == 0

    def test_check_archive_matches_completed_task(self, runner):
        d = _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        runner.invoke(cli, ["done", d["id"]])
        result = runner.invoke(
            cli, ["add", "Fix bug", "--dedup",
                  "--idempotency-key", "key-001", "--check-archive"]
        )
        assert result.exit_code == 4

    def test_check_archive_fuzzy(self, runner):
        d = _add(runner, "Fix login bug")
        runner.invoke(cli, ["done", d["id"]])
        result = runner.invoke(
            cli, ["add", "Fix login issue", "--dedup", "--check-archive"]
        )
        assert result.exit_code == 4


# ---------------------------------------------------------------------------
# --dedup: dry-run interaction
# ---------------------------------------------------------------------------

class TestDedupDryRun:
    def test_dry_run_duplicate_does_not_save(self, runner):
        _add(runner, "Fix bug", extra_args=["--idempotency-key", "key-001"])
        runner.invoke(
            cli, ["add", "Fix bug again", "--dry-run",
                  "--dedup", "--idempotency-key", "key-001"]
        )
        assert len(read_tasks()) == 1  # still just the original

    def test_dry_run_created_does_not_save(self, runner):
        result = runner.invoke(
            cli, ["add", "Buy groceries", "--dry-run", "--dedup"]
        )
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert data["result"] == "created"
        assert read_tasks() == []


# ---------------------------------------------------------------------------
# search --similar
# ---------------------------------------------------------------------------

class TestSearchSimilar:
    def test_finds_similar_task(self, runner):
        add_task(Task(title="Fix login bug", id="aaa00001"))
        result = runner.invoke(cli, ["search", "Fix login issue", "--similar"])
        assert result.exit_code == 0
        assert "aaa00001" in result.output

    def test_no_match_exits_3(self, runner):
        add_task(Task(title="Buy groceries", id="aaa00001"))
        result = runner.invoke(cli, ["search", "Fix login bug", "--similar"])
        assert result.exit_code == 3

    def test_json_output_shape(self, runner):
        add_task(Task(title="Fix login bug", id="aaa00001"))
        result = runner.invoke(
            cli, ["search", "Fix login issue", "--similar", "--json"]
        )
        assert result.exit_code == 0
        data = _unwrap(result.output)
        assert isinstance(data, list)
        assert "score" in data[0]
        assert "task" in data[0]
        assert "matched_fields" not in data[0]  # similarity output, not keyword

    def test_sorted_by_score(self, runner):
        add_task(Task(title="Fix login bug", id="aaa00001"))
        add_task(Task(title="Fix login bug report", id="bbb00002"))
        result = runner.invoke(
            cli, ["search", "Fix login bug", "--similar", "--json"]
        )
        data = _unwrap(result.output)
        scores = [r["score"] for r in data]
        assert scores == sorted(scores, reverse=True)

    def test_similar_includes_archive(self, runner):
        d = _add(runner, "Fix login bug")
        runner.invoke(cli, ["done", d["id"]])
        result = runner.invoke(
            cli, ["search", "Fix login issue", "--similar", "--archive", "--json"]
        )
        data = _unwrap(result.output)
        assert any(r["task"]["id"] == d["id"] for r in data)

    def test_similar_tag_filter(self, runner):
        add_task(Task(title="Fix login bug", id="aaa00001", tags=["work"]))
        add_task(Task(title="Fix login bug", id="bbb00002", tags=["home"]))
        result = runner.invoke(
            cli, ["search", "Fix login bug", "--similar", "--tag", "work", "--json"]
        )
        data = _unwrap(result.output)
        assert len(data) == 1
        assert data[0]["task"]["id"] == "aaa00001"
