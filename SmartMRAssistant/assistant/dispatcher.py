from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tools import ToolRegistry


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    scheduling: str = "NON_BLOCKING"


async def dispatch_tool_call(call: ToolCall, registry: ToolRegistry) -> dict[str, Any]:
    result = await registry.run(call.name, call.args)
    return {
        "tool_call_id": call.id,
        "name": call.name,
        "response": result,
    }
