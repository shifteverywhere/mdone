"""
WebhookBackend — generic HTTP POST for Teams, Discord, Zapier, n8n, etc.

Configuration (config.toml):

    [notifications.webhook]
    url    = "https://hooks.example.com/notify"
    method = "POST"          # optional, default POST
    # Header values may reference env vars with $VAR syntax
    headers = { "Authorization" = "Bearer $NOTIFY_TOKEN",
                "X-Source"      = "todo-cli" }

The full task payload dict is posted as a JSON body.
Env var interpolation happens at send time — values are never stored expanded.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from . import BaseBackend

_ENV_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand_env(value: str) -> str:
    """Replace $VAR_NAME occurrences with the current env value (empty if unset)."""
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)


class WebhookBackend(BaseBackend):
    name = "webhook"

    def send(self, payload: dict, config: dict) -> bool:
        cfg = config.get("notifications", {}).get("webhook", {})
        url = cfg.get("url", "")
        if not url:
            print("[WebhookBackend] No url configured.", file=sys.stderr)
            return False

        method  = cfg.get("method", "POST").upper()
        raw_hdrs = cfg.get("headers", {})
        headers = {k: _expand_env(v) for k, v in raw_hdrs.items()}
        headers.setdefault("Content-Type", "application/json")

        data = json.dumps(payload).encode()

        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as e:
            print(f"[WebhookBackend] HTTP {e.code}: {e.reason}", file=sys.stderr)
            return False
        except urllib.error.URLError as e:
            print(f"[WebhookBackend] Connection error: {e}", file=sys.stderr)
            return False
