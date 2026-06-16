from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
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


@dataclass(frozen=True, slots=True)
class VoiceSessionConfig:
    provider: str
    model_id: str
    api_key_env: str
    has_api_key: bool = False

    @classmethod
    def from_env(cls, provider: str) -> "VoiceSessionConfig":
        normalized = provider.lower()
        if normalized == "gemini":
            model_env = "SMARTMR_VOICE_GEMINI_MODEL"
            api_key_env = "GEMINI_API_KEY"
        elif normalized == "qwen":
            model_env = "SMARTMR_VOICE_QWEN_MODEL"
            api_key_env = "DASHSCOPE_API_KEY"
        else:
            raise ValueError(f"Unsupported voice provider: {provider}")

        model_id = os.environ.get(model_env)
        if not model_id:
            raise ValueError(f"Missing required model id env var: {model_env}")

        return cls(
            provider=normalized,
            model_id=model_id,
            api_key_env=api_key_env,
            has_api_key=bool(os.environ.get(api_key_env)),
        )


class VoiceSession(ABC):
    """Provider session boundary that emits C4 tool calls.

    Audio capture, codecs, and provider transport stay outside this interface.
    Tests can replay audio bytes as inert timing/input markers and feed recorded
    provider events through the same C4 normalizer.
    """

    @abstractmethod
    def extract_tool_calls(self, event: dict[str, Any]) -> list[ToolCall]:
        raise NotImplementedError

    @abstractmethod
    async def replay_recorded_audio(
        self,
        audio_chunks: list[bytes],
        provider_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


def _tool_call_from_c4(payload: dict[str, Any]) -> ToolCall:
    return ToolCall(
        id=str(payload["id"]),
        name=str(payload["name"]),
        args=dict(payload.get("args", {})),
        scheduling=str(payload.get("scheduling", "NON_BLOCKING")),
    )


@dataclass(slots=True)
class LiveVoiceSession(VoiceSession):
    """Provider-neutral tool-call side of a live voice session."""

    registry: ToolRegistry = field(default_factory=create_default_registry)
    context: SceneContext = field(default_factory=SceneContext)
    config: VoiceSessionConfig | None = None

    async def handle_tool_call_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        call = _tool_call_from_c4(payload)
        return await dispatch_tool_call(call, self.registry)

    def extract_tool_calls(self, event: dict[str, Any]) -> list[ToolCall]:
        return [_tool_call_from_c4(event)]

    async def replay_recorded_audio(
        self,
        audio_chunks: list[bytes],
        provider_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        _ = audio_chunks
        responses: list[dict[str, Any]] = []
        for event in provider_events:
            for call in self.extract_tool_calls(event):
                responses.append(await dispatch_tool_call(call, self.registry))
        return responses


@dataclass(slots=True)
class GeminiLiveVoiceSession(LiveVoiceSession):
    """Gemini Live event adapter that emits frozen C4 tool calls."""

    config: VoiceSessionConfig = field(default_factory=lambda: VoiceSessionConfig.from_env("gemini"))

    def extract_tool_calls(self, event: dict[str, Any]) -> list[ToolCall]:
        tool_call = event.get("toolCall", {})
        function_calls = tool_call.get("functionCalls", event.get("functionCalls", []))
        calls: list[ToolCall] = []
        for function_call in function_calls:
            calls.append(
                _tool_call_from_c4(
                    {
                        "id": function_call.get("id", function_call.get("callId")),
                        "name": function_call["name"],
                        "args": function_call.get("args", {}),
                        "scheduling": function_call.get("scheduling", "NON_BLOCKING"),
                    }
                )
            )
        return calls


@dataclass(slots=True)
class QwenOmniRealtimeVoiceSession(LiveVoiceSession):
    """Qwen Omni Realtime event adapter that emits frozen C4 tool calls."""

    config: VoiceSessionConfig = field(default_factory=lambda: VoiceSessionConfig.from_env("qwen"))

    def extract_tool_calls(self, event: dict[str, Any]) -> list[ToolCall]:
        if event.get("type") == "response.function_call_arguments.done":
            return [
                _tool_call_from_c4(
                    {
                        "id": event.get("call_id", event.get("id")),
                        "name": event["name"],
                        "args": _parse_qwen_arguments(event.get("arguments", {})),
                        "scheduling": event.get("scheduling", "NON_BLOCKING"),
                    }
                )
            ]

        calls: list[ToolCall] = []
        for choice in event.get("choices", []):
            delta = choice.get("delta", {})
            for tool_call in delta.get("tool_calls", []):
                function = tool_call.get("function", {})
                calls.append(
                    _tool_call_from_c4(
                        {
                            "id": tool_call.get("id"),
                            "name": function["name"],
                            "args": _parse_qwen_arguments(function.get("arguments", {})),
                            "scheduling": tool_call.get("scheduling", "NON_BLOCKING"),
                        }
                    )
                )
        return calls


def _parse_qwen_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, str):
        return dict(json.loads(arguments or "{}"))
    return dict(arguments or {})


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
