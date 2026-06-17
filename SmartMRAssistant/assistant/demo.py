from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping
from typing import Any

from .card_payload import summarize_tool_results
from .session import SimulatedVoiceSession


DEFAULT_QUESTION = "他手上有什么任务"
DEFAULT_CARD_ID = "CardAnchor"
DEFAULT_PERSON_REF = "person-ada"
DEFAULT_ISSUE_KEY = "XR-42"
DEFAULT_SCENE_SNAPSHOT = {
    "people": [
        {
            "id": "person-ada",
            "display_name": "Ada Lovelace",
            "role": "Demo Lead",
            "confidence": 0.93,
        }
    ]
}
DEFAULT_JIRA_CACHE = {
    "issues": [
        {
            "key": "XR-42",
            "summary": "Prepare MR assistant demo",
            "status": "In Progress",
            "assignee": "Ada",
        }
    ]
}


async def build_mstar_demo_result(
    *,
    question: str = DEFAULT_QUESTION,
    person_ref: str = DEFAULT_PERSON_REF,
    issue_key: str = DEFAULT_ISSUE_KEY,
    card_id: str = DEFAULT_CARD_ID,
    snapshot: Mapping[str, Any] | None = None,
    cache: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    session = SimulatedVoiceSession()
    scene_snapshot = dict(snapshot or DEFAULT_SCENE_SNAPSHOT)
    jira_cache = dict(cache or DEFAULT_JIRA_CACHE)

    identity_response = await session.run_tool_call(
        "identity_lookup",
        {
            "person_ref": person_ref,
            "identity_source": scene_snapshot,
        },
        call_id="mstar-identity-1",
    )
    work_item_response = await session.run_tool_call(
        "work_item_lookup",
        {
            "issue_key": issue_key,
            "work_item_source": jira_cache,
        },
        call_id="mstar-work-item-1",
    )
    scene_response = await session.run_tool_call(
        "scene_status",
        {
            "scene_snapshot": {
                "last_user_text": question,
                "facts": {"card_id": card_id, "target_id": person_ref},
            }
        },
        call_id="mstar-scene-status-1",
    )
    identity_result = identity_response["response"]
    work_item_result = work_item_response["response"]
    issue = work_item_result.get("work_item") if isinstance(work_item_result.get("work_item"), Mapping) else None
    tool_summary = summarize_tool_results(
        identity_result=identity_result,
        jira_result={
            "status": work_item_result.get("status"),
            "issue": issue,
        },
    )
    person = identity_result.get("person") if isinstance(identity_result.get("person"), Mapping) else None
    card_response = await session.run_tool_call(
        "assistant_card_push",
        {
            "card_id": card_id,
            "target_id": person_ref,
            "assistant_state": "responding",
            "response_text": _response_text(tool_summary, issue),
            "tool_summary": tool_summary,
            "person": person,
            "issue": issue,
        },
        call_id="mstar-card-push-1",
    )
    payload = card_response["response"]["assistant_card"]
    return {
        "question": question,
        "tool_responses": [scene_response, identity_response, work_item_response, card_response],
        "assistant_card": payload,
    }


def build_mstar_demo_result_sync(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(build_mstar_demo_result(**kwargs))


def _response_text(tool_summary: Mapping[str, Any], issue: Mapping[str, Any] | None) -> str:
    person_label = str(tool_summary.get("person_label", "Unknown person"))
    issue_label = str(tool_summary.get("issue_label", "No issue"))
    if issue is None:
        return f"{person_label} has no linked issue."
    return f"{person_label} is working on {issue_label}."


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the SmartMR M-star assistant-card demo.")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--person-ref", default=DEFAULT_PERSON_REF)
    parser.add_argument("--issue-key", default=DEFAULT_ISSUE_KEY)
    parser.add_argument("--card-id", default=DEFAULT_CARD_ID)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = build_mstar_demo_result_sync(
        question=args.question,
        person_ref=args.person_ref,
        issue_key=args.issue_key,
        card_id=args.card_id,
    )
    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()
