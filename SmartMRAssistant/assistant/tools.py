from __future__ import annotations

import inspect
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .card_payload import build_assistant_card_payload


ToolArgs = Mapping[str, Any]
ToolResult = dict[str, Any]
ToolHandler = Callable[[ToolArgs], ToolResult | Awaitable[ToolResult]]
CardSink = Callable[[dict[str, Any]], None]


class UnknownToolError(KeyError):
    """Raised when a caller requests a tool that is not registered."""


class MissingRequiredArgumentError(ValueError):
    """Raised when a tool call omits schema-required input."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    handler: ToolHandler
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    latency_budget_ms: int
    scheduling: str

    def export(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "latency_budget_ms": self.latency_budget_ms,
            "scheduling": self.scheduling,
        }


class ToolRegistry:
    """Small async-aware registry for assistant tool calls."""

    def __init__(self, trace_path: str | Path | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._trace_path = Path(trace_path) if trace_path is not None else None

    def register(
        self,
        name: str,
        handler: ToolHandler,
        *,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        latency_budget_ms: int = 250,
        scheduling: str = "NON_BLOCKING",
    ) -> None:
        if not name:
            raise ValueError("tool name must not be empty")
        self._specs[name] = ToolSpec(
            name=name,
            handler=handler,
            input_schema=input_schema or {"type": "object", "properties": {}},
            output_schema=output_schema or {"type": "object", "properties": {}},
            latency_budget_ms=latency_budget_ms,
            scheduling=scheduling,
        )

    def export_schemas(self) -> dict[str, dict[str, Any]]:
        return {name: spec.export() for name, spec in self._specs.items()}

    async def run(self, name: str, args: ToolArgs) -> ToolResult:
        start = datetime.now(timezone.utc)
        start_perf = time.perf_counter()
        success = False
        error_type: str | None = None
        try:
            try:
                spec = self._specs[name]
            except KeyError as exc:
                raise UnknownToolError(f"unknown tool: {name}") from exc
            _validate_required_args(name, args, spec.input_schema)
            result = spec.handler(args)
            if inspect.isawaitable(result):
                result = await result
            success = True
            return dict(result)
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            end = datetime.now(timezone.utc)
            self._write_trace(
                {
                    "tool_name": name,
                    "args_summary": _summarize_args(args),
                    "started_at": start.isoformat(),
                    "ended_at": end.isoformat(),
                    "duration_ms": round((time.perf_counter() - start_perf) * 1000, 3),
                    "success": success,
                    "error_type": error_type,
                }
            )

    def _write_trace(self, record: dict[str, Any]) -> None:
        if self._trace_path is None:
            return
        self._trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self._trace_path.open("a", encoding="utf-8") as trace_file:
            trace_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def scene_status_tool(args: ToolArgs) -> ToolResult:
    scene_snapshot = args.get("scene_snapshot") or {}
    scene = dict(scene_snapshot) if isinstance(scene_snapshot, Mapping) else {}
    scene.setdefault("last_user_text", None)
    scene.setdefault("facts", {})
    return {"status": "ok", "scene": scene}


def identity_lookup_tool(args: ToolArgs) -> ToolResult:
    person_ref = str(args["person_ref"])
    identity_source = args.get("identity_source") or args.get("snapshot") or {}
    people = identity_source.get("people", []) if isinstance(identity_source, Mapping) else []
    for person in people:
        if not isinstance(person, Mapping):
            continue
        if person.get("id") == person_ref or person.get("display_name") == person_ref:
            return {"status": "found", "person": dict(person)}
    return {"status": "not_found", "person": None}


def work_item_lookup_tool(args: ToolArgs) -> ToolResult:
    issue_key = str(args["issue_key"])
    work_item_source = args.get("work_item_source") or args.get("cache") or {}
    issues = work_item_source.get("issues", []) if isinstance(work_item_source, Mapping) else []
    for issue in issues:
        if not isinstance(issue, Mapping):
            continue
        if issue.get("key") == issue_key:
            return {"status": "found", "work_item": dict(issue)}
    return {"status": "not_found", "work_item": None}


def card_command_tool(args: ToolArgs) -> ToolResult:
    control = {
        "type": "control",
        "command": str(args["command"]),
    }
    if "card_id" in args:
        control["card_id"] = str(args["card_id"])
    if "target_id" in args:
        control["target_id"] = str(args["target_id"])
    return {"status": "accepted", "control": control}


def assistant_card_push_tool(args: ToolArgs, card_sink: CardSink | None = None) -> ToolResult:
    assistant_card = build_assistant_card_payload(
        card_id=str(args["card_id"]),
        target_id=str(args["target_id"]),
        assistant_state=str(args.get("assistant_state", "responding")),
        response_text=str(args.get("response_text", "")),
        tool_summary=_optional_mapping(args.get("tool_summary")),
        person=_optional_mapping(args.get("person")),
        issue=_optional_mapping(args.get("issue")),
    )
    if card_sink is not None:
        card_sink(assistant_card)
    return {"status": "published", "assistant_card": assistant_card}


def create_default_registry(trace_path: str | Path | None = None, card_sink: CardSink | None = None) -> ToolRegistry:
    registry = ToolRegistry(trace_path=trace_path)
    registry.register(
        "scene_status",
        scene_status_tool,
        input_schema={
            "type": "object",
            "properties": {"scene_snapshot": {"type": "object"}},
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["ok"]},
                "scene": {"type": "object"},
            },
            "required": ["status", "scene"],
        },
        latency_budget_ms=75,
        scheduling="NON_BLOCKING",
    )
    registry.register(
        "identity_lookup",
        identity_lookup_tool,
        input_schema={
            "type": "object",
            "properties": {
                "person_ref": {"type": "string"},
                "identity_source": {"type": "object"},
            },
            "required": ["person_ref"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["found", "not_found"]},
                "person": {"type": ["object", "null"]},
            },
            "required": ["status", "person"],
        },
        latency_budget_ms=150,
        scheduling="NON_BLOCKING",
    )
    registry.register(
        "work_item_lookup",
        work_item_lookup_tool,
        input_schema={
            "type": "object",
            "properties": {
                "issue_key": {"type": "string"},
                "work_item_source": {"type": "object"},
            },
            "required": ["issue_key"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["found", "not_found"]},
                "work_item": {"type": ["object", "null"]},
            },
            "required": ["status", "work_item"],
        },
        latency_budget_ms=200,
        scheduling="NON_BLOCKING",
    )
    registry.register(
        "card_command",
        card_command_tool,
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "card_id": {"type": "string"},
                "target_id": {"type": "string"},
            },
            "required": ["command"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["accepted"]},
                "control": {"type": "object"},
            },
            "required": ["status", "control"],
        },
        latency_budget_ms=75,
        scheduling="NON_BLOCKING",
    )
    registry.register(
        "assistant_card_push",
        lambda args: assistant_card_push_tool(args, card_sink),
        input_schema={
            "type": "object",
            "properties": {
                "card_id": {"type": "string"},
                "target_id": {"type": "string"},
                "assistant_state": {"type": "string"},
                "response_text": {"type": "string"},
                "tool_summary": {"type": "object"},
                "person": {"type": ["object", "null"]},
                "issue": {"type": ["object", "null"]},
            },
            "required": ["card_id", "target_id", "response_text"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["published"]},
                "assistant_card": {"type": "object"},
            },
            "required": ["status", "assistant_card"],
        },
        latency_budget_ms=150,
        scheduling="NON_BLOCKING",
    )
    return registry


def _validate_required_args(name: str, args: ToolArgs, schema: Mapping[str, Any]) -> None:
    missing = [field for field in schema.get("required", []) if field not in args]
    if missing:
        raise MissingRequiredArgumentError(f"{name} missing required argument(s): {', '.join(missing)}")


def _summarize_args(args: ToolArgs) -> dict[str, Any]:
    sensitive_or_large = {
        "snapshot",
        "cache",
        "identity_source",
        "work_item_source",
        "scene_snapshot",
        "person",
        "issue",
        "tool_summary",
        "secret",
        "token",
        "password",
        "api_key",
    }
    summary: dict[str, Any] = {}
    for key, value in args.items():
        lowered = str(key).lower()
        if lowered in sensitive_or_large or any(marker in lowered for marker in ("secret", "token", "password")):
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            summary[str(key)] = value
    return summary


def _optional_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError("assistant_card_push optional object fields must be objects or null")
