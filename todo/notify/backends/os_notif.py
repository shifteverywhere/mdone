"""
OSBackend — native desktop notifications.

macOS  : osascript
Linux  : notify-send  (libnotify)
Windows: win10toast (optional pip install)

Falls back to a printed warning if none of the above are available.
"""

import platform
import subprocess
import sys
from . import BaseBackend


class OSBackend(BaseBackend):
    name = "os"

    def send(self, payload: dict, config: dict) -> bool:
        title = f"Todo: {payload['title']}"
        body_parts = []
        if payload.get("due"):
            label = "OVERDUE" if payload.get("overdue") else f"due {payload['due']}"
            body_parts.append(label)
        if payload.get("priority", 4) < 4:
            body_parts.append(f"p{payload['priority']}")
        body = "  ".join(body_parts) if body_parts else "Task reminder"

        os_name = platform.system()

        if os_name == "Darwin":
            return self._macos(title, body)
        elif os_name == "Linux":
            return self._linux(title, body)
        elif os_name == "Windows":
            return self._windows(title, body)
        else:
            print(
                f"[OSBackend] Unsupported platform {os_name!r}. "
                "Use stdout backend for agent use.",
                file=sys.stderr,
            )
            return False

    # ------------------------------------------------------------------

    def _macos(self, title: str, body: str) -> bool:
        script = (
            f'display notification "{body}" '
            f'with title "{title}" '
            f'sound name "Default"'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"[OSBackend] macOS notification failed: {e}", file=sys.stderr)
            return False

    def _linux(self, title: str, body: str) -> bool:
        try:
            subprocess.run(
                ["notify-send", "--urgency=normal", title, body],
                check=True,
                capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"[OSBackend] notify-send failed: {e}", file=sys.stderr)
            return False

    def _windows(self, title: str, body: str) -> bool:
        try:
            from win10toast import ToastNotifier  # type: ignore
            ToastNotifier().show_toast(title, body, duration=10, threaded=True)
            return True
        except ImportError:
            print(
                "[OSBackend] win10toast not installed. "
                "Run: pip install win10toast",
                file=sys.stderr,
            )
            return False
        except Exception as e:
            print(f"[OSBackend] Windows notification failed: {e}", file=sys.stderr)
            return False
