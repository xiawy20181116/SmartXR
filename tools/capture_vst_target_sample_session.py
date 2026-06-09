from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


SESSION_FILE = "vst_capture_session.jsonl"
FIRST_TARGET_FILE = "vst_first_target_sample.json"
STATUS_FILE = "vst_capture_status.json"


def _as_float(value: Any, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    return fallback


def _as_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return fallback


def _image_from_frame(frame: dict[str, Any]) -> dict[str, int]:
    image = frame.get("image")
    if isinstance(image, dict):
        width = _as_int(image.get("w", image.get("width")), 0)
        height = _as_int(image.get("h", image.get("height")), 0)
    else:
        width = _as_int(frame.get("image_width", frame.get("width")), 0)
        height = _as_int(frame.get("image_height", frame.get("height")), 0)
    result: dict[str, int] = {}
    if width > 0:
        result["w"] = width
    if height > 0:
        result["h"] = height
    return result


def _frame_sequence(frame: dict[str, Any], index: int) -> int:
    return _as_int(frame.get("sequence", frame.get("frame_id", frame.get("frame_index"))), index)


def _target_source_items(frame: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("detections", "targets", "people"):
        value = frame.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _bbox_from_value(value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        if all(key in value for key in ("cx", "cy", "w", "h")):
            return {
                "cx": _as_float(value.get("cx"), 0.0),
                "cy": _as_float(value.get("cy"), 0.0),
                "w": _as_float(value.get("w"), 0.0),
                "h": _as_float(value.get("h"), 0.0),
            }
        if all(key in value for key in ("x1", "y1", "x2", "y2")):
            x1 = _as_float(value.get("x1"), 0.0)
            y1 = _as_float(value.get("y1"), 0.0)
            x2 = _as_float(value.get("x2"), x1)
            y2 = _as_float(value.get("y2"), y1)
            return {"cx": (x1 + x2) * 0.5, "cy": (y1 + y2) * 0.5, "w": x2 - x1, "h": y2 - y1}
    if isinstance(value, list) and len(value) >= 4:
        x1 = _as_float(value[0], 0.0)
        y1 = _as_float(value[1], 0.0)
        x2 = _as_float(value[2], x1)
        y2 = _as_float(value[3], y1)
        return {"cx": (x1 + x2) * 0.5, "cy": (y1 + y2) * 0.5, "w": x2 - x1, "h": y2 - y1}
    return {}


def _detection_id(item: dict[str, Any], index: int) -> str:
    raw_id = item.get("id", item.get("target_id", item.get("track_id")))
    if raw_id is None or raw_id == "":
        raw_id = index
    value = str(raw_id)
    if value.startswith("person-"):
        return value
    return f"person-{value}"


def normalize_frame(frame: dict[str, Any], index: int, min_confidence: float) -> dict[str, Any]:
    sequence = _frame_sequence(frame, index)
    image = _image_from_frame(frame)
    timestamp_ms = frame.get("timestamp_ms", frame.get("ts_ms"))
    normalized: dict[str, Any] = {
        "source": str(frame.get("source", "vst")),
        "sequence": sequence,
        "detections": [],
        "pose_quality": str(frame.get("pose_quality", "projected_2d")),
    }
    if timestamp_ms is not None:
        normalized["timestamp_ms"] = _as_float(timestamp_ms, 0.0)
    if image:
        normalized["image"] = image

    detections: list[dict[str, Any]] = []
    for item_index, item in enumerate(_target_source_items(frame)):
        confidence = _as_float(item.get("confidence", item.get("score")), 1.0)
        if confidence < min_confidence:
            continue
        detection: dict[str, Any] = {
            "id": _detection_id(item, item_index),
            "state": str(item.get("state", item.get("tracking_status", "tracked"))),
            "confidence": confidence,
        }
        bbox = _bbox_from_value(item.get("bbox", item.get("box")))
        if bbox:
            detection["bbox"] = bbox
        if "depth_m" in item:
            detection["depth_m"] = _as_float(item.get("depth_m"), 1.2)
        if "position" in item:
            detection["position"] = item["position"]
        if "transform" in item:
            detection["transform"] = item["transform"]
        detections.append(detection)

    normalized["detections"] = detections
    return normalized


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def capture_target_sample_session(
    frames: Iterable[dict[str, Any]],
    out_dir: Path,
    min_confidence: float = 0.0,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    session_path = out_dir / SESSION_FILE
    first_target_path = out_dir / FIRST_TARGET_FILE
    status_path = out_dir / STATUS_FILE

    frames_seen = 0
    empty_frames = 0
    first_target_frame: int | None = None
    first_target_sample: dict[str, Any] | None = None

    with session_path.open("w", encoding="utf-8", newline="\n") as session:
        for index, frame in enumerate(frames, start=1):
            if not isinstance(frame, dict):
                continue
            normalized = normalize_frame(frame, index=index, min_confidence=min_confidence)
            frames_seen += 1
            if not normalized["detections"]:
                empty_frames += 1
            elif first_target_sample is None:
                first_target_sample = normalized
                first_target_frame = int(normalized["sequence"])
            session.write(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")) + "\n")

    target_ready = first_target_sample is not None
    if target_ready:
        _write_json(first_target_path, first_target_sample)

    if frames_seen == 0:
        reason = "no_frames_seen"
    elif target_ready:
        reason = "target_sample_ready"
    else:
        reason = "no_target_observed"

    status: dict[str, Any] = {
        "source_alive": frames_seen > 0,
        "frames_seen": frames_seen,
        "empty_frames": empty_frames,
        "target_sample_ready": target_ready,
        "first_target_frame": first_target_frame,
        "reason": reason,
        "session_jsonl": str(session_path),
        "status_json": str(status_path),
    }
    if target_ready:
        status["output"] = str(first_target_path)
    _write_json(status_path, status)
    return status


def _iter_stdin_jsonl() -> Iterable[dict[str, Any]]:
    for line_number, line in enumerate(sys.stdin, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"stdin line {line_number} must be a JSON object")
        yield payload


def _iter_input_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object")
            yield payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture a VST target sample session without requiring 6DoF pose.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--stdin-jsonl", action="store_true")
    input_group.add_argument("--input-jsonl", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--require-target", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    frames = _iter_stdin_jsonl() if args.stdin_jsonl else _iter_input_jsonl(args.input_jsonl)
    status = capture_target_sample_session(frames, args.out_dir, min_confidence=args.min_confidence)
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    if args.require_target and not status["target_sample_ready"]:
        return 2
    if not status["source_alive"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
