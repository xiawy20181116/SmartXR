from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SceneContext:
    """Placeholder for device-side scene state consumed by future tools."""

    last_user_text: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "last_user_text": self.last_user_text,
            "facts": dict(self.facts),
        }
