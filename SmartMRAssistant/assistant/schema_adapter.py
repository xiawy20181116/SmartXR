from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def export_live_tool_declarations(exported_schemas: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Convert SmartXR C5 tool schemas into provider-neutral Live declarations."""

    declarations: list[dict[str, Any]] = []
    for name, spec in exported_schemas.items():
        declarations.append(
            {
                "name": str(name),
                "description": f"SmartXR assistant capability: {name}",
                "parameters": dict(spec.get("input_schema", {})),
                "x_smartxr": {
                    "output_schema": dict(spec.get("output_schema", {})),
                    "latency_budget_ms": int(spec.get("latency_budget_ms", 250)),
                    "scheduling": str(spec.get("scheduling", "NON_BLOCKING")),
                },
            }
        )
    return {"function_declarations": declarations}
