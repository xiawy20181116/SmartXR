from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any


ToolArgs = Mapping[str, Any]
ToolResult = dict[str, Any]
ToolHandler = Callable[[ToolArgs], ToolResult | Awaitable[ToolResult]]


class ToolRegistry:
    """Small async-aware registry for assistant tool calls."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        if not name:
            raise ValueError("tool name must not be empty")
        self._handlers[name] = handler

    async def run(self, name: str, args: ToolArgs) -> ToolResult:
        try:
            handler = self._handlers[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

        result = handler(args)
        if inspect.isawaitable(result):
            result = await result
        return dict(result)


def echo_tool(args: ToolArgs) -> ToolResult:
    return {"text": str(args.get("text", ""))}


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("echo", echo_tool)
    return registry
