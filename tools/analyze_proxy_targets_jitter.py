from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from capture_vst_target_sample_session import normalize_frame  # noqa: E402
from proxy_targets_smoothing import (  # noqa: E402
    TargetPositionSmoother,
    add_smoothing_arguments,
    smoother_from_args,
)
from vst_proxy_targets_publisher import (  # noqa: E402
    DEFAULT_TARGET_DEPTH_M,
    normalize_source_payload,
)


def load_session_samples(
    path: Path,
    *,
    min_confidence: float = 0.0,
    default_depth_m: float = DEFAULT_TARGET_DEPTH_M,
) -> dict[str, list[dict[str, Any]]]:
    """Replays a recorded humantrackor JSONL session through the exact
    publisher math and returns per-target ordered position samples."""
    samples: dict[str, list[dict[str, Any]]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError(f"session JSONL line must be an object: {path}:{line_number}")
            normalized = normalize_frame(payload, index=line_number, min_confidence=min_confidence)
            message = normalize_source_payload(
                normalized,
                sequence=line_number,
                default_depth_m=default_depth_m,
            )
            for target in message["targets"]:
                transform = target.get("transform", {})
                position = transform.get("position")
                if not isinstance(position, list) or len(position) < 3:
                    continue
                sample: dict[str, Any] = {
                    "sequence": message["sequence"],
                    "timestamp_ms": target.get("timestamp_ms"),
                    "position": [float(position[0]), float(position[1]), float(position[2])],
                }
                source_coordinate = target.get("source_coordinate")
                if isinstance(source_coordinate, dict):
                    frame_info = source_coordinate.get("source_frame", {})
                    sample["pixel_center"] = [
                        float(frame_info.get("center_x", 0.0)),
                        float(frame_info.get("center_y", 0.0)),
                    ]
                samples.setdefault(str(target["target_id"]), []).append(sample)
    if not samples:
        raise ValueError(f"session did not contain any target frames: {path}")
    return samples


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(math.ceil(fraction * len(ordered))) - 1, len(ordered) - 1)
    return ordered[max(index, 0)]


def _delta_stats(deltas: list[float]) -> dict[str, float]:
    return {
        "mean": _mean(deltas),
        "p95": _percentile(deltas, 0.95),
        "max": max(deltas) if deltas else 0.0,
    }


def _angle_between_deg(a: list[float], b: list[float]) -> float:
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if norm_a <= 1e-9 or norm_b <= 1e-9:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)
    return math.degrees(math.acos(min(max(dot, -1.0), 1.0)))


def position_metrics(positions: list[list[float]]) -> dict[str, Any]:
    axes = ["x", "y", "z"]
    deltas = [
        math.dist(positions[index], positions[index - 1])
        for index in range(1, len(positions))
    ]
    angle_deltas = [
        _angle_between_deg(positions[index], positions[index - 1])
        for index in range(1, len(positions))
    ]
    return {
        "frames": len(positions),
        "mean_position_m": [_mean([p[axis] for p in positions]) for axis in range(3)],
        "std_per_axis_m": {
            axes[axis]: _std([p[axis] for p in positions]) for axis in range(3)
        },
        "frame_delta_m": _delta_stats(deltas),
        "frame_delta_deg": _delta_stats(angle_deltas),
    }


def pixel_metrics(pixel_centers: list[list[float]]) -> dict[str, Any] | None:
    if len(pixel_centers) < 2:
        return None
    deltas = [
        math.dist(pixel_centers[index], pixel_centers[index - 1])
        for index in range(1, len(pixel_centers))
    ]
    return {
        "std_x_px": _std([p[0] for p in pixel_centers]),
        "std_y_px": _std([p[1] for p in pixel_centers]),
        "frame_delta_px": _delta_stats(deltas),
    }


def smoothed_positions(
    target_id: str,
    samples: list[dict[str, Any]],
    smoother: TargetPositionSmoother,
) -> list[list[float]]:
    smoother.reset()
    result = []
    for sample in samples:
        timestamp_ms = sample.get("timestamp_ms")
        if not isinstance(timestamp_ms, (int, float)) or isinstance(timestamp_ms, bool):
            timestamp_ms = None
        result.append(smoother.smooth_position(target_id, sample["position"], timestamp_ms))
    return result


def build_report(
    samples_by_target: dict[str, list[dict[str, Any]]],
    smoother: TargetPositionSmoother,
) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for target_id, samples in samples_by_target.items():
        positions = [sample["position"] for sample in samples]
        entry: dict[str, Any] = {"raw": position_metrics(positions)}
        pixel_centers = [sample["pixel_center"] for sample in samples if "pixel_center" in sample]
        pixels = pixel_metrics(pixel_centers)
        if pixels is not None:
            entry["pixel"] = pixels
        if smoother.mode != "none":
            smoothed = smoothed_positions(target_id, samples, smoother)
            entry["smoothed"] = position_metrics(smoothed)
            raw_delta = entry["raw"]["frame_delta_m"]["mean"]
            smoothed_delta = entry["smoothed"]["frame_delta_m"]["mean"]
            entry["jitter_reduction_pct"] = (
                (1.0 - smoothed_delta / raw_delta) * 100.0 if raw_delta > 1e-12 else 0.0
            )
        targets[target_id] = entry
    return {
        "type": "proxy_targets_jitter_report",
        "smoothing": smoother.describe(),
        "targets": targets,
    }


def format_report_summary(report: dict[str, Any]) -> str:
    lines = [f"smoothing: {report['smoothing']}"]
    for target_id, entry in report["targets"].items():
        raw = entry["raw"]
        lines.append(
            "target %s: frames=%d raw_delta_mean=%.4fm p95=%.4fm max=%.4fm angular_mean=%.3fdeg"
            % (
                target_id,
                raw["frames"],
                raw["frame_delta_m"]["mean"],
                raw["frame_delta_m"]["p95"],
                raw["frame_delta_m"]["max"],
                raw["frame_delta_deg"]["mean"],
            )
        )
        pixels = entry.get("pixel")
        if pixels:
            lines.append(
                "  pixel: delta_mean=%.2fpx p95=%.2fpx std_x=%.2fpx std_y=%.2fpx"
                % (
                    pixels["frame_delta_px"]["mean"],
                    pixels["frame_delta_px"]["p95"],
                    pixels["std_x_px"],
                    pixels["std_y_px"],
                )
            )
        smoothed = entry.get("smoothed")
        if smoothed:
            lines.append(
                "  smoothed: delta_mean=%.4fm p95=%.4fm max=%.4fm reduction=%.1f%%"
                % (
                    smoothed["frame_delta_m"]["mean"],
                    smoothed["frame_delta_m"]["p95"],
                    smoothed["frame_delta_m"]["max"],
                    entry.get("jitter_reduction_pct", 0.0),
                )
            )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quantify proxy target jitter from a recorded humantrackor JSONL session, offline."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--default-depth-m", type=float, default=DEFAULT_TARGET_DEPTH_M)
    parser.add_argument("--output", type=Path, default=None)
    add_smoothing_arguments(parser)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    samples = load_session_samples(
        args.input,
        min_confidence=args.min_confidence,
        default_depth_m=args.default_depth_m,
    )
    smoother = smoother_from_args(args)
    report = build_report(samples, smoother)
    print(format_report_summary(report), flush=True)
    if args.output is not None:
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"report written: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
