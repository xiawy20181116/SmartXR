"""Clip-level capture manifest model and validation.

This module is the code form of ``docs/capture_clip_manifest.md``. The manifest
extends the capture-package level inventory with clip/session labels used by the
T0-T3 data grading line.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MANIFEST_TYPE = "capture_clip_manifest"

ALLOWED_TIERS = {"T0", "T1", "T2", "T3"}
REQUIRED_LABELS = ("scene", "people", "distance", "motion", "lighting", "entry_exit")

ALLOWED_CONFIDENCE = {"verified", "observed", "inferred", "unlabeled", "unknown"}
ALLOWED_DISTANCE_BANDS = {"near", "mid", "far", "mixed", "unknown"}
ALLOWED_MOTION_PATTERNS = {
    "static",
    "lateral",
    "approach_recede",
    "mixed",
    "presence_change",
    "sparse_presence",
    "steady_presence",
    "unknown",
}
ALLOWED_LIGHTING = {"normal_indoor", "low_light", "backlit", "mixed", "unknown"}
ALLOWED_ENTRY_EXIT = {"yes", "no", "candidate", "unknown"}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_string(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path} must be a non-empty string")


def _validate_confidence(label: dict[str, Any], path: str, errors: list[str]) -> None:
    confidence = label.get("confidence")
    if confidence not in ALLOWED_CONFIDENCE:
        errors.append(f"{path}.confidence must be one of {sorted(ALLOWED_CONFIDENCE)}")


def _validate_label_object(value: Any, path: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return None
    _validate_confidence(value, path, errors)
    return value


def _validate_scene(value: Any, path: str, errors: list[str]) -> None:
    label = _validate_label_object(value, path, errors)
    if label is None:
        return
    _require_string(label.get("value"), f"{path}.value", errors)


def _validate_people(value: Any, path: str, errors: list[str]) -> None:
    label = _validate_label_object(value, path, errors)
    if label is None:
        return

    min_count = label.get("min_sampled_count")
    max_count = label.get("max_sampled_count")
    dominant_count = label.get("dominant_sampled_count")
    for key, count in (
        ("min_sampled_count", min_count),
        ("max_sampled_count", max_count),
        ("dominant_sampled_count", dominant_count),
    ):
        if not _is_int(count) or count < 0:
            errors.append(f"{path}.{key} must be a non-negative integer")

    if _is_int(min_count) and _is_int(max_count) and min_count > max_count:
        errors.append(f"{path}.min_sampled_count must be <= max_sampled_count")

    histogram = label.get("sampled_count_histogram")
    if not isinstance(histogram, dict) or not histogram:
        errors.append(f"{path}.sampled_count_histogram must be a non-empty object")
        return

    parsed_keys: list[int] = []
    for key, count in histogram.items():
        try:
            parsed_key = int(key)
        except (TypeError, ValueError):
            errors.append(f"{path}.sampled_count_histogram keys must be integer strings")
            continue
        if parsed_key < 0:
            errors.append(f"{path}.sampled_count_histogram keys must be non-negative")
        parsed_keys.append(parsed_key)
        if not _is_int(count) or count < 0:
            errors.append(f"{path}.sampled_count_histogram[{key!r}] must be a non-negative integer")

    if parsed_keys and _is_int(max_count) and max(parsed_keys) != max_count:
        errors.append(f"{path}.max_sampled_count must match sampled_count_histogram max key")


def _validate_enum_label(
    value: Any,
    path: str,
    field: str,
    allowed_values: set[str],
    errors: list[str],
) -> None:
    label = _validate_label_object(value, path, errors)
    if label is None:
        return
    if label.get(field) not in allowed_values:
        errors.append(f"{path}.{field} must be one of {sorted(allowed_values)}")


def _validate_verification(value: Any, path: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return
    recall = value.get("person_recall_pct")
    if recall is not None and (not _is_number(recall) or recall < 0.0 or recall > 100.0):
        errors.append(f"{path}.person_recall_pct must be a number in [0, 100]")
    confidence = value.get("mean_confidence")
    if confidence is not None and (not _is_number(confidence) or confidence < 0.0 or confidence > 1.0):
        errors.append(f"{path}.mean_confidence must be a number in [0, 1]")


def _validate_clip(clip: Any, index: int, errors: list[str]) -> None:
    path = f"$.clips[{index}]"
    if not isinstance(clip, dict):
        errors.append(f"{path} must be an object")
        return

    _require_string(clip.get("session_id"), f"{path}.session_id", errors)
    if clip.get("tier") not in ALLOWED_TIERS:
        errors.append(f"{path}.tier must be one of {sorted(ALLOWED_TIERS)}")

    for key in ("frames_total", "sampled_frames"):
        if key in clip and (not _is_int(clip[key]) or clip[key] < 0):
            errors.append(f"{path}.{key} must be a non-negative integer")

    labels = clip.get("labels")
    if not isinstance(labels, dict):
        errors.append(f"{path}.labels must be an object")
        return
    for label in REQUIRED_LABELS:
        if label not in labels:
            errors.append(f"{path}.labels.{label} is required")

    if "scene" in labels:
        _validate_scene(labels["scene"], f"{path}.labels.scene", errors)
    if "people" in labels:
        _validate_people(labels["people"], f"{path}.labels.people", errors)
    if "distance" in labels:
        _validate_enum_label(labels["distance"], f"{path}.labels.distance", "band", ALLOWED_DISTANCE_BANDS, errors)
    if "motion" in labels:
        _validate_enum_label(labels["motion"], f"{path}.labels.motion", "pattern", ALLOWED_MOTION_PATTERNS, errors)
    if "lighting" in labels:
        _validate_enum_label(labels["lighting"], f"{path}.labels.lighting", "condition", ALLOWED_LIGHTING, errors)
    if "entry_exit" in labels:
        _validate_enum_label(labels["entry_exit"], f"{path}.labels.entry_exit", "event", ALLOWED_ENTRY_EXIT, errors)

    _validate_verification(clip.get("verification"), f"{path}.verification", errors)


def validate_manifest(manifest: Any) -> list[str]:
    """Validate a clip-level capture manifest. Returns a list of errors."""
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["$ must be an object"]

    if manifest.get("type") != MANIFEST_TYPE:
        errors.append(f"$.type must be {MANIFEST_TYPE}")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"$.schema_version must be {SCHEMA_VERSION}")

    source_package = manifest.get("source_package")
    if not isinstance(source_package, dict):
        errors.append("$.source_package must be an object")
    else:
        _require_string(source_package.get("package_id"), "$.source_package.package_id", errors)
        _require_string(source_package.get("source_manifest"), "$.source_package.source_manifest", errors)

    clips = manifest.get("clips")
    if not isinstance(clips, list) or not clips:
        errors.append("$.clips must be a non-empty array")
    else:
        seen_sessions: set[str] = set()
        for index, clip in enumerate(clips):
            _validate_clip(clip, index, errors)
            if isinstance(clip, dict):
                session_id = clip.get("session_id")
                if isinstance(session_id, str) and session_id:
                    if session_id in seen_sessions:
                        errors.append(f"$.clips[{index}].session_id must be unique")
                    seen_sessions.add(session_id)

    return errors


def load_manifest(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
