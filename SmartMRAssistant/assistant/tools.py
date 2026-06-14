from __future__ import annotations

import inspect
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ToolArgs = Mapping[str, Any]
ToolResult = dict[str, Any]
ToolHandler = Callable[[ToolArgs], ToolResult | Awaitable[ToolResult]]


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
        try:
            spec = self._specs[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

        start = datetime.now(timezone.utc)
        start_perf = time.perf_counter()
        success = False
        error_type: str | None = None
        try:
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


def echo_tool(args: ToolArgs) -> ToolResult:
    return {"text": str(args.get("text", ""))}


def identity_lookup_tool(args: ToolArgs) -> ToolResult:
    person_ref = str(args["person_ref"])
    snapshot = args.get("snapshot") or {}
    people = snapshot.get("people", []) if isinstance(snapshot, Mapping) else []
    for person in people:
        if not isinstance(person, Mapping):
            continue
        if person.get("id") == person_ref or person.get("display_name") == person_ref:
            return {"status": "found", "person": dict(person)}
    return {"status": "not_found", "person": None}


def jira_lookup_tool(args: ToolArgs) -> ToolResult:
    issue_key = str(args["issue_key"])
    cache = args.get("cache") or {}
    issues = cache.get("issues", []) if isinstance(cache, Mapping) else []
    for issue in issues:
        if not isinstance(issue, Mapping):
            continue
        if issue.get("key") == issue_key:
            return {"status": "found", "issue": dict(issue)}
    return {"status": "not_found", "issue": None}


def create_default_registry(trace_path: str | Path | None = None) -> ToolRegistry:
    registry = ToolRegistry(trace_path=trace_path)
    registry.register(
        "echo",
        echo_tool,
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        latency_budget_ms=50,
        scheduling="NON_BLOCKING",
    )
    registry.register(
        "identity_lookup",
        identity_lookup_tool,
        input_schema={
            "type": "object",
            "properties": {
                "person_ref": {"type": "string"},
                "snapshot": {"type": "object"},
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
        "jira_lookup",
        jira_lookup_tool,
        input_schema={
            "type": "object",
            "properties": {
                "issue_key": {"type": "string"},
                "cache": {"type": "object"},
            },
            "required": ["issue_key"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["found", "not_found"]},
                "issue": {"type": ["object", "null"]},
            },
            "required": ["status", "issue"],
        },
        latency_budget_ms=200,
        scheduling="NON_BLOCKING",
    )
    return registry


def _validate_required_args(name: str, args: ToolArgs, schema: Mapping[str, Any]) -> None:
    missing = [field for field in schema.get("required", []) if field not in args]
    if missing:
        raise ValueError(f"{name} missing required argument(s): {', '.join(missing)}")


def _summarize_args(args: ToolArgs) -> dict[str, Any]:
    sensitive_or_large = {"snapshot", "cache", "secret", "token", "password", "api_key"}
    summary: dict[str, Any] = {}
    for key, value in args.items():
        lowered = str(key).lower()
        if lowered in sensitive_or_large or any(marker in lowered for marker in ("secret", "token", "password")):
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            summary[str(key)] = value
    return summary
