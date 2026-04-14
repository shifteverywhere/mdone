"""
Notification backend registry.

Each backend implements BaseBackend.send(payload, config) → bool.

Usage
-----
    from todo.notify.backends import get_backend
    backend = get_backend("slack", config)
    backend.send(payload, config)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseBackend(ABC):
    """Contract every delivery backend must satisfy."""

    name: str = "base"

    @abstractmethod
    def send(self, payload: dict, config: dict) -> bool:
        """
        Deliver a single notification.

        Parameters
        ----------
        payload : dict
            The pending-task dict produced by checker.build_pending.
        config : dict
            The full parsed config dict (backend may read its own section).

        Returns
        -------
        bool
            True if the notification was delivered successfully.
        """


def get_backend(name: str, config: dict) -> BaseBackend:
    """Return the backend instance for *name*, or raise ValueError."""
    from .stdout import StdoutBackend
    from .os_notif import OSBackend
    from .email import EmailBackend
    from .slack import SlackBackend
    from .webhook import WebhookBackend

    backends: dict = {
        "stdout":  StdoutBackend,
        "os":      OSBackend,
        "email":   EmailBackend,
        "slack":   SlackBackend,
        "webhook": WebhookBackend,
    }
    if name not in backends:
        raise ValueError(
            f"Unknown backend {name!r}. "
            f"Available: {', '.join(backends)}"
        )
    return backends[name]()
