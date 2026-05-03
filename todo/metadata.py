"""
Sidecar metadata store: ~/.todo/metadata.json

Stores agent-facing fields keyed by task ID. These fields have no human value
and would clutter tasks.md if stored inline.

Immutable fields (set on creation, never overwritten):
  source, origin_id, origin_url, captured_at, idempotency_key

Mutable fields (updated automatically):
  edited_at
"""

import json
import os
from pathlib import Path
from typing import Optional

METADATA_SCHEMA_VERSION = 1

_IMMUTABLE = frozenset({"source", "origin_id", "origin_url", "captured_at", "idempotency_key"})


def _meta_file() -> Path:
    custom = os.environ.get("TODO_DIR")
    base = Path(custom) if custom else Path.home() / ".todo"
    return base / "metadata.json"


def _read_raw() -> dict:
    f = _meta_file()
    if not f.exists():
        return {"schema_version": METADATA_SCHEMA_VERSION, "tasks": {}}
    return json.loads(f.read_text())


def _write_raw(data: dict) -> None:
    _meta_file().write_text(json.dumps(data, indent=2))


def get_task_meta(task_id: str) -> dict:
    """Return metadata dict for one task (empty dict if no entry exists)."""
    return _read_raw()["tasks"].get(task_id, {})


def read_all_meta() -> dict:
    """Return the full tasks mapping {task_id: meta_dict}."""
    return _read_raw()["tasks"]


def create_task_meta(task_id: str, meta: dict) -> None:
    """Write initial metadata for a new task. None values are not stored."""
    data = _read_raw()
    data["tasks"][task_id] = {k: v for k, v in meta.items() if v is not None}
    _write_raw(data)


def update_task_meta(task_id: str, updates: dict) -> None:
    """Update mutable metadata fields. Immutable fields are silently ignored."""
    data = _read_raw()
    existing = data["tasks"].get(task_id, {})
    for k, v in updates.items():
        if k not in _IMMUTABLE and v is not None:
            existing[k] = v
    data["tasks"][task_id] = existing
    _write_raw(data)


def delete_task_meta(task_id: str) -> None:
    """Remove the metadata entry for a task (e.g. on permanent delete)."""
    data = _read_raw()
    data["tasks"].pop(task_id, None)
    _write_raw(data)
