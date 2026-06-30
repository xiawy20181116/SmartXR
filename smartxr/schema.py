"""Canonical proxy_targets message model and validation.

This module is the code form of ``docs/proxy_targets_payload_contract.md``:
Godot consumes only canonical ``proxy_targets`` messages, raw source fields
(bbox/detections/depth/image) must never cross this boundary.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

ALLOWED_STATES = {"tracked", "predicted", "stale", "lost"}
ALLOWED_TARGET_DEPTH_CONFIDENCES = {"high", "low"}
RAW_SOURCE_FIELDS = {"bbox", "boxes", "detection", "detections", "depth_m", "image"}

DEFAULT_CARD_ID = "CardAnchor"


def default_offset_rule() -> dict[str, Any]:
    """Default card offset rule shared by every publisher."""
    return {
        "mode": "depth_scaled_right_half_width",
        "offset_space": "world",
        "depth_scale": 1.3,
        "depth_offset_m": 0.0,
        "right_width_fraction": 0.5,
        "right_angle_deg": 15.0,
        "fallback": "hold_last_pose",
    }


def _coerce_float(value: Any, default_value: float) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default_value
        return float(value)
    except (TypeError, ValueError):
        return default_value


def _coerce_string(value: Any, default_value: str) -> str:
    if value is None:
        return default_value
    text = str(value).strip()
    return text if text else default_value


def _apply_offset_rule_options(rule: dict[str, Any], options: dict[str, Any], prefix: str = "") -> None:
    string_keys = {
        "mode": "mode",
        "offset_space": "offset_space",
        "fallback": "fallback",
    }
    float_keys = {
        "depth_scale": "depth_scale",
        "depth_offset_m": "depth_offset_m",
        "right_width_fraction": "right_width_fraction",
        "right_angle_deg": "right_angle_deg",
        "up_m": "up_m",
    }
    for option_key, rule_key in string_keys.items():
        key = f"{prefix}{option_key}" if prefix else option_key
        if key in options:
            rule[rule_key] = _coerce_string(options.get(key), str(rule.get(rule_key, "")))
    for option_key, rule_key in float_keys.items():
        key = f"{prefix}{option_key}" if prefix else option_key
        if key in options:
            rule[rule_key] = _coerce_float(options.get(key), float(rule.get(rule_key, 0.0)))


def load_card_offset_rule(options_path: Path | str | None = None, default_rule: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load the card offset rule from a SmartXR JSON options file.

    The Python publishers and Godot fallback both use this shape. Missing or
    invalid config files fall back to the shared default so manual runners can
    pass a path before the user has edited the file.
    """
    rule = dict(default_rule or default_offset_rule())
    raw_path = str(options_path or os.environ.get("SMARTXR_OPTIONS_PATH", "")).strip()
    if not raw_path:
        return rule

    try:
        parsed = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return rule
    if not isinstance(parsed, dict):
        return rule

    nested = parsed.get("proxy_targets_card_offset_rule")
    if isinstance(nested, dict):
        _apply_offset_rule_options(rule, nested)
    _apply_offset_rule_options(rule, parsed, prefix="proxy_targets_card_")
    return rule


def canonical_state(raw_state: Any) -> str:
    """Map source tracking states onto the canonical state enum."""
    state = str(raw_state or "tracked").strip().lower()
    if state in ALLOWED_STATES:
        return state
    if state in {"new", "active", "confirmed"}:
        return "tracked"
    if state in {"missing", "occluded"}:
        return "predicted"
    if state in {"removed", "deleted"}:
        return "lost"
    return "tracked"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_number_array(value: Any, length: int, path: str, errors: list[str]) -> None:
    if not isinstance(value, list) or len(value) != length:
        errors.append(f"{path} must be an array of {length} numbers")
        return
    for index, item in enumerate(value):
        if not _is_number(item):
            errors.append(f"{path}[{index}] must be a number")


def _scan_raw_source_fields(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in RAW_SOURCE_FIELDS:
                errors.append(f"raw source field not allowed at {child_path}")
            _scan_raw_source_fields(child, child_path, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_raw_source_fields(child, f"{path}[{index}]", errors)


def _validate_target(target: Any, index: int, errors: list[str]) -> str | None:
    path = f"$.targets[{index}]"
    if not isinstance(target, dict):
        errors.append(f"{path} must be an object")
        return None

    target_id = target.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        errors.append(f"{path}.target_id must be a non-empty string")
    if not isinstance(target.get("source"), str) or not target.get("source"):
        errors.append(f"{path}.source must be a non-empty string")
    if target.get("state") not in ALLOWED_STATES:
        errors.append(f"{path}.state must be one of {sorted(ALLOWED_STATES)}")
    confidence = target.get("confidence")
    if not _is_number(confidence) or confidence < 0.0 or confidence > 1.0:
        errors.append(f"{path}.confidence must be a number in [0, 1]")
    if "depth_source" in target and (not isinstance(target.get("depth_source"), str) or not target.get("depth_source")):
        errors.append(f"{path}.depth_source must be a non-empty string when present")
    if "depth_confidence" in target and target.get("depth_confidence") not in ALLOWED_TARGET_DEPTH_CONFIDENCES:
        errors.append(f"{path}.depth_confidence must be one of {sorted(ALLOWED_TARGET_DEPTH_CONFIDENCES)}")
    if not _is_number(target.get("timestamp_ms")):
        errors.append(f"{path}.timestamp_ms must be a number")

    transform = target.get("transform")
    if not isinstance(transform, dict):
        errors.append(f"{path}.transform must be an object")
    else:
        _validate_number_array(transform.get("position"), 3, f"{path}.transform.position", errors)
        _validate_number_array(transform.get("rotation_xyzw"), 4, f"{path}.transform.rotation_xyzw", errors)
        _validate_number_array(transform.get("scale"), 3, f"{path}.transform.scale", errors)

    return target_id if isinstance(target_id, str) and target_id else None


def _validate_card(card: Any, index: int, target_ids: set[str], errors: list[str]) -> None:
    path = f"$.cards[{index}]"
    if not isinstance(card, dict):
        errors.append(f"{path} must be an object")
        return
    card_id = card.get("card_id")
    target_id = card.get("target_id")
    if not isinstance(card_id, str) or not card_id:
        errors.append(f"{path}.card_id must be a non-empty string")
    if not isinstance(target_id, str) or not target_id:
        errors.append(f"{path}.target_id must be a non-empty string")
    elif target_id not in target_ids:
        errors.append(f"{path}.target_id must reference a target in $.targets")
    if "offset_rule" in card and not isinstance(card["offset_rule"], dict):
        errors.append(f"{path}.offset_rule must be an object when present")


def validate_message(message: Any) -> list[str]:
    """Validate a canonical proxy_targets message. Returns a list of errors."""
    errors: list[str] = []
    if not isinstance(message, dict):
        return ["$ must be an object"]

    _scan_raw_source_fields(message, "$", errors)

    if message.get("type") != "proxy_targets":
        errors.append("$.type must be proxy_targets")
    if message.get("schema_version") != SCHEMA_VERSION:
        errors.append("$.schema_version must be 1")
    if not isinstance(message.get("sequence"), int) or isinstance(message.get("sequence"), bool):
        errors.append("$.sequence must be an integer")

    targets = message.get("targets")
    if not isinstance(targets, list) or not targets:
        errors.append("$.targets must be a non-empty array")
        target_ids: set[str] = set()
    else:
        target_ids = set()
        for index, target in enumerate(targets):
            target_id = _validate_target(target, index, errors)
            if target_id is not None:
                target_ids.add(target_id)

    cards = message.get("cards")
    if not isinstance(cards, list) or not cards:
        errors.append("$.cards must be a non-empty array")
    else:
        for index, card in enumerate(cards):
            _validate_card(card, index, target_ids, errors)

    return errors


def load_message(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
