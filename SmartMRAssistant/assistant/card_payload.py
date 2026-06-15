from __future__ import annotations

from collections.abc import Mapping
from typing import Any


ASSISTANT_CARD_SCHEMA_VERSION = 1
ASSISTANT_CARD_TYPE = "assistant_card"

ALLOWED_ASSISTANT_STATES = {
    "idle",
    "listening",
    "thinking",
    "responding",
    "complete",
    "error",
}


def build_assistant_card_payload(
    *,
    card_id: str,
    target_id: str,
    assistant_state: str,
    response_text: str,
    tool_summary: Mapping[str, Any] | None = None,
    person: Mapping[str, Any] | None = None,
    issue: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "type": ASSISTANT_CARD_TYPE,
        "schema_version": ASSISTANT_CARD_SCHEMA_VERSION,
        "card_id": str(card_id),
        "target_id": str(target_id),
        "assistant_state": str(assistant_state),
        "response_text": str(response_text),
        "tool_summary": dict(tool_summary or {}),
        "person": dict(person) if person is not None else None,
        "issue": dict(issue) if issue is not None else None,
    }
    errors = validate_assistant_card_payload(payload)
    if errors:
        raise ValueError("; ".join(errors))
    return payload


def validate_assistant_card_payload(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["$ must be an object"]

    errors: list[str] = []
    if payload.get("type") != ASSISTANT_CARD_TYPE:
        errors.append("$.type must be assistant_card")
    if payload.get("schema_version") != ASSISTANT_CARD_SCHEMA_VERSION:
        errors.append("$.schema_version must be 1")
    _validate_non_empty_string(payload, "card_id", errors)
    _validate_non_empty_string(payload, "target_id", errors)
    _validate_non_empty_string(payload, "assistant_state", errors)
    if isinstance(payload.get("assistant_state"), str) and payload["assistant_state"] not in ALLOWED_ASSISTANT_STATES:
        errors.append(f"$.assistant_state must be one of {sorted(ALLOWED_ASSISTANT_STATES)}")
    if not isinstance(payload.get("response_text"), str):
        errors.append("$.response_text must be a string")
    if "tool_summary" in payload and not isinstance(payload["tool_summary"], Mapping):
        errors.append("$.tool_summary must be an object when present")
    if "person" in payload and payload["person"] is not None and not isinstance(payload["person"], Mapping):
        errors.append("$.person must be an object or null when present")
    if "issue" in payload and payload["issue"] is not None and not isinstance(payload["issue"], Mapping):
        errors.append("$.issue must be an object or null when present")
    return errors


def summarize_tool_results(
    *,
    identity_result: Mapping[str, Any],
    jira_result: Mapping[str, Any],
) -> dict[str, str]:
    person = identity_result.get("person") if isinstance(identity_result.get("person"), Mapping) else None
    issue = jira_result.get("issue") if isinstance(jira_result.get("issue"), Mapping) else None

    person_label = _person_label(person)
    issue_key = str(issue.get("key", "")) if issue is not None else ""
    issue_summary = str(issue.get("summary", "")) if issue is not None else ""
    issue_label = _issue_label(issue_key, issue_summary)
    issue_status = str(issue.get("status", "")) if issue is not None else ""

    return {
        "identity_status": str(identity_result.get("status", "not_found")),
        "jira_status": str(jira_result.get("status", "not_found")),
        "person_label": person_label,
        "issue_label": issue_label,
        "status_line": _status_line(person_label, issue_key, issue_status),
    }


def _validate_non_empty_string(payload: Mapping[str, Any], field: str, errors: list[str]) -> None:
    if not isinstance(payload.get(field), str) or not payload.get(field):
        errors.append(f"$.{field} must be a non-empty string")


def _person_label(person: Mapping[str, Any] | None) -> str:
    if person is None:
        return "Unknown person"
    display_name = str(person.get("display_name", "")).strip()
    if display_name:
        return display_name
    person_id = str(person.get("id", "")).strip()
    return person_id if person_id else "Unknown person"


def _issue_label(issue_key: str, issue_summary: str) -> str:
    if issue_key and issue_summary:
        return f"{issue_key}: {issue_summary}"
    if issue_key:
        return issue_key
    if issue_summary:
        return issue_summary
    return "No issue"


def _status_line(person_label: str, issue_key: str, issue_status: str) -> str:
    parts = [person_label]
    if issue_key:
        parts.append(issue_key)
    if issue_status:
        parts.append(issue_status)
    return " | ".join(parts)
