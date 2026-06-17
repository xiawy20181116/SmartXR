"""Module 3 display wiring: convert C1 tracking_raw -> C2 proxy_targets.

Reads a C1 ``tracking_raw`` payload (a single JSON message or a ``.jsonl`` stream
of them, e.g. the output of ``smartxr.tracking_raw_producer`` /
``tools/build_tracking_raw_replay_fixture.py``), applies the module-3 camera->head
alignment, and writes canonical C2 ``proxy_targets`` messages that the existing
proxy_targets WebSocket / Godot card path consumes. Both ends are validated: a C1
input that violates its schema and a C2 output that violates its schema are hard
errors, so this bridge cannot silently emit a bad payload.

Empty C1 frames (no people -- a valid state) produce no C2 message and are
reported as skipped rather than emitted as an invalid empty proxy_targets.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from smartxr.mr_integration import (
    Calibration,
    TrackingRawToProxyTargetsConverter,
)
from smartxr.schema import validate_message as validate_proxy_targets
from smartxr.tracking_raw_schema import validate_message as validate_tracking_raw


def _load_calibration(matrix_path: Path | None) -> Calibration:
    if matrix_path is None:
        return Calibration.monocular()
    data = json.loads(matrix_path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("right_eye_to_head", data.get("matrix"))
    if not isinstance(data, list):
        raise ValueError(
            f"{matrix_path}: expected a 16-element right_eye_to_head matrix "
            "(a JSON array, or an object with a 'right_eye_to_head' key)"
        )
    return Calibration.with_right_eye_to_head(data)


def _iter_input_messages(input_path: Path):
    if input_path.suffix.lower() == ".jsonl":
        with input_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                yield line_number, json.loads(text)
    else:
        yield 1, json.loads(input_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert C1 tracking_raw payloads to C2 proxy_targets (module 3)."
    )
    parser.add_argument("--input", required=True, type=Path, help="C1 JSON or JSONL file.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="C2 output file (.jsonl for a stream, .json for a single message). "
        "Defaults to stdout.",
    )
    parser.add_argument(
        "--right-eye-to-head",
        type=Path,
        default=None,
        help="Optional JSON file with a 16-element right_eye_to_head matrix "
        "(binocular calibration). Default: v1 monocular axis flip.",
    )
    parser.add_argument("--card-id", default="CardAnchor", help="C2 card id (default: CardAnchor).")
    parser.add_argument("--min-confidence", type=float, default=0.0, help="Drop detections below this confidence.")
    parser.add_argument(
        "--stale-after-ms",
        type=float,
        default=None,
        help="Downgrade a tracked target to 'stale' when its pose lags the frame by more than this.",
    )
    parser.add_argument("--diagnostics", action="store_true", help="Include per-target mr_alignment diagnostics.")
    args = parser.parse_args(argv)

    converter = TrackingRawToProxyTargetsConverter(
        _load_calibration(args.right_eye_to_head),
        card_id=args.card_id,
        stale_after_ms=args.stale_after_ms,
        min_confidence=args.min_confidence,
        include_diagnostics=args.diagnostics,
    )

    outputs: list[dict] = []
    converted = 0
    skipped_empty = 0
    for line_number, message in _iter_input_messages(args.input):
        c1_errors = validate_tracking_raw(message)
        if c1_errors:
            print(f"{args.input}:{line_number}: invalid C1 input")
            for error in c1_errors:
                print(f"  - {error}")
            return 1
        c2 = converter.convert(message)
        if c2 is None:
            skipped_empty += 1
            continue
        c2_errors = validate_proxy_targets(c2)
        if c2_errors:
            print(f"{args.input}:{line_number}: converter produced an invalid C2 message")
            for error in c2_errors:
                print(f"  - {error}")
            return 1
        outputs.append(c2)
        converted += 1

    if args.output is None:
        for c2 in outputs:
            print(json.dumps(c2))
    elif args.output.suffix.lower() == ".jsonl":
        with args.output.open("w", encoding="utf-8") as handle:
            for c2 in outputs:
                handle.write(json.dumps(c2) + "\n")
    else:
        # Single-message JSON: require exactly one converted message.
        if len(outputs) != 1:
            print(
                f"--output {args.output} is a single-message .json but {len(outputs)} "
                "messages were produced; use a .jsonl output for a stream."
            )
            return 1
        args.output.write_text(json.dumps(outputs[0], indent=2) + "\n", encoding="utf-8")

    print(f"converted={converted} skipped_empty={skipped_empty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
