"""
StdoutBackend — prints a JSON notification payload to stdout.

This is the default backend and the primary interface for AI agents.
The agent reads stdout, dispatches through its own channel, then calls
`todo notify --mark-sent <id>`.
"""

import json
import sys
from . import BaseBackend


class StdoutBackend(BaseBackend):
    name = "stdout"

    def send(self, payload: dict, config: dict) -> bool:
        print(json.dumps(payload, indent=2), file=sys.stdout)
        return True
