from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from monitor_proxy_targets_live_stream import monitor_stream, status_from_exception  # noqa: E402


def validate_depth_confidence_status(
    status: dict[str, Any],
    require_confidences: list[str],
    forbid_confidences: list[str],
    require_depth_fields: bool,
) -> list[str]:
    errors = list(status.get("errors", []))
    if not status.get("ok", False):
        errors.append("stream monitor status is not ok")

    depth_confidences = status.get("depth_confidences", {})
    if not isinstance(depth_confidences, dict):
        depth_confidences = {}

    for confidence in require_confidences:
        if int(depth_confidences.get(confidence, 0)) <= 0:
            errors.append(f"required depth_confidence missing: {confidence}")
    for confidence in forbid_confidences:
        count = int(depth_confidences.get(confidence, 0))
        if count > 0:
            errors.append(f"forbidden depth_confidence present: {confidence}={count}")

    if require_depth_fields:
        missing_confidence = int(status.get("missing_depth_confidence_count", 0))
        missing_source = int(status.get("missing_depth_source_count", 0))
        if missing_confidence > 0:
            errors.append(f"targets missing depth_confidence: {missing_confidence}")
        if missing_source > 0:
            errors.append(f"targets missing depth_source: {missing_source}")

    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate depth_source/depth_confidence on a live proxy_targets stream.")
    parser.add_argument("--url", default="ws://127.0.0.1:8766/proxy_targets")
    parser.add_argument("--min-packets", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--subscribe-stream", default="proxy_targets")
    parser.add_argument("--require-confidence", action="append", default=[])
    parser.add_argument("--forbid-confidence", action="append", default=["none"])
    parser.add_argument("--require-depth-fields", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        status = monitor_stream(
            args.url,
            min_packets=max(1, args.min_packets),
            timeout_seconds=max(0.1, args.timeout_seconds),
            subscribe_stream=args.subscribe_stream,
        )
    except Exception as exc:
        status = status_from_exception(exc, args.url, args.timeout_seconds)

    validation_errors = validate_depth_confidence_status(
        status,
        require_confidences=args.require_confidence,
        forbid_confidences=args.forbid_confidence,
        require_depth_fields=args.require_depth_fields,
    )
    status["depth_confidence_validation_ok"] = not validation_errors
    status["depth_confidence_validation_errors"] = validation_errors

    text = json.dumps(status, ensure_ascii=False, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if not validation_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
