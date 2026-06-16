"""Build the L2 C1 replay fixture from recorded 2D detections (YAN-108).

Reads a detections JSONL (one ``{frame_index, timestamp_ms, detections:[...]}``
line per frame, as produced by ``verify_yolov8n_on_capture.py --dump-*`` from
real VST capture) and runs it through the real C1 producer
(:class:`smartxr.tracking_raw_producer.TrackingRawProducer`), writing one
validated canonical C1 message per frame to a C1 JSONL.

This tool is **dependency-free** (pure ``smartxr``) so it runs under the same
Python as the test suite. The producer configuration below is the pinned recipe
the committed golden fixture (``tracking_raw_replay_c1.jsonl``) is built with;
the L2 test re-runs this exact pipeline and compares against the golden, so it
doubles as a producer drift gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.detection_backend import detections_from_records  # noqa: E402
from smartxr.tracker import HumanTracker  # noqa: E402
from smartxr.tracking_raw_producer import ConstantDepthSource, TrackingRawProducer  # noqa: E402

# Pinned producer recipe for the committed golden fixture.
DEFAULT_DEPTH_M = 1.8
TRACKER_KWARGS = dict(iou_threshold=0.3, n_confirm=3, m_to_lost=1, k_to_delete=10)


def make_producer(depth_m: float = DEFAULT_DEPTH_M) -> TrackingRawProducer:
    return TrackingRawProducer(
        tracker=HumanTracker(**TRACKER_KWARGS),
        depth_source=ConstantDepthSource(depth_m),
        source="replay",
        coordinate_space="vst_right_camera",
    )


def read_detection_frames(path: Path) -> list[dict]:
    frames = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                frames.append(json.loads(line))
    return frames


def build_messages(detection_frames: list[dict], depth_m: float = DEFAULT_DEPTH_M) -> list[dict]:
    producer = make_producer(depth_m)
    messages = []
    for sequence, frame in enumerate(detection_frames):
        detections = detections_from_records(frame.get("detections", []))
        timestamp_ms = float(frame.get("timestamp_ms", sequence))
        messages.append(producer.produce_frame(detections, sequence, timestamp_ms))
    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the L2 C1 replay fixture from recorded detections.")
    parser.add_argument("--input", required=True, type=Path, help="detections JSONL")
    parser.add_argument("--output", required=True, type=Path, help="C1 messages JSONL")
    parser.add_argument("--depth-m", type=float, default=DEFAULT_DEPTH_M)
    args = parser.parse_args(argv)

    frames = read_detection_frames(args.input)
    messages = build_messages(frames, args.depth_m)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as fh:
        for message in messages:
            fh.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")

    nonempty = sum(1 for m in messages if m["detections"])
    print(
        json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "frames": len(messages),
                "frames_with_detections": nonempty,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
