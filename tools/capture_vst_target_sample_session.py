from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.frames import normalize_frame  # noqa: E402,F401


SESSION_FILE = "vst_capture_session.jsonl"
FIRST_TARGET_FILE = "vst_first_target_sample.json"
STATUS_FILE = "vst_capture_status.json"


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
