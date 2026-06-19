from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tools import MissingRequiredArgumentError, ToolRegistry, UnknownToolError


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    scheduling: str = "NON_BLOCKING"


async def dispatch_tool_call(call: ToolCall, registry: ToolRegistry) -> dict[str, Any]:
    try:
        result = await registry.run(call.name, call.args)
    except Exception as exc:
        result = _structured_error_response(call.name, exc)
    return {
        "tool_call_id": call.id,
        "name": call.name,
        "response": result,
    }


def _structured_error_response(tool_name: str, exc: Exception) -> dict[str, str]:
    error_type = type(exc).__name__
    if isinstance(exc, UnknownToolError):
        message = f"Tool '{tool_name}' is not registered."
    elif isinstance(exc, MissingRequiredArgumentError):
        missing = _missing_args_from_error(exc)
        message = f"Tool '{tool_name}' missing required argument(s): {missing}."
    else:
        message = f"Tool '{tool_name}' failed while handling the request."
    return {
        "status": "error",
        "error_type": error_type,
        "message": message,
    }


def _missing_args_from_error(exc: MissingRequiredArgumentError) -> str:
    text = str(exc)
    marker = "missing required argument(s): "
    if marker not in text:
        return "unknown"
    return text.split(marker, 1)[1]
