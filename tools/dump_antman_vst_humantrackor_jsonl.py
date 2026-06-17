from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable


DEFAULT_ANTMAN_ROOT = Path("E:/xia/Antman_smart")
VALID_VST_EYES = {"Left", "Right"}


def resolve_vst_shm_name(base_name: str, eye: str | None) -> str:
    eye_value = "" if eye is None else str(eye).strip()
    base_value = str(base_name).strip()
    if not eye_value:
        return base_value
    if eye_value not in VALID_VST_EYES:
        raise ValueError(f"unsupported VST SHM eye {eye_value!r}; expected Left, Right, or empty legacy eye")
    if base_value.endswith(".Left") or base_value.endswith(".Right"):
        return base_value
    return f"{base_value}.{eye_value}"


def _shape_width_height(frame: Any) -> tuple[int, int]:
    shape = getattr(frame, "shape", None)
    if isinstance(shape, tuple) and len(shape) >= 2:
        return int(shape[1]), int(shape[0])
    return 0, 0


def _person_value(person: Any, name: str, fallback: Any = None) -> Any:
    if isinstance(person, dict):
        return person.get(name, fallback)
    return getattr(person, name, fallback)


def _person_to_dict(person: Any) -> dict[str, Any]:
    bbox = _person_value(person, "bbox", (0, 0, 0, 0))
    return {
        "track_id": int(_person_value(person, "track_id", 0)),
        "bbox": [int(value) for value in bbox],
        "confidence": float(_person_value(person, "confidence", 0.0)),
        "tracking_status": str(_person_value(person, "tracking_status", "tracked")),
    }


def build_frame_record(
    *,
    frame: Any,
    frame_id: int,
    timestamp_ms: int,
    tracking_result: Any,
    source_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    width, height = _shape_width_height(frame)
    people = [_person_to_dict(person) for person in getattr(tracking_result, "people", [])]
    record: dict[str, Any] = {
        "source": "vst",
        "frame_id": int(frame_id),
        "timestamp_ms": int(timestamp_ms),
        "image_width": width,
        "image_height": height,
        "people": people,
        "tracker": {
            "frame_index": int(getattr(tracking_result, "frame_index", frame_id)),
            "frame_latency_ms": float(getattr(tracking_result, "frame_latency_ms", 0.0)),
        },
        "pose_quality": "projected_2d",
    }
    if source_stats:
        record["source_stats"] = source_stats
    return record


def dump_vst_humantrackor_jsonl(
    *,
    reader: Any,
    tracker: Any,
    out_path: Path,
    duration_seconds: float,
    stop_after_first_target_frames: int = 10,
    sleep_seconds: float = 0.005,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started = clock()
    frames_written = 0
    empty_frames = 0
    target_observed = False
    first_target_frame: int | None = None
    frames_after_first_target = 0
    last_frame_id = -1

    try:
        with out_path.open("w", encoding="utf-8", newline="\n") as handle:
            while clock() - started < duration_seconds:
                ok, frame_id, frame = reader.read_latest()
                if not ok:
                    break
                if frame is None or int(frame_id) < 0:
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)
                    continue

                tracking_result = tracker.process_frame(frame)
                source_stats = reader.get_stats() if hasattr(reader, "get_stats") else {}
                timestamp_ms = int(time.time() * 1000)
                record = build_frame_record(
                    frame=frame,
                    frame_id=int(frame_id),
                    timestamp_ms=timestamp_ms,
                    tracking_result=tracking_result,
                    source_stats=source_stats,
                )
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                frames_written += 1
                last_frame_id = int(frame_id)

                if record["people"]:
                    if not target_observed:
                        first_target_frame = int(frame_id)
                    target_observed = True
                    frames_after_first_target += 1
                else:
                    empty_frames += 1

                if target_observed and frames_after_first_target >= max(1, int(stop_after_first_target_frames)):
                    break
    finally:
        if hasattr(reader, "release"):
            reader.release()

    if frames_written == 0:
        reason = "no_frames_seen"
    elif target_observed:
        reason = "target_observed"
    else:
        reason = "no_target_observed"

    return {
        "source_alive": frames_written > 0,
        "frames_written": frames_written,
        "empty_frames": empty_frames,
        "target_observed": target_observed,
        "first_target_frame": first_target_frame,
        "last_frame_id": last_frame_id,
        "reason": reason,
        "output_jsonl": str(out_path),
    }


def _install_antman_paths(antman_root: Path) -> None:
    for path in (antman_root / "demo" / "src", antman_root / "human_detect"):
        value = str(path.resolve())
        if value not in sys.path:
            sys.path.insert(0, value)


def _create_live_reader_and_tracker(args: argparse.Namespace) -> tuple[Any, Any]:
    _install_antman_paths(args.antman_root)
    from human_face_visualizer.async_runtime import VstAiShmReader
    from human_trackor.api import HumanTrackor

    shm_name = resolve_vst_shm_name(args.shm_name, getattr(args, "shm_eye", "Right"))
    reader = VstAiShmReader(
        name=shm_name,
        namespace=args.shm_namespace,
        wait_timeout_ms=args.wait_timeout_ms,
        wait_for_producer_seconds=args.wait_for_producer_seconds,
    )
    tracker = HumanTrackor(
        model=args.model,
        backend=args.backend,
        imgsz=args.imgsz,
        conf=args.min_confidence,
        device=args.device,
    )
    return reader, tracker


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
            "frames_written": 0,
            "empty_frames": 0,
            "target_observed": False,
            "first_target_frame": None,
            "last_frame_id": -1,
            "reason": reason,
            "error": str(exc),
            "output_jsonl": str(out_path.resolve()),
        },
        exit_code,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump Antman VST SHM + HumanTrackor results as SmartXR JSONL.")
    parser.add_argument("--antman-root", type=Path, default=DEFAULT_ANTMAN_ROOT)
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--require-target", action="store_true")
    parser.add_argument("--stop-after-first-target-frames", type=int, default=10)
    parser.add_argument("--shm-name", default="Antman.VST.AI.v1")
    parser.add_argument("--shm-eye", default="Right", help='VST eye suffix: "Right", "Left", or "" for legacy unsuffixed SHM')
    parser.add_argument("--shm-namespace", default=None)
    parser.add_argument("--wait-timeout-ms", type=int, default=1000)
    parser.add_argument("--wait-for-producer-seconds", type=float, default=10.0)
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--backend", default="ultralytics")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--device", default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        reader, tracker = _create_live_reader_and_tracker(args)
    except Exception as exc:
        status, exit_code = startup_error_status(exc, args.out)
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
        return exit_code
    status = dump_vst_humantrackor_jsonl(
        reader=reader,
        tracker=tracker,
        out_path=args.out,
        duration_seconds=args.duration_seconds,
        stop_after_first_target_frames=args.stop_after_first_target_frames,
    )
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    if not status["source_alive"]:
        return 1
    if args.require_target and not status["target_observed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
