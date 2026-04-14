"""
SlackBackend — Incoming Webhook notification delivery.

Configuration (config.toml):

    [notifications.slack]
    webhook_url_env = "SLACK_WEBHOOK_URL"   # env var holding the webhook URL

The webhook URL itself is NEVER stored in config — only the env var name.

Message format: a single Slack Block Kit message with a header and fields.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from . import BaseBackend


class SlackBackend(BaseBackend):
    name = "slack"

    def send(self, payload: dict, config: dict) -> bool:
        cfg = config.get("notifications", {}).get("slack", {})
        url_env = cfg.get("webhook_url_env", "SLACK_WEBHOOK_URL")
        webhook_url = os.environ.get(url_env, "")

        if not webhook_url:
            print(
                f"[SlackBackend] Env var {url_env!r} is not set.",
                file=sys.stderr,
            )
            return False

        body = self._build_blocks(payload)
        data = json.dumps(body).encode()

        try:
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except urllib.error.URLError as e:
            print(f"[SlackBackend] HTTP error: {e}", file=sys.stderr)
            return False

    @staticmethod
    def _build_blocks(payload: dict) -> dict:
        status = ":rotating_light: OVERDUE" if payload.get("overdue") else ":bell: Due soon"
        pri_map = {1: ":red_circle: p1 Urgent", 2: ":large_orange_circle: p2 Important",
                   3: ":large_yellow_circle: p3 Normal", 4: "p4"}
        pri_label = pri_map.get(payload.get("priority", 4), "p4")

        fields = [
            {"type": "mrkdwn", "text": f"*Status*\n{status}"},
            {"type": "mrkdwn", "text": f"*Priority*\n{pri_label}"},
        ]
        if payload.get("due"):
            fields.append({"type": "mrkdwn", "text": f"*Due*\n{payload['due']}"})
        if payload.get("tags"):
            tag_str = "  ".join(f"`@{t}`" for t in payload["tags"])
            fields.append({"type": "mrkdwn", "text": f"*Tags*\n{tag_str}"})

        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"Todo: {payload['title']}"},
                },
                {"type": "section", "fields": fields},
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"ID: `{payload['id']}`"}
                    ],
                },
            ]
        }
