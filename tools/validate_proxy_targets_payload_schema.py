from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ALLOWED_STATES = {"tracked", "predicted", "stale", "lost"}
RAW_SOURCE_FIELDS = {"bbox", "boxes", "detection", "detections", "depth_m", "image"}


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
    errors: list[str] = []
    if not isinstance(message, dict):
        return ["$ must be an object"]

    _scan_raw_source_fields(message, "$", errors)

    if message.get("type") != "proxy_targets":
        errors.append("$.type must be proxy_targets")
    if message.get("schema_version") != 1:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate canonical proxy_targets payloads before Godot consumption.")
    parser.add_argument("--input", action="append", required=True, type=Path, help="JSON payload file to validate.")
    args = parser.parse_args()

    ok = True
    for input_path in args.input:
        errors = validate_message(load_message(input_path))
        if errors:
            ok = False
            print(f"{input_path}: invalid")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"{input_path}: ok")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
