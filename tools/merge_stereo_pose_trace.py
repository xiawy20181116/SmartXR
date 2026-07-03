"""Merge offline stereo package frame timing with a pose JSONL trace."""

from __future__ import annotations

import argparse
from bisect import bisect_left
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from smartxr.pose_recording import normalize_pose_row, sync_quality
from smartxr.stereo_depth import format_pair_id

SCHEMA_VERSION = 1
TIMESTAMP_KIND = "godot_sample_time"
POSE_TIME_CLOCK = "system_unix_time_usec"
READ_TIME_SOURCE = "read_system_unix_time_us_midpoint"
EXPOSURE_SOURCE = "exposure_midpoint"


def merge_pose_trace(package_dir: Path, pose_trace: Path, output: Path) -> dict:
    """Write frame-to-nearest-pose associations for a stereo package."""
    package_dir = Path(package_dir)
    pose_trace = Path(pose_trace)
    output = Path(output)

    left = _read_metadata(package_dir / "left" / "metadata.json")
    right = _read_metadata(package_dir / "right" / "metadata.json")
    poses = _read_pose_trace(pose_trace)
    if not poses:
        raise ValueError("pose_trace must contain at least one pose row")
    pose_times_us = [int(pose["pose_time_us"]) for pose in poses]

    rows = []
    for frame_id in sorted(set(left) & set(right)):
        left_frame = left[frame_id]
        right_frame = right[frame_id]
        frame_mid_exposure_us = (left_frame["exposure_us"] + right_frame["exposure_us"]) // 2
        match_time_us, source = _frame_match_time_us(left_frame, right_frame, frame_mid_exposure_us)
        pose = _nearest_pose(poses, pose_times_us, match_time_us)
        delta_ms = abs(int(pose["pose_time_us"]) - match_time_us) / 1000.0
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "pair_id": format_pair_id(frame_id),
                "frame_id": frame_id,
                "left_exposure_us": left_frame["exposure_us"],
                "right_exposure_us": right_frame["exposure_us"],
                "frame_mid_exposure_us": frame_mid_exposure_us,
                "frame_match_time_source": source,
                "frame_match_time_us": match_time_us,
                "matched_pose_sample_index": int(pose["sample_index"]),
                "matched_pose_time_us": int(pose["pose_time_us"]),
                "matched_pose_delta_ms": delta_ms,
                "timestamp_kind": pose["timestamp_kind"],
                "pose_time_clock": pose["pose_time_clock"],
                "sync_quality": sync_quality(delta_ms),
                "world_from_head": pose["world_from_head"],
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    return {"rows_written": len(rows)}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _read_metadata(path: Path) -> dict[int, dict[str, int | None]]:
    metadata = _read_json(path)
    frame_ids = _int_list(metadata, "frame_ids")
    timestamps_us = _int_list(metadata, "timestamps_us")
    if len(frame_ids) != len(timestamps_us):
        raise ValueError(f"{path} frame_ids count must match timestamps_us count")

    read_times = None
    if "read_system_unix_time_us" in metadata:
        read_times = _int_list(metadata, "read_system_unix_time_us")
        if len(read_times) != len(frame_ids):
            raise ValueError(
                f"{path} read_system_unix_time_us count must match frame_ids count"
            )

    by_frame_id: dict[int, dict[str, int | None]] = {}
    for index, frame_id in enumerate(frame_ids):
        if frame_id in by_frame_id:
            raise ValueError(f"{path} duplicate frame_id {frame_id}")
        by_frame_id[frame_id] = {
            "exposure_us": timestamps_us[index],
            "read_system_unix_time_us": None if read_times is None else read_times[index],
        }
    return by_frame_id


def _int_list(metadata: Mapping[str, Any], field: str) -> list[int]:
    value = metadata.get(field)
    if not isinstance(value, list):
        raise ValueError(f"metadata.{field} must be a list")
    return [_to_int(item, f"metadata.{field}[{index}]") for index, item in enumerate(value)]


def _to_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if not number.is_integer():
        raise ValueError(f"{field} must be an integer")
    return int(number)


def _read_pose_trace(path: Path) -> list[dict[str, Any]]:
    poses = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} invalid JSON") from exc
            pose = normalize_pose_row(row)
            if pose["schema_version"] != SCHEMA_VERSION:
                raise ValueError(
                    f"{path}:{line_number} schema_version must be {SCHEMA_VERSION}"
                )
            if pose["timestamp_kind"] != TIMESTAMP_KIND:
                raise ValueError(
                    f"{path}:{line_number} timestamp_kind must be {TIMESTAMP_KIND!r}"
                )
            if pose["pose_time_clock"] != POSE_TIME_CLOCK:
                raise ValueError(
                    f"{path}:{line_number} pose_time_clock must be {POSE_TIME_CLOCK!r}"
                )
            poses.append(pose)
    return sorted(poses, key=lambda row: int(row["pose_time_us"]))


def _frame_match_time_us(
    left_frame: Mapping[str, int | None],
    right_frame: Mapping[str, int | None],
    fallback_us: int,
) -> tuple[int, str]:
    left_read_time = left_frame.get("read_system_unix_time_us")
    right_read_time = right_frame.get("read_system_unix_time_us")
    if left_read_time is not None and right_read_time is not None:
        return (int(left_read_time) + int(right_read_time)) // 2, READ_TIME_SOURCE
    return fallback_us, EXPOSURE_SOURCE


def _nearest_pose(
    poses: list[dict[str, Any]],
    pose_times_us: list[int],
    target_us: int,
) -> dict[str, Any]:
    index = bisect_left(pose_times_us, target_us)
    if index <= 0:
        return poses[0]
    if index >= len(poses):
        return poses[-1]

    before_index = index - 1
    before_delta = target_us - pose_times_us[before_index]
    after_delta = pose_times_us[index] - target_us
    if before_delta <= after_delta:
        return poses[before_index]
    return poses[index]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--pose-trace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = merge_pose_trace(args.package_dir, args.pose_trace, args.output)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
