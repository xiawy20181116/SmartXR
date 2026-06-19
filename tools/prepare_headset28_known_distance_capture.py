from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.stereo_depth import (  # noqa: E402
    SCHEMA_VERSION,
    build_known_distance_record,
)
from smartxr.stereo_package import (  # noqa: E402
    load_stereo_metadata,
    load_stereo_package,
    validate_stereo_package,
)


CAPTURE_RUN_FILE = "capture_run.json"
CAPTURE_STATUS_FILE = "capture_status.json"
KNOWN_DISTANCE_GT_FILE = "known_distance_gt.jsonl"


def write_known_distance_capture_run(
    *,
    run_dir: Path,
    stereo_package_dir: Path,
    known_distance_m: float,
    target_id: str,
    recorded_width: int,
    recorded_height: int,
    recorder_status: Mapping[str, Any] | None = None,
    recorder_exit_code: int = 0,
    run_id: str | None = None,
    created_at: str | None = None,
    operator: str = "",
    notes: str = "",
    command: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Write manifest/status files for a controlled #28 known-distance capture."""
    run_dir = Path(run_dir)
    stereo_package_dir = Path(stereo_package_dir)
    known_distance_m = _positive_float(known_distance_m, "known_distance_m")
    recorded_width = _positive_int(recorded_width, "recorded_width")
    recorded_height = _positive_int(recorded_height, "recorded_height")
    target_id = str(target_id).strip()
    if not target_id:
        raise ValueError("target_id must be non-empty")
    if run_id is None:
        run_id = run_dir.name
    if created_at is None:
        created_at = _utc_now()
    recorder_status_dict = dict(recorder_status or {})
    recorder_exit_code = int(recorder_exit_code)

    run_dir.mkdir(parents=True, exist_ok=True)

    validation_errors = validate_stereo_package(stereo_package_dir)
    metadata: dict[str, Any] = {}
    summary = None
    if not validation_errors:
        metadata = load_stereo_metadata(stereo_package_dir)
        summary = load_stereo_package(stereo_package_dir)

    pair_count = _pair_count(recorder_status_dict, summary)
    source_alive = _source_alive(recorder_status_dict, pair_count)
    reason = _reason(
        source_alive=source_alive,
        pair_count=pair_count,
        validation_errors=validation_errors,
        recorder_exit_code=recorder_exit_code,
    )
    ready = reason == "ready_for_depth_error_report"

    gt_records: list[dict[str, Any]] = []
    if ready and summary is not None:
        calibration_ref = str(metadata["calibration"]["id"])
        frame_provenance = str(metadata["frame_provenance"])
        gt_records = [
            build_known_distance_record(
                pair_id=pair.pair_id,
                frame_id=pair.frame_id,
                person_id=target_id,
                known_distance_m=known_distance_m,
                calibration_ref=calibration_ref,
                frame_provenance=frame_provenance,
            )
            for pair in summary.pairs
        ]
        _write_jsonl(run_dir / KNOWN_DISTANCE_GT_FILE, gt_records)
    else:
        stale_gt = run_dir / KNOWN_DISTANCE_GT_FILE
        if stale_gt.exists():
            stale_gt.unlink()

    run_manifest = {
        "schema_version": SCHEMA_VERSION,
        "type": "headset28_known_distance_capture",
        "run_id": run_id,
        "created_at": created_at,
        "device_id": "28",
        "capture_protocol": "known_distance_stereo_vst_v1",
        "known_distance": {
            "distance_m": known_distance_m,
            "target_id": target_id,
            "source": "operator_measurement",
        },
        "stereo_package": {
            "relative_path": _relative_path(stereo_package_dir, run_dir),
            "validation_errors": validation_errors,
            "pair_count": pair_count,
            "gt_record_count": len(gt_records),
            "known_distance_gt_jsonl": (
                KNOWN_DISTANCE_GT_FILE if gt_records else None
            ),
        },
        "recording": {
            "recorded_width": recorded_width,
            "recorded_height": recorded_height,
            "recorder_exit_code": recorder_exit_code,
            "recorder_status": recorder_status_dict,
        },
        "operator": operator,
        "notes": notes,
        "command": list(command or []),
        "raw_capture_policy": "real capture packages stay outside git",
    }
    _write_json(run_dir / CAPTURE_RUN_FILE, run_manifest)

    status = {
        "source_alive": source_alive,
        "ready_for_depth_error_report": ready,
        "reason": reason,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "stereo_package_dir": str(stereo_package_dir),
        "capture_run_json": str(run_dir / CAPTURE_RUN_FILE),
        "capture_status_json": str(run_dir / CAPTURE_STATUS_FILE),
        "known_distance_gt_jsonl": (
            str(run_dir / KNOWN_DISTANCE_GT_FILE) if gt_records else None
        ),
        "known_distance_m": known_distance_m,
        "target_id": target_id,
        "pair_count": pair_count,
        "gt_record_count": len(gt_records),
        "validation_errors": validation_errors,
        "recorder_exit_code": recorder_exit_code,
    }
    _write_json(run_dir / CAPTURE_STATUS_FILE, status)
    return status


def exit_code_from_status(status: Mapping[str, Any]) -> int:
    if status.get("ready_for_depth_error_report") is True:
        return 0
    if status.get("source_alive") is False:
        return 1
    if int(status.get("pair_count", 0)) <= 0:
        return 2
    if status.get("validation_errors"):
        return 4
    return 5


def _pair_count(recorder_status: Mapping[str, Any], summary: Any) -> int:
    if "pair_count" in recorder_status:
        return _non_negative_int(recorder_status["pair_count"], "recorder_status.pair_count")
    if summary is not None:
        return int(summary.pair_count)
    return 0


def _source_alive(recorder_status: Mapping[str, Any], pair_count: int) -> bool:
    if recorder_status:
        return (
            _non_negative_int(recorder_status.get("frames_seen_left", 0), "frames_seen_left") > 0
            and _non_negative_int(recorder_status.get("frames_seen_right", 0), "frames_seen_right") > 0
        )
    return pair_count > 0


def _reason(
    *,
    source_alive: bool,
    pair_count: int,
    validation_errors: Sequence[str],
    recorder_exit_code: int,
) -> str:
    if not source_alive:
        return "vst_source_unavailable"
    if pair_count <= 0:
        return "no_stereo_pairs"
    if validation_errors:
        return "package_invalid"
    if recorder_exit_code != 0:
        return "recorder_failed"
    return "ready_for_depth_error_report"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _positive_float(value: Any, name: str) -> float:
    result = float(value)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive, got {value}")
    return result


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _parse_command(raw: str) -> list[str]:
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError("--command-json must be a JSON array of strings")
    return data


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write SmartXR #28 known-distance capture run metadata."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--stereo-package-dir", type=Path, required=True)
    parser.add_argument("--known-distance-m", type=float, required=True)
    parser.add_argument("--target-id", default="known-target-1")
    parser.add_argument("--recorded-width", type=int, required=True)
    parser.add_argument("--recorded-height", type=int, required=True)
    parser.add_argument("--recorder-status-json", type=Path)
    parser.add_argument("--recorder-exit-code", type=int, default=0)
    parser.add_argument("--run-id")
    parser.add_argument("--operator", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--command-json", default="")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    recorder_status = (
        _read_json(args.recorder_status_json)
        if args.recorder_status_json is not None and args.recorder_status_json.exists()
        else None
    )
    status = write_known_distance_capture_run(
        run_dir=args.run_dir,
        stereo_package_dir=args.stereo_package_dir,
        known_distance_m=args.known_distance_m,
        target_id=args.target_id,
        recorded_width=args.recorded_width,
        recorded_height=args.recorded_height,
        recorder_status=recorder_status,
        recorder_exit_code=args.recorder_exit_code,
        run_id=args.run_id,
        operator=args.operator,
        notes=args.notes,
        command=_parse_command(args.command_json),
    )
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    return exit_code_from_status(status)


if __name__ == "__main__":
    raise SystemExit(main())
