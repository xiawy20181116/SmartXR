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
from smartxr.stereo_package import load_stereo_package  # noqa: E402


def _people_from_tracking_result(tracking_result: Any) -> list[dict[str, Any]]:
    return [_person_to_dict(person) for person in getattr(tracking_result, "people", [])]


def _best_person(people: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not people:
        return None
    return max(people, key=lambda person: float(person.get("confidence", 0.0)))


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
    left_person = _best_person(left["people"])
    right_person = _best_person(right["people"])
    if left_person is None or right_person is None:
        return None

    left_track_id = int(left_person.get("track_id", 0))
    right_track_id = int(right_person.get("track_id", 0))
    confidence = min(
        float(left_person.get("confidence", 0.0)),
        float(right_person.get("confidence", 0.0)),
    )
    return {
        "source": "vst_stereo_bbox",
        "schema_version": 1,
        "pair_id": f"pair-{int(frame_id):06d}",
        "frame_id": int(frame_id),
        "person_id": f"person-{left_track_id}-{right_track_id}",
        "timestamp_ms": int(timestamp_ms),
        "left_bbox_xyxy": [int(value) for value in left_person["bbox"]],
        "right_bbox_xyxy": [int(value) for value in right_person["bbox"]],
        "confidence": confidence,
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
    from human_face_visualizer.async_runtime import VstAiShmReader
    from human_trackor.api import HumanTrackor

    left_name, right_name = build_stereo_shm_names(args.shm_name)
    reader_kwargs = {
        "namespace": args.shm_namespace,
        "wait_timeout_ms": args.wait_timeout_ms,
        "wait_for_producer_seconds": args.wait_for_producer_seconds,
    }
    left_reader = VstAiShmReader(name=left_name, **reader_kwargs)
    right_reader = VstAiShmReader(name=right_name, **reader_kwargs)
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
