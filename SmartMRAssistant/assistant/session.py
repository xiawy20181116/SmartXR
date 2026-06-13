from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .context import SceneContext
from .dispatcher import ToolCall, dispatch_tool_call
from .tools import ToolRegistry, create_default_registry


@dataclass(slots=True)
class LiveVoiceSession:
    """Tool-call side of a future Gemini Live voice session."""

    registry: ToolRegistry = field(default_factory=create_default_registry)
    context: SceneContext = field(default_factory=SceneContext)

    async def handle_tool_call_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        call = ToolCall(
            id=str(payload["id"]),
            name=str(payload["name"]),
            args=dict(payload.get("args", {})),
            scheduling=str(payload.get("scheduling", "NON_BLOCKING")),
        )
        return await dispatch_tool_call(call, self.registry)


@dataclass(slots=True)
class SimulatedVoiceSession:
    """Headless text simulation of the voice-agent path.

    Live audio transport is intentionally kept outside the dispatcher. The
    dispatcher only sees tool-call objects, which mirrors Gemini Live tool-call
    handling while keeping S1 runnable without a headset or microphone.
    """

    registry: ToolRegistry = field(default_factory=create_default_registry)
    context: SceneContext = field(default_factory=SceneContext)

    async def run_text_turn(self, text: str) -> list[dict[str, Any]]:
        self.context.last_user_text = text
        call = ToolCall(
            id="simulated-echo-1",
            name="echo",
            args={"text": text},
            scheduling="NON_BLOCKING",
        )
        return [await dispatch_tool_call(call, self.registry)]
