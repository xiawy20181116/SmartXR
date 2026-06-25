from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
_ROOT = TOOLS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from collect_stereo_bbox_pairs import nv12_frame_to_bgr  # noqa: E402
from smartxr.nv12_reader import read_packet_file  # noqa: E402
from smartxr.stereo_package import load_stereo_package  # noqa: E402


KEYPOINT_NAMES = {
    0: "nose",
    1: "left_eye",
    2: "right_eye",
    3: "left_ear",
    4: "right_ear",
    5: "left_shoulder",
    6: "right_shoulder",
    7: "left_elbow",
    8: "right_elbow",
    9: "left_wrist",
    10: "right_wrist",
    11: "left_hip",
    12: "right_hip",
    13: "left_knee",
    14: "right_knee",
    15: "left_ankle",
    16: "right_ankle",
}


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object")
            yield payload


def _bbox_top_center(bbox_xyxy: list[float] | tuple[float, float, float, float]) -> list[float]:
    x1, y1, x2, _y2 = (float(value) for value in bbox_xyxy)
    return [(x1 + x2) * 0.5, y1]


def _as_xy_score(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    xy = value.get("xy")
    score = value.get("score")
    if not isinstance(xy, (list, tuple)) or len(xy) != 2 or score is None:
        return None
    return {"xy": [float(xy[0]), float(xy[1])], "score": float(score)}


def _valid_keypoint(keypoints: dict[str, Any], name: str, min_score: float) -> dict[str, Any] | None:
    keypoint = _as_xy_score(keypoints.get(name))
    if keypoint is None or float(keypoint["score"]) < float(min_score):
        return None
    return keypoint


def _midpoint_anchor(
    keypoints: dict[str, Any],
    left_name: str,
    right_name: str,
    *,
    kind: str,
    min_score: float,
) -> dict[str, Any] | None:
    left = _valid_keypoint(keypoints, left_name, min_score)
    right = _valid_keypoint(keypoints, right_name, min_score)
    if left is None or right is None:
        return None
    return {
        "kind": kind,
        "keypoints": [left_name, right_name],
        "xy": [
            (float(left["xy"][0]) + float(right["xy"][0])) * 0.5,
            (float(left["xy"][1]) + float(right["xy"][1])) * 0.5,
        ],
        "score": min(float(left["score"]), float(right["score"])),
    }


def select_anchor(
    keypoints: dict[str, Any],
    *,
    bbox_xyxy: list[float] | tuple[float, float, float, float] | None,
    min_score: float,
) -> dict[str, Any]:
    shoulder = _midpoint_anchor(
        keypoints,
        "left_shoulder",
        "right_shoulder",
        kind="shoulder_midpoint",
        min_score=min_score,
    )
    if shoulder is not None:
        return shoulder

    nose = _valid_keypoint(keypoints, "nose", min_score)
    if nose is not None:
        return {
            "kind": "nose",
            "keypoints": ["nose"],
            "xy": nose["xy"],
            "score": float(nose["score"]),
        }

    ears = _midpoint_anchor(
        keypoints,
        "left_ear",
        "right_ear",
        kind="ear_midpoint",
        min_score=min_score,
    )
    if ears is not None:
        return ears

    if bbox_xyxy is None:
        return {"kind": "missing", "keypoints": [], "xy": None, "score": 0.0}
    return {
        "kind": "bbox_top_center",
        "keypoints": [],
        "xy": _bbox_top_center(bbox_xyxy),
        "score": 1.0,
    }


def build_stereo_keypoint_pair_record(
    *,
    frame_id: int,
    timestamp_ms: int,
    left_keypoints: dict[str, Any],
    right_keypoints: dict[str, Any],
    bbox_pair: dict[str, Any] | None,
    min_score: float,
) -> dict[str, Any]:
    left_bbox = None if bbox_pair is None else bbox_pair.get("left_bbox_xyxy")
    right_bbox = None if bbox_pair is None else bbox_pair.get("right_bbox_xyxy")
    left_anchor = select_anchor(left_keypoints, bbox_xyxy=left_bbox, min_score=min_score)
    right_anchor = select_anchor(right_keypoints, bbox_xyxy=right_bbox, min_score=min_score)
    anchor_kind = left_anchor["kind"] if left_anchor["kind"] == right_anchor["kind"] else "mixed"
    anchor_keypoints = list(
        dict.fromkeys(list(left_anchor.get("keypoints", [])) + list(right_anchor.get("keypoints", [])))
    )
    anchor_score = min(float(left_anchor.get("score", 0.0)), float(right_anchor.get("score", 0.0)))

    pair_id = f"pair-{int(frame_id):06d}"
    person_id = "person-1"
    confidence = anchor_score
    if bbox_pair is not None:
        pair_id = str(bbox_pair.get("pair_id", pair_id))
        person_id = str(bbox_pair.get("person_id", person_id))
        confidence = min(confidence, float(bbox_pair.get("confidence", confidence)))

    record: dict[str, Any] = {
        "source": "vst_stereo_keypoint",
        "schema_version": 1,
        "pair_id": pair_id,
        "frame_id": int(frame_id),
        "person_id": person_id,
        "timestamp_ms": int(timestamp_ms),
        "confidence": confidence,
        "keypoints": {
            "left": left_keypoints,
            "right": right_keypoints,
        },
        "selected_anchor": {
            "kind": anchor_kind,
            "keypoints": anchor_keypoints,
            "left_px": left_anchor["xy"],
            "right_px": right_anchor["xy"],
            "score": anchor_score,
        },
    }
    if left_bbox is not None and right_bbox is not None:
        left_bbox_values = [float(value) for value in left_bbox]
        right_bbox_values = [float(value) for value in right_bbox]
        record["left_bbox_xyxy"] = left_bbox_values
        record["right_bbox_xyxy"] = right_bbox_values
        record["bbox_baseline"] = {
            "left_anchor_px": _bbox_top_center(left_bbox_values),
            "right_anchor_px": _bbox_top_center(right_bbox_values),
            "score": float(bbox_pair.get("confidence", 1.0)) if bbox_pair is not None else 1.0,
        }
    return record


def write_stereo_keypoint_pair_records(
    *,
    records: Iterable[dict[str, Any]],
    out_path: Path,
    min_score: float,
) -> dict[str, Any]:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pair_count = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for source in records:
            record = build_stereo_keypoint_pair_record(
                frame_id=int(source["frame_id"]),
                timestamp_ms=int(source.get("timestamp_ms", int(time.time() * 1000))),
                left_keypoints=dict(source["left_keypoints"]),
                right_keypoints=dict(source["right_keypoints"]),
                bbox_pair=source.get("bbox_pair"),
                min_score=min_score,
            )
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            pair_count += 1
    return {"pair_count": pair_count, "target_observed": pair_count > 0, "output_jsonl": str(out_path)}


def _to_list(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def _normalize_pose_output(keypoints: Any, scores: Any) -> dict[str, dict[str, Any]]:
    keypoints = _to_list(keypoints)
    scores = _to_list(scores)
    if not keypoints:
        return {}
    if keypoints and isinstance(keypoints[0], (int, float)):
        keypoints = [keypoints]
        scores = [scores]
    if keypoints and keypoints[0] and isinstance(keypoints[0][0], (int, float)):
        keypoints = [keypoints]
        scores = [scores]

    best_index = 0
    best_score = -1.0
    for person_index, person_scores in enumerate(scores):
        valid_scores = [float(score) for score in person_scores if score is not None]
        average_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
        if average_score > best_score:
            best_index = person_index
            best_score = average_score

    selected_keypoints = keypoints[best_index]
    selected_scores = scores[best_index]
    normalized: dict[str, dict[str, Any]] = {}
    for index, name in KEYPOINT_NAMES.items():
        if index >= len(selected_keypoints) or index >= len(selected_scores):
            continue
        xy = selected_keypoints[index]
        if not isinstance(xy, (list, tuple)) or len(xy) < 2:
            continue
        normalized[name] = {
            "xy": [float(xy[0]), float(xy[1])],
            "score": float(selected_scores[index]),
        }
    return normalized


def _load_bbox_pairs(path: Path | None) -> dict[int, dict[str, Any]]:
    if path is None:
        return {}
    return {int(record["frame_id"]): record for record in _iter_jsonl(path)}


def build_stereo_keypoint_pairs_from_package(
    *,
    package_dir: Path,
    pose_estimator: Callable[[Any], tuple[Any, Any]],
    out_path: Path,
    bbox_pairs_input: Path | None = None,
    frame_decoder: Callable[[Any], Any] | None = None,
    min_score: float = 0.5,
    stop_after_pairs: int | None = None,
) -> dict[str, Any]:
    summary = load_stereo_package(package_dir)
    bbox_pairs = _load_bbox_pairs(bbox_pairs_input)
    if frame_decoder is None:
        frame_decoder = nv12_frame_to_bgr

    pair_count = 0
    dropped_no_anchor_pairs = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for pair in summary.pairs:
            left_frame = frame_decoder(read_packet_file(pair.left.path, index=pair.left.index))
            right_frame = frame_decoder(read_packet_file(pair.right.path, index=pair.right.index))
            left_keypoints, left_scores = pose_estimator(left_frame)
            right_keypoints, right_scores = pose_estimator(right_frame)
            record = build_stereo_keypoint_pair_record(
                frame_id=pair.frame_id,
                timestamp_ms=min(pair.left.timestamp_us, pair.right.timestamp_us) // 1000,
                left_keypoints=_normalize_pose_output(left_keypoints, left_scores),
                right_keypoints=_normalize_pose_output(right_keypoints, right_scores),
                bbox_pair=bbox_pairs.get(pair.frame_id),
                min_score=min_score,
            )
            if record["selected_anchor"]["left_px"] is None or record["selected_anchor"]["right_px"] is None:
                dropped_no_anchor_pairs += 1
                continue
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            pair_count += 1
            if stop_after_pairs is not None and pair_count >= max(1, int(stop_after_pairs)):
                break
    return {
        "source": "stereo_record_package",
        "input_package_dir": str(package_dir),
        "bbox_pairs_input": None if bbox_pairs_input is None else str(bbox_pairs_input),
        "output_jsonl": str(out_path),
        "package_pair_count": summary.pair_count,
        "pair_count": pair_count,
        "target_observed": pair_count > 0,
        "dropped_no_anchor_pairs": dropped_no_anchor_pairs,
    }


def _create_rtmlib_estimator(args: argparse.Namespace) -> Callable[[Any], tuple[Any, Any]]:
    try:
        from rtmlib import Body, Wholebody
    except Exception as exc:
        raise RuntimeError(
            "rtmlib is required for record-package keypoint collection; install rtmlib in the active Python env"
        ) from exc

    estimator_class = Wholebody if args.pose_model == "wholebody" else Body
    kwargs = {
        "mode": args.mode,
        "backend": args.backend,
        "device": args.device,
    }
    try:
        return estimator_class(to_openpose=False, **kwargs)
    except TypeError:
        return estimator_class(**kwargs)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect paired Left/Right VST rtmlib keypoints for stereo depth evaluation."
    )
    parser.add_argument("--input-package", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--bbox-pairs-input", type=Path, default=None)
    parser.add_argument("--stop-after-pairs", type=int, default=None)
    parser.add_argument("--require-target", action="store_true")
    parser.add_argument("--min-keypoint-score", type=float, default=0.5)
    parser.add_argument("--pose-model", choices=["body", "wholebody"], default="body")
    parser.add_argument("--mode", default="balanced")
    parser.add_argument("--backend", default="onnxruntime")
    parser.add_argument("--device", default="cpu")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        pose_estimator = _create_rtmlib_estimator(args)
        status = build_stereo_keypoint_pairs_from_package(
            package_dir=args.input_package,
            pose_estimator=pose_estimator,
            out_path=args.out,
            bbox_pairs_input=args.bbox_pairs_input,
            min_score=args.min_keypoint_score,
            stop_after_pairs=args.stop_after_pairs,
        )
    except Exception as exc:
        status = {
            "source": "stereo_record_package",
            "target_observed": False,
            "pair_count": 0,
            "reason": "keypoint_collection_failed",
            "error": str(exc),
            "input_package_dir": str(args.input_package),
            "output_jsonl": str(args.out.resolve()),
        }
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
        return 1
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    if args.require_target and not status["target_observed"]:
        return 2
    return 0 if status["pair_count"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
