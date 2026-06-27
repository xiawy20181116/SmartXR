from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
_ROOT = TOOLS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dump_antman_vst_humantrackor_jsonl import (  # noqa: E402
    DEFAULT_ANTMAN_ROOT,
    _install_antman_paths,
    _person_to_dict,
    _shape_width_height,
    resolve_vst_shm_name,
)
from smartxr.nv12_reader import Nv12Frame, read_packet_file  # noqa: E402
from smartxr.stereo_depth import SCENE_STEREO_28  # noqa: E402
from smartxr.stereo_package import load_stereo_package  # noqa: E402


def _people_from_tracking_result(tracking_result: Any) -> list[dict[str, Any]]:
    return [_person_to_dict(person) for person in getattr(tracking_result, "people", [])]


def _best_person(people: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not people:
        return None
    return max(people, key=lambda person: float(person.get("confidence", 0.0)))


def _bbox_xyxy(person: dict[str, Any]) -> list[int]:
    return [int(value) for value in person["bbox"]]


def _track_id(person: dict[str, Any]) -> int:
    return int(person.get("track_id", 0))


def _top_center(bbox: list[int]) -> tuple[float, float]:
    x1, y1, x2, _y2 = (float(value) for value in bbox)
    return ((x1 + x2) * 0.5, y1)


def _bbox_center(bbox: list[int]) -> tuple[float, float]:
    x1, y1, x2, y2 = (float(value) for value in bbox)
    return ((x1 + x2) * 0.5, (y1 + y2) * 0.5)


def _bbox_size(bbox: list[int]) -> tuple[float, float]:
    x1, y1, x2, y2 = (float(value) for value in bbox)
    return (x2 - x1, y2 - y1)


def _bbox_iou(first: list[int], second: list[int]) -> float:
    ax1, ay1, ax2, ay2 = (float(value) for value in first)
    bx1, by1, bx2, by2 = (float(value) for value in second)
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0.0:
        return 0.0
    first_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    second_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = first_area + second_area - inter_area
    if union <= 0.0:
        return 0.0
    return inter_area / union


def _estimated_depth_m(image_width: int, image_height: int, disparity_px: float) -> float | None:
    if disparity_px <= 0.0:
        return None
    try:
        calibration = SCENE_STEREO_28.scaled_to(image_width, image_height)
    except ValueError:
        return None
    return calibration.left.fx * calibration.baseline_m / float(disparity_px)


class StereoActiveTargetStabilizer:
    def __init__(
        self,
        *,
        active_target_id: str = "active-1",
        switch_confirm_frames: int = 2,
        switch_score_margin: float = 0.12,
        hold_frames: int = 6,
        continuity_iou_threshold: float = 0.30,
    ) -> None:
        self.active_target_id = active_target_id
        self.switch_confirm_frames = max(1, int(switch_confirm_frames))
        self.switch_score_margin = float(switch_score_margin)
        self.hold_frames = max(0, int(hold_frames))
        self.continuity_iou_threshold = float(continuity_iou_threshold)
        self._active: dict[str, Any] | None = None
        self._pending_key: tuple[int, int] | None = None
        self._pending_count = 0
        self._switch_count = 0

    def select(
        self,
        *,
        frame_id: int,
        image_width: int,
        image_height: int,
        left_people: list[dict[str, Any]],
        right_people: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        candidates = self._build_candidates(frame_id, image_width, image_height, left_people, right_people)
        if not candidates:
            return self._hold_missing(frame_id, candidate_count=0)

        best = max(candidates, key=lambda item: item["base_score"])
        active_candidate = self._active_candidate(candidates)
        if self._active is None:
            return self._activate(best, switch_reason="initial", candidate_count=len(candidates))

        if active_candidate is None:
            held = self._hold_missing(frame_id, candidate_count=len(candidates))
            if held is not None:
                return held
            return self._activate(best, switch_reason="active_missing_switch", candidate_count=len(candidates))

        active_score = float(active_candidate["base_score"])
        best_score = float(best["base_score"])
        if best["key"] != active_candidate["key"] and best_score > active_score + self.switch_score_margin:
            if self._pending_key == best["key"]:
                self._pending_count += 1
            else:
                self._pending_key = best["key"]
                self._pending_count = 1
            if self._pending_count >= self.switch_confirm_frames:
                self._switch_count += 1
                return self._activate(best, switch_reason="switch_confirmed", candidate_count=len(candidates))

        self._pending_key = None if best["key"] == active_candidate["key"] else self._pending_key
        return self._activate(active_candidate, switch_reason="active_continuity", candidate_count=len(candidates))

    def _build_candidates(
        self,
        frame_id: int,
        image_width: int,
        image_height: int,
        left_people: list[dict[str, Any]],
        right_people: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for left_person in left_people:
            left_bbox = _bbox_xyxy(left_person)
            left_anchor = _top_center(left_bbox)
            left_center = _bbox_center(left_bbox)
            left_size = _bbox_size(left_bbox)
            for right_person in right_people:
                right_bbox = _bbox_xyxy(right_person)
                right_anchor = _top_center(right_bbox)
                right_center = _bbox_center(right_bbox)
                right_size = _bbox_size(right_bbox)
                confidence = min(
                    float(left_person.get("confidence", 0.0)),
                    float(right_person.get("confidence", 0.0)),
                )
                disparity_px = left_anchor[0] - right_anchor[0]
                vertical_error_px = left_anchor[1] - right_anchor[1]
                estimated_depth_m = _estimated_depth_m(image_width, image_height, disparity_px)
                candidates.append(
                    {
                        "frame_id": int(frame_id),
                        "key": (_track_id(left_person), _track_id(right_person)),
                        "left_person": left_person,
                        "right_person": right_person,
                        "left_bbox": left_bbox,
                        "right_bbox": right_bbox,
                        "confidence": confidence,
                        "base_score": self._candidate_base_score(
                            confidence=confidence,
                            disparity_px=disparity_px,
                            vertical_error_px=vertical_error_px,
                            left_size=left_size,
                            right_size=right_size,
                            estimated_depth_m=estimated_depth_m,
                        ),
                        "left_center_px": left_center,
                        "right_center_px": right_center,
                        "left_size_px": left_size,
                        "right_size_px": right_size,
                        "disparity_px": disparity_px,
                        "vertical_error_px": vertical_error_px,
                        "estimated_depth_m": estimated_depth_m,
                        "image_width": int(image_width),
                        "image_height": int(image_height),
                    }
                )
        return candidates

    def _candidate_base_score(
        self,
        *,
        confidence: float,
        disparity_px: float,
        vertical_error_px: float,
        left_size: tuple[float, float],
        right_size: tuple[float, float],
        estimated_depth_m: float | None,
    ) -> float:
        score = float(confidence)
        if disparity_px <= 0.0:
            score -= 1.0
        if estimated_depth_m is None or estimated_depth_m < 0.2 or estimated_depth_m > 5.0:
            score -= 0.75
        score -= min(abs(float(vertical_error_px)) / 200.0, 0.5)
        width_ratio = left_size[0] / max(right_size[0], 1.0)
        height_ratio = left_size[1] / max(right_size[1], 1.0)
        if width_ratio < 0.5 or width_ratio > 2.0:
            score -= 0.5
        if height_ratio < 0.5 or height_ratio > 2.0:
            score -= 0.5
        return score

    def _active_candidate(self, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        if self._active is None:
            return None
        active_key = self._active["key"]
        for candidate in candidates:
            if candidate["key"] == active_key:
                return candidate
        plausible: list[tuple[float, dict[str, Any]]] = []
        for candidate in candidates:
            left_iou = _bbox_iou(candidate["left_bbox"], self._active["left_bbox"])
            right_iou = _bbox_iou(candidate["right_bbox"], self._active["right_bbox"])
            continuity = (left_iou + right_iou) * 0.5
            if continuity >= self.continuity_iou_threshold:
                plausible.append((continuity, candidate))
        if not plausible:
            return None
        return max(plausible, key=lambda item: item[0])[1]

    def _activate(self, candidate: dict[str, Any], *, switch_reason: str, candidate_count: int) -> dict[str, Any]:
        active_age_frames = 1
        if self._active is not None and candidate["key"] == self._active["key"]:
            active_age_frames = int(self._active.get("active_age_frames", 0)) + 1
        elif switch_reason == "active_continuity":
            active_age_frames = int(self._active.get("active_age_frames", 0)) + 1 if self._active else 1
        if switch_reason == "switch_confirmed":
            self._pending_key = None
            self._pending_count = 0
        self._active = {
            "key": candidate["key"],
            "left_bbox": candidate["left_bbox"],
            "right_bbox": candidate["right_bbox"],
            "confidence": candidate["confidence"],
            "active_age_frames": active_age_frames,
            "missing_frames": 0,
            "image_width": candidate.get("image_width", 880),
            "image_height": candidate.get("image_height", 660),
        }
        return {
            "person_id": self.active_target_id,
            "left_person": candidate["left_person"],
            "right_person": candidate["right_person"],
            "left_bbox_xyxy": candidate["left_bbox"],
            "right_bbox_xyxy": candidate["right_bbox"],
            "confidence": candidate["confidence"],
            "selection": self._selection_metadata(
                candidate,
                switch_reason=switch_reason,
                active_age_frames=active_age_frames,
                candidate_count=candidate_count,
                held_last_pose=False,
            ),
        }

    def _hold_missing(self, frame_id: int, *, candidate_count: int) -> dict[str, Any] | None:
        if self._active is None:
            return None
        missing_frames = int(self._active.get("missing_frames", 0)) + 1
        if missing_frames > self.hold_frames:
            return None
        self._active["missing_frames"] = missing_frames
        held_candidate = {
            "frame_id": int(frame_id),
            "key": self._active["key"],
            "left_person": {"track_id": self._active["key"][0], "bbox": self._active["left_bbox"]},
            "right_person": {"track_id": self._active["key"][1], "bbox": self._active["right_bbox"]},
            "left_bbox": list(self._active["left_bbox"]),
            "right_bbox": list(self._active["right_bbox"]),
            "confidence": float(self._active.get("confidence", 0.0)),
            "base_score": float(self._active.get("confidence", 0.0)),
            "left_center_px": _bbox_center(self._active["left_bbox"]),
            "right_center_px": _bbox_center(self._active["right_bbox"]),
            "left_size_px": _bbox_size(self._active["left_bbox"]),
            "right_size_px": _bbox_size(self._active["right_bbox"]),
            "disparity_px": _top_center(self._active["left_bbox"])[0] - _top_center(self._active["right_bbox"])[0],
            "vertical_error_px": _top_center(self._active["left_bbox"])[1] - _top_center(self._active["right_bbox"])[1],
            "estimated_depth_m": _estimated_depth_m(
                self._active.get("image_width", 880),
                self._active.get("image_height", 660),
                _top_center(self._active["left_bbox"])[0] - _top_center(self._active["right_bbox"])[0],
            ),
        }
        return {
            "person_id": self.active_target_id,
            "left_person": held_candidate["left_person"],
            "right_person": held_candidate["right_person"],
            "left_bbox_xyxy": held_candidate["left_bbox"],
            "right_bbox_xyxy": held_candidate["right_bbox"],
            "confidence": held_candidate["confidence"],
            "selection": self._selection_metadata(
                held_candidate,
                switch_reason="held_missing",
                active_age_frames=int(self._active.get("active_age_frames", 1)),
                candidate_count=candidate_count,
                held_last_pose=True,
            ),
        }

    def _selection_metadata(
        self,
        candidate: dict[str, Any],
        *,
        switch_reason: str,
        active_age_frames: int,
        candidate_count: int,
        held_last_pose: bool,
    ) -> dict[str, Any]:
        raw_left_track_id, raw_right_track_id = candidate["key"]
        return {
            "active_target_id": self.active_target_id,
            "raw_left_track_id": int(raw_left_track_id),
            "raw_right_track_id": int(raw_right_track_id),
            "raw_person_id": f"person-{int(raw_left_track_id)}-{int(raw_right_track_id)}",
            "candidate_count": int(candidate_count),
            "selected_score": float(candidate["base_score"]),
            "switch_count": int(self._switch_count),
            "switch_reason": switch_reason,
            "active_age_frames": int(active_age_frames),
            "held_last_pose": bool(held_last_pose),
            "disparity_px": float(candidate["disparity_px"]),
            "vertical_error_px": float(candidate["vertical_error_px"]),
            "left_center_px": [candidate["left_center_px"][0], candidate["left_center_px"][1]],
            "right_center_px": [candidate["right_center_px"][0], candidate["right_center_px"][1]],
            "left_size_px": [candidate["left_size_px"][0], candidate["left_size_px"][1]],
            "right_size_px": [candidate["right_size_px"][0], candidate["right_size_px"][1]],
            "estimated_depth_m": candidate.get("estimated_depth_m"),
        }


def _eye_record(
    *,
    frame: Any,
    frame_id: int,
    tracking_result: Any,
    source_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    width, height = _shape_width_height(frame)
    record: dict[str, Any] = {
        "frame_id": int(frame_id),
        "image_width": width,
        "image_height": height,
        "people": _people_from_tracking_result(tracking_result),
        "tracker": {
            "frame_index": int(getattr(tracking_result, "frame_index", frame_id)),
            "frame_latency_ms": float(getattr(tracking_result, "frame_latency_ms", 0.0)),
        },
    }
    if source_stats:
        record["source_stats"] = source_stats
    return record


def build_stereo_bbox_pair_record(
    *,
    frame_id: int,
    left_frame: Any,
    right_frame: Any,
    left_tracking_result: Any,
    right_tracking_result: Any,
    timestamp_ms: int,
    left_source_stats: dict[str, Any] | None = None,
    right_source_stats: dict[str, Any] | None = None,
    target_stabilizer: StereoActiveTargetStabilizer | None = None,
) -> dict[str, Any] | None:
    left = _eye_record(
        frame=left_frame,
        frame_id=frame_id,
        tracking_result=left_tracking_result,
        source_stats=left_source_stats,
    )
    right = _eye_record(
        frame=right_frame,
        frame_id=frame_id,
        tracking_result=right_tracking_result,
        source_stats=right_source_stats,
    )
    if target_stabilizer is None:
        left_person = _best_person(left["people"])
        right_person = _best_person(right["people"])
        if left_person is None or right_person is None:
            return None
        left_track_id = _track_id(left_person)
        right_track_id = _track_id(right_person)
        selected = {
            "person_id": f"person-{left_track_id}-{right_track_id}",
            "left_bbox_xyxy": _bbox_xyxy(left_person),
            "right_bbox_xyxy": _bbox_xyxy(right_person),
            "confidence": min(
                float(left_person.get("confidence", 0.0)),
                float(right_person.get("confidence", 0.0)),
            ),
            "selection": {
                "active_target_id": f"person-{left_track_id}-{right_track_id}",
                "raw_left_track_id": left_track_id,
                "raw_right_track_id": right_track_id,
                "raw_person_id": f"person-{left_track_id}-{right_track_id}",
                "candidate_count": 1,
                "selected_score": min(
                    float(left_person.get("confidence", 0.0)),
                    float(right_person.get("confidence", 0.0)),
                ),
                "switch_count": 0,
                "switch_reason": "best_confidence",
                "active_age_frames": 1,
                "held_last_pose": False,
            },
        }
    else:
        selected = target_stabilizer.select(
            frame_id=frame_id,
            image_width=int(left["image_width"]),
            image_height=int(left["image_height"]),
            left_people=left["people"],
            right_people=right["people"],
        )
        if selected is None:
            return None
    return {
        "source": "vst_stereo_bbox",
        "schema_version": 1,
        "pair_id": f"pair-{int(frame_id):06d}",
        "frame_id": int(frame_id),
        "person_id": selected["person_id"],
        "timestamp_ms": int(timestamp_ms),
        "left_bbox_xyxy": selected["left_bbox_xyxy"],
        "right_bbox_xyxy": selected["right_bbox_xyxy"],
        "confidence": selected["confidence"],
        "selection": selected["selection"],
        "left": left,
        "right": right,
    }


def collect_stereo_bbox_pairs(
    *,
    left_reader: Any,
    right_reader: Any,
    tracker: Any | None = None,
    left_tracker: Any | None = None,
    right_tracker: Any | None = None,
    out_path: Path,
    duration_seconds: float = 30.0,
    max_read_attempts: int = 6000,
    stop_after_pairs: int | None = None,
    sleep_seconds: float = 0.005,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    left_tracker = left_tracker or tracker
    right_tracker = right_tracker or tracker
    if left_tracker is None or right_tracker is None:
        raise ValueError("collect_stereo_bbox_pairs needs tracker or left_tracker/right_tracker")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started = clock()
    pending_left: dict[int, Any] = {}
    pending_right: dict[int, Any] = {}
    seen_left: set[int] = set()
    seen_right: set[int] = set()
    pair_count = 0
    dropped_no_target_pairs = 0
    read_failures = 0
    last_pair_frame_id = -1

    try:
        with out_path.open("w", encoding="utf-8", newline="\n") as handle:
            for _attempt in range(max(0, int(max_read_attempts))):
                if clock() - started >= duration_seconds:
                    break
                read_failures += _read_one_eye(left_reader, pending_left, seen_left)
                read_failures += _read_one_eye(right_reader, pending_right, seen_right)

                for frame_id in sorted(set(pending_left).intersection(pending_right)):
                    left_frame = pending_left.pop(frame_id)
                    right_frame = pending_right.pop(frame_id)
                    timestamp_ms = int(time.time() * 1000)
                    left_tracking_result = left_tracker.process_frame(left_frame)
                    right_tracking_result = right_tracker.process_frame(right_frame)
                    left_stats = left_reader.get_stats() if hasattr(left_reader, "get_stats") else {}
                    right_stats = right_reader.get_stats() if hasattr(right_reader, "get_stats") else {}
                    record = build_stereo_bbox_pair_record(
                        frame_id=frame_id,
                        left_frame=left_frame,
                        right_frame=right_frame,
                        left_tracking_result=left_tracking_result,
                        right_tracking_result=right_tracking_result,
                        timestamp_ms=timestamp_ms,
                        left_source_stats=left_stats,
                        right_source_stats=right_stats,
                    )
                    if record is None:
                        dropped_no_target_pairs += 1
                        continue
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                    pair_count += 1
                    last_pair_frame_id = frame_id
                    if stop_after_pairs is not None and pair_count >= max(1, int(stop_after_pairs)):
                        break

                if stop_after_pairs is not None and pair_count >= max(1, int(stop_after_pairs)):
                    break
                if sleep_seconds > 0.0:
                    time.sleep(sleep_seconds)
    finally:
        _release_reader(left_reader)
        _release_reader(right_reader)

    return {
        "source": "live_vst_shm",
        "source_alive": bool(seen_left or seen_right),
        "frames_seen_left": len(seen_left),
        "frames_seen_right": len(seen_right),
        "pair_count": pair_count,
        "target_observed": pair_count > 0,
        "dropped_unpaired_left": len(pending_left),
        "dropped_unpaired_right": len(pending_right),
        "dropped_no_target_pairs": dropped_no_target_pairs,
        "read_failures": read_failures,
        "last_pair_frame_id": last_pair_frame_id,
        "output_jsonl": str(out_path),
    }


def build_stereo_bbox_pairs_from_package(
    *,
    package_dir: Path,
    tracker: Any | None = None,
    left_tracker: Any | None = None,
    right_tracker: Any | None = None,
    out_path: Path,
    frame_decoder: Callable[[Nv12Frame], Any] | None = None,
    stop_after_pairs: int | None = None,
) -> dict[str, Any]:
    left_tracker = left_tracker or tracker
    right_tracker = right_tracker or tracker
    if left_tracker is None or right_tracker is None:
        raise ValueError("build_stereo_bbox_pairs_from_package needs tracker or left_tracker/right_tracker")

    package_dir = Path(package_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary = load_stereo_package(package_dir)
    if frame_decoder is None:
        frame_decoder = nv12_frame_to_bgr

    pair_count = 0
    dropped_no_target_pairs = 0
    last_pair_frame_id = -1
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for pair in summary.pairs:
            left_frame = frame_decoder(read_packet_file(pair.left.path, index=pair.left.index))
            right_frame = frame_decoder(read_packet_file(pair.right.path, index=pair.right.index))
            left_tracking_result = left_tracker.process_frame(left_frame)
            right_tracking_result = right_tracker.process_frame(right_frame)
            timestamp_ms = min(pair.left.timestamp_us, pair.right.timestamp_us) // 1000
            record = build_stereo_bbox_pair_record(
                frame_id=pair.frame_id,
                left_frame=left_frame,
                right_frame=right_frame,
                left_tracking_result=left_tracking_result,
                right_tracking_result=right_tracking_result,
                timestamp_ms=timestamp_ms,
                left_source_stats={
                    "record_package": str(package_dir),
                    "packet_index": pair.left.index,
                    "timestamp_us": pair.left.timestamp_us,
                },
                right_source_stats={
                    "record_package": str(package_dir),
                    "packet_index": pair.right.index,
                    "timestamp_us": pair.right.timestamp_us,
                },
            )
            if record is None:
                dropped_no_target_pairs += 1
                continue
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            pair_count += 1
            last_pair_frame_id = pair.frame_id
            if stop_after_pairs is not None and pair_count >= max(1, int(stop_after_pairs)):
                break

    return {
        "source": "stereo_record_package",
        "input_package_dir": str(package_dir),
        "output_jsonl": str(out_path),
        "package_pair_count": summary.pair_count,
        "pair_count": pair_count,
        "target_observed": pair_count > 0,
        "dropped_unpaired_left": summary.dropped_unpaired_left,
        "dropped_unpaired_right": summary.dropped_unpaired_right,
        "dropped_no_target_pairs": dropped_no_target_pairs,
        "last_pair_frame_id": last_pair_frame_id,
    }


def nv12_frame_to_bgr(frame: Nv12Frame) -> Any:
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        raise RuntimeError(
            "record-package mode needs numpy and opencv-python-headless to decode NV12 frames"
        ) from exc

    payload = frame.y_plane + frame.uv_plane
    yuv = np.frombuffer(payload, dtype=np.uint8).reshape((frame.height * 3 // 2, frame.stride))
    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)
    return bgr[:, : frame.width]


def _read_one_eye(reader: Any, pending: dict[int, Any], seen_frame_ids: set[int]) -> int:
    ok, frame_id, frame = reader.read_latest()
    if not ok:
        return 1
    if frame is None or int(frame_id) < 0:
        return 0
    frame_id = int(frame_id)
    if frame_id in seen_frame_ids:
        return 0
    pending[frame_id] = frame
    seen_frame_ids.add(frame_id)
    return 0


def _release_reader(reader: Any) -> None:
    if hasattr(reader, "release"):
        reader.release()


def build_stereo_shm_names(base_name: str) -> tuple[str, str]:
    return (
        resolve_vst_shm_name(base_name, "Left"),
        resolve_vst_shm_name(base_name, "Right"),
    )


def _create_stereo_readers_and_trackers(args: argparse.Namespace) -> tuple[Any, Any, Any, Any]:
    _install_antman_paths(args.antman_root)
    from human_trackor.api import HumanTrackor

    if getattr(args, "vst_reader", "legacy") == "vst_ai_shm":
        left_reader, right_reader = _create_vst_ai_shm_consumer_readers(args)
    else:
        left_reader, right_reader = _create_legacy_stereo_readers(args)
    left_tracker = HumanTrackor(
        model=args.model,
        backend=args.backend,
        imgsz=args.imgsz,
        conf=args.min_confidence,
        device=args.device,
    )
    right_tracker = HumanTrackor(
        model=args.model,
        backend=args.backend,
        imgsz=args.imgsz,
        conf=args.min_confidence,
        device=args.device,
    )
    return left_reader, right_reader, left_tracker, right_tracker


def _create_vst_ai_shm_consumer_readers(args: argparse.Namespace) -> tuple[Any, Any]:
    root = Path(getattr(args, "vst_ai_shm_root", "E:/xia/Antman/0422/0527/P1/vst_ai_shm"))
    value = str(root.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)
    from record_antman_vst_stereo_package import VstAiShmConsumerReader
    from vst_ai_shm_consumer import VstAiShmConsumer

    left = VstAiShmConsumer(
        base_name=args.shm_name,
        namespace=args.shm_namespace,
        eye="Left",
    )
    right = VstAiShmConsumer(
        base_name=args.shm_name,
        namespace=args.shm_namespace,
        eye="Right",
    )
    left.open(wait_for_producer_seconds=args.wait_for_producer_seconds)
    right.open(wait_for_producer_seconds=args.wait_for_producer_seconds)
    return (
        VstAiShmConsumerReader(consumer=left, wait_timeout_ms=args.wait_timeout_ms),
        VstAiShmConsumerReader(consumer=right, wait_timeout_ms=args.wait_timeout_ms),
    )


def _create_legacy_stereo_readers(args: argparse.Namespace) -> tuple[Any, Any]:
    from human_face_visualizer.async_runtime import VstAiShmReader

    left_name, right_name = build_stereo_shm_names(args.shm_name)
    reader_kwargs = {
        "namespace": args.shm_namespace,
        "wait_timeout_ms": args.wait_timeout_ms,
        "wait_for_producer_seconds": args.wait_for_producer_seconds,
    }
    return (
        VstAiShmReader(name=left_name, **reader_kwargs),
        VstAiShmReader(name=right_name, **reader_kwargs),
    )


def _create_tracker(args: argparse.Namespace) -> Any:
    _install_antman_paths(args.antman_root)
    from human_trackor.api import HumanTrackor

    return HumanTrackor(
        model=args.model,
        backend=args.backend,
        imgsz=args.imgsz,
        conf=args.min_confidence,
        device=args.device,
    )


def _create_eye_trackers(args: argparse.Namespace) -> tuple[Any, Any]:
    return _create_tracker(args), _create_tracker(args)


def startup_error_status(exc: Exception, out_path: Path) -> tuple[dict[str, Any], int]:
    if isinstance(exc, ModuleNotFoundError):
        reason = "dependency_unavailable"
        exit_code = 3
    else:
        reason = "vst_source_unavailable"
        exit_code = 1
    return (
        {
            "source_alive": False,
            "frames_seen_left": 0,
            "frames_seen_right": 0,
            "pair_count": 0,
            "target_observed": False,
            "reason": reason,
            "error": str(exc),
            "output_jsonl": str(out_path.resolve()),
        },
        exit_code,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect paired Left/Right Antman VST HumanTrackor bboxes for stereo depth evaluation."
    )
    parser.add_argument("--antman-root", type=Path, default=DEFAULT_ANTMAN_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--input-package",
        type=Path,
        default=None,
        help="Existing stereo record package directory; when set, build bbox pairs offline from the record instead of reading live SHM.",
    )
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    parser.add_argument("--max-read-attempts", type=int, default=6000)
    parser.add_argument("--stop-after-pairs", type=int, default=None)
    parser.add_argument("--require-target", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.005)
    parser.add_argument("--shm-name", default="Antman.VST.AI.v1")
    parser.add_argument("--shm-namespace", default=None)
    parser.add_argument("--wait-timeout-ms", type=int, default=1000)
    parser.add_argument("--wait-for-producer-seconds", type=float, default=10.0)
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--backend", default="ultralytics")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--device", default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.input_package is not None:
        try:
            left_tracker, right_tracker = _create_eye_trackers(args)
            status = build_stereo_bbox_pairs_from_package(
                package_dir=args.input_package,
                left_tracker=left_tracker,
                right_tracker=right_tracker,
                out_path=args.out,
                stop_after_pairs=args.stop_after_pairs,
            )
        except Exception as exc:
            status = {
                "source": "stereo_record_package",
                "target_observed": False,
                "pair_count": 0,
                "reason": "record_package_failed",
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

    try:
        left_reader, right_reader, left_tracker, right_tracker = _create_stereo_readers_and_trackers(args)
    except Exception as exc:
        status, exit_code = startup_error_status(exc, args.out)
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
        return exit_code

    status = collect_stereo_bbox_pairs(
        left_reader=left_reader,
        right_reader=right_reader,
        left_tracker=left_tracker,
        right_tracker=right_tracker,
        out_path=args.out,
        duration_seconds=args.duration_seconds,
        max_read_attempts=args.max_read_attempts,
        stop_after_pairs=args.stop_after_pairs,
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    if not status["source_alive"]:
        return 1
    if args.require_target and not status["target_observed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
