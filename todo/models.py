from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Task:
    title: str
    id: str
    done: bool = False
    tags: List[str] = field(default_factory=list)
    contexts: List[str] = field(default_factory=list)
    due: Optional[str] = None       # ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM
    recur: Optional[str] = None     # daily | weekly | monthly | RRULE:...
    priority: int = 4               # 1 (urgent) – 4 (none)
    notify: Optional[str] = None    # lead time before due: 30m | 1h | 1d
    snooze: Optional[str] = None    # YYYY-MM-DDTHH:MM
    section: str = "inbox"          # inbox | today | upcoming | someday | waiting
    idempotency_key: Optional[str] = None  # caller-provided stable key for dedup

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "done": self.done,
            "tags": self.tags,
            "contexts": self.contexts,
            "due": self.due,
            "recur": self.recur,
            "priority": self.priority,
            "notify": self.notify,
            "snooze": self.snooze,
            "section": self.section,
            "idempotency_key": self.idempotency_key,
        }
