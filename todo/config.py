"""
config.toml loader.

Searches for config.toml in TODO_DIR (default ~/.todo/).
Returns a plain dict; all keys are lowercase strings matching the TOML keys.

Python 3.11+ has tomllib in stdlib.  For 3.9/3.10 we use the tomli backport.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .storage import get_todo_dir


def _load_toml(path: Path) -> dict:
    if sys.version_info >= (3, 11):
        import tomllib
        with path.open("rb") as f:
            return tomllib.load(f)
    else:
        try:
            import tomli
            with path.open("rb") as f:
                return tomli.load(f)
        except ImportError:
            raise ImportError(
                "tomli is required for Python < 3.11. "
                "Run: pip install tomli"
            )


# ---------------------------------------------------------------------------
# Built-in defaults
# ---------------------------------------------------------------------------

_DEFAULTS: dict = {
    # ── General ─────────────────────────────────────────────────────────────
    "general": {
        # strftime format used when displaying dates in human-readable output.
        # Does not affect how dates are stored — storage always uses ISO 8601.
        "date_format": "%Y-%m-%d",

        # Default priority assigned to new tasks when not explicitly set.
        "default_priority": 4,
    },

    # ── Tags ─────────────────────────────────────────────────────────────────
    "tags": {
        # Tags automatically applied to every new task added via add.
        # Useful for agents that operate on behalf of a single user / project.
        # Example: default_tags = ["work", "q2"]
        "default_tags": [],
    },

    # ── Notifications ────────────────────────────────────────────────────────
    "notifications": {
        # Delivery backend: stdout | os | email | slack | webhook
        "backend": "stdout",

        # Default lead time applied to tasks that have a due: field but no
        # notify: field.  Set to "" to disable implicit notifications.
        # Accepted formats: 30m | 2h | 1d
        "default_notify": "",

        # Daemon poll interval in seconds
        "poll_interval": 60,

        # Quiet hours window — no notifications are sent during this period.
        # Format: "HH:MM-HH:MM" (24-hour).  Cross-midnight ranges are supported
        # (e.g. "22:00-08:00").  Set to "" to disable.
        "quiet_hours": "",

        "email":   {},
        "slack":   {},
        "webhook": {},
    },
}


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into a copy of base."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """
    Load and return the merged configuration dict.

    Priority (highest to lowest):
      1. config.toml in TODO_DIR
      2. Built-in defaults (_DEFAULTS)
    """
    config_path = get_todo_dir() / "config.toml"
    if not config_path.exists():
        return _deep_merge({}, _DEFAULTS)
    user = _load_toml(config_path)
    return _deep_merge(_DEFAULTS, user)


# ── Convenience accessors ────────────────────────────────────────────────────

def get_notification_backend_name(config: dict) -> str:
    return config.get("notifications", {}).get("backend", "stdout")


def get_poll_interval(config: dict) -> int:
    return int(config.get("notifications", {}).get("poll_interval", 60))


def get_default_notify(config: dict) -> str:
    """Return the default notify lead time string, or '' if not set."""
    return config.get("notifications", {}).get("default_notify", "")


def get_default_tags(config: dict) -> list:
    """Return the list of tags automatically applied to every new task."""
    return list(config.get("tags", {}).get("default_tags", []))


def get_default_priority(config: dict) -> int:
    return int(config.get("general", {}).get("default_priority", 4))


def get_date_format(config: dict) -> str:
    """Return the strftime format string for human-readable date display."""
    return config.get("general", {}).get("date_format", "%Y-%m-%d")


def get_quiet_hours(config: dict) -> str:
    """Return the quiet-hours window string (e.g. '22:00-08:00'), or '' if unset."""
    return config.get("notifications", {}).get("quiet_hours", "")


# ── Config file template ─────────────────────────────────────────────────────

def write_default_config() -> Path:
    """
    Write a commented default config.toml to TODO_DIR if one doesn't exist.
    Returns the path whether or not it was created.
    """
    path = get_todo_dir() / "config.toml"
    if path.exists():
        return path

    get_todo_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(
        """\
# todo CLI configuration
# Location: ~/.todo/config.toml

# ── General ──────────────────────────────────────────────────────────────────
[general]
# strftime format for human-readable date display (storage always uses ISO 8601)
date_format      = "%Y-%m-%d"
# Default priority for new tasks that don't specify one (1=urgent … 4=none)
default_priority = 4

# ── Tags ─────────────────────────────────────────────────────────────────────
[tags]
# Tags automatically added to every new task
# default_tags = ["work", "q2"]
default_tags = []

# ── Notifications ─────────────────────────────────────────────────────────────
[notifications]
# Delivery backend: stdout | os | email | slack | webhook
backend        = "stdout"
# Default notify lead time for tasks that have a due: but no notify: field.
# Leave empty ("") to disable.  e.g. "1h" fires 1 hour before due.
default_notify = ""
# Daemon poll interval in seconds
poll_interval  = 60
# Quiet hours: suppress notifications during this window.
# Format: "HH:MM-HH:MM" (24-hour clock, cross-midnight supported).
# quiet_hours = "22:00-08:00"
quiet_hours    = ""

# ── Email (SMTP) ─────────────────────────────────────────────────────────────
# [notifications.email]
# smtp_host    = "smtp.gmail.com"
# smtp_port    = 587
# from         = "todo-agent@example.com"
# to           = "you@example.com"
# username_env = "SMTP_USER"      # name of env var holding the username
# password_env = "SMTP_PASSWORD"  # name of env var holding the password

# ── Slack ─────────────────────────────────────────────────────────────────────
# [notifications.slack]
# webhook_url_env = "SLACK_WEBHOOK_URL"

# ── Generic webhook (Teams / Discord / Zapier / n8n) ─────────────────────────
# [notifications.webhook]
# url    = "https://hooks.example.com/notify"
# method = "POST"
# headers = { "Authorization" = "Bearer $NOTIFY_TOKEN" }
"""
    )
    return path
