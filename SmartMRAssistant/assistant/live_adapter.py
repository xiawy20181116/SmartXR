from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .card_payload import summarize_tool_results
from .session import (
    DEFAULT_CARD_ID,
    DEFAULT_IDENTITY_SOURCE,
    DEFAULT_ISSUE_KEY,
    DEFAULT_PERSON_REF,
    DEFAULT_WORK_ITEM_SOURCE,
    LiveVoiceSession,
)


def normalize_live_tool_call_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize provider-specific tool-call events for LiveVoiceSession."""

    raw_call = _raw_tool_call(event)
    args = _decode_args(raw_call.get("args", raw_call.get("arguments", {})))
    return {
        "id": str(raw_call["id"]),
        "name": str(raw_call["name"]),
        "args": args,
        "scheduling": str(raw_call.get("scheduling", "NON_BLOCKING")),
    }


async def handle_live_tool_call_event(event: Mapping[str, Any], session: LiveVoiceSession) -> dict[str, Any]:
    try:
        payload = normalize_live_tool_call_event(event)
        response = await session.handle_tool_call_payload(payload)
        return {"ok": True, **response}
    except Exception as exc:
        raw_call = _best_effort_raw_tool_call(event)
        return {
            "ok": False,
            "tool_call_id": str(raw_call.get("id", "unknown")),
            "name": str(raw_call.get("name", "unknown")),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }


async def run_fake_live_task_query_turn(text: str, session: LiveVoiceSession) -> dict[str, Any]:
    session.context.last_user_text = text
    scene_response = await handle_live_tool_call_event(
        {
            "tool_call": {
                "id": "fake-live-scene-status-1",
                "name": "scene_status",
                "args": {"scene_snapshot": session.context.snapshot()},
            }
        },
        session,
    )
    identity_response = await handle_live_tool_call_event(
        {
            "tool_call": {
                "id": "fake-live-identity-1",
                "name": "identity_lookup",
                "args": {
                    "person_ref": DEFAULT_PERSON_REF,
                    "identity_source": DEFAULT_IDENTITY_SOURCE,
                },
            }
        },
        session,
    )
    work_item_response = await handle_live_tool_call_event(
        {
            "tool_call": {
                "id": "fake-live-work-item-1",
                "name": "work_item_lookup",
                "args": {
                    "issue_key": DEFAULT_ISSUE_KEY,
                    "work_item_source": DEFAULT_WORK_ITEM_SOURCE,
                },
            }
        },
        session,
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
    card_response = await handle_live_tool_call_event(
        {
            "tool_call": {
                "id": "fake-live-card-push-1",
                "name": "assistant_card_push",
                "args": {
                    "card_id": DEFAULT_CARD_ID,
                    "target_id": DEFAULT_PERSON_REF,
                    "assistant_state": "responding",
                    "response_text": _response_text(tool_summary, issue),
                    "tool_summary": tool_summary,
                    "person": person,
                    "issue": issue,
                },
            }
        },
        session,
    )
    return {
        "text": text,
        "tool_responses": [scene_response, identity_response, work_item_response, card_response],
        "assistant_card": card_response["response"]["assistant_card"],
    }


def _raw_tool_call(event: Mapping[str, Any]) -> Mapping[str, Any]:
    raw_call = _best_effort_raw_tool_call(event)
    if "id" not in raw_call:
        raise ValueError("live tool-call event missing id")
    if "name" not in raw_call:
        raise ValueError("live tool-call event missing name")
    return raw_call


def _best_effort_raw_tool_call(event: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(event.get("tool_call"), Mapping):
        return event["tool_call"]
    if isinstance(event.get("function_call"), Mapping):
        return event["function_call"]
    return event


def _decode_args(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        if not value.strip():
            return {}
        decoded = json.loads(value)
        if not isinstance(decoded, Mapping):
            raise ValueError("live tool-call arguments must decode to an object")
        return dict(decoded)
    raise ValueError("live tool-call args must be an object or JSON object string")


def _response_text(tool_summary: Mapping[str, Any], issue: Any) -> str:
    person_label = str(tool_summary.get("person_label", "Unknown person"))
    issue_label = str(tool_summary.get("issue_label", "No issue"))
    if issue is None:
        return f"{person_label} has no linked issue."
    return f"{person_label} is working on {issue_label}."
