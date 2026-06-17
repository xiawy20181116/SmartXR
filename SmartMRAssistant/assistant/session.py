from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .card_payload import summarize_tool_results
from .context import SceneContext
from .dispatcher import ToolCall, dispatch_tool_call
from .tools import CardSink, ToolRegistry, create_default_registry


DEFAULT_CARD_ID = "CardAnchor"
DEFAULT_PERSON_REF = "person-ada"
DEFAULT_ISSUE_KEY = "XR-42"
DEFAULT_IDENTITY_SOURCE = {
    "people": [
        {
            "id": "person-ada",
            "display_name": "Ada Lovelace",
            "role": "Demo Lead",
            "confidence": 0.93,
        }
    ]
}
DEFAULT_WORK_ITEM_SOURCE = {
    "issues": [
        {
            "key": "XR-42",
            "summary": "Prepare MR assistant demo",
            "status": "In Progress",
            "assignee": "Ada",
        }
    ]
}


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
    card_sink: CardSink | None = None

    async def run_text_turn(self, text: str) -> list[dict[str, Any]]:
        self.context.last_user_text = text
        scene_response = await self.run_tool_call(
            "scene_status",
            {"scene_snapshot": self.context.snapshot()},
            call_id="simulated-scene-status-1",
        )
        identity_response = await self.run_tool_call(
            "identity_lookup",
            {
                "person_ref": DEFAULT_PERSON_REF,
                "identity_source": DEFAULT_IDENTITY_SOURCE,
            },
            call_id="simulated-identity-1",
        )
        work_item_response = await self.run_tool_call(
            "work_item_lookup",
            {
                "issue_key": DEFAULT_ISSUE_KEY,
                "work_item_source": DEFAULT_WORK_ITEM_SOURCE,
            },
            call_id="simulated-work-item-1",
        )
        identity_result = identity_response["response"]
        work_item_result = work_item_response["response"]
        issue = work_item_result.get("work_item")
        person = identity_result.get("person")
        tool_summary = summarize_tool_results(
            identity_result=identity_result,
            jira_result={
                "status": work_item_result.get("status"),
                "issue": issue,
            },
        )
        card_response = await self.run_tool_call(
            "assistant_card_push",
            {
                "card_id": DEFAULT_CARD_ID,
                "target_id": DEFAULT_PERSON_REF,
                "assistant_state": "responding",
                "response_text": _response_text(tool_summary, issue),
                "tool_summary": tool_summary,
                "person": person,
                "issue": issue,
            },
            call_id="simulated-card-push-1",
        )
        if self.card_sink is not None:
            self.card_sink(card_response["response"]["assistant_card"])
        return [scene_response, identity_response, work_item_response, card_response]

    async def run_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        *,
        call_id: str = "simulated-tool-call-1",
        scheduling: str = "NON_BLOCKING",
    ) -> dict[str, Any]:
        call = ToolCall(
            id=call_id,
            name=name,
            args=args,
            scheduling=scheduling,
        )
        return await dispatch_tool_call(call, self.registry)


def _response_text(tool_summary: dict[str, Any], issue: Any) -> str:
    person_label = str(tool_summary.get("person_label", "Unknown person"))
    issue_label = str(tool_summary.get("issue_label", "No issue"))
    if issue is None:
        return f"{person_label} has no linked issue."
    return f"{person_label} is working on {issue_label}."
