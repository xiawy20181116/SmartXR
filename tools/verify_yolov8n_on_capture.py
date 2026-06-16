"""Run yolov8n (ncnn) over the recorded VST captures and report person recall.

This is module 1's "first step": prove the on-device detector actually finds
people on real VST imagery, and decide whether T3 frame annotation is needed
(YAN-96 data-tiering thread). It also dumps a contiguous window of real
detections as a JSONL the L2 replay fixture is built from -- so the C1 fixture
comes from real capture without committing ~10 GB of frames or adding a runtime
dependency.

Needs the optional detection deps (numpy, opencv, ncnn) -- run from the uv venv,
e.g.::

    .venv-detect/Scripts/python.exe tools/verify_yolov8n_on_capture.py \
        --capture-root "E:\\...\\fixed_replay_captures-20260429-194546" \
        --report-out docs/yolov8n_vst_verification.json --step 15

    .venv-detect/Scripts/python.exe tools/verify_yolov8n_on_capture.py \
        --capture-root "E:\\..." --dump-session capture_20260417T073836Z \
        --dump-start 600 --dump-count 200 \
        --dump-out godot-android/fixtures/tracking_raw_replay_detections.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.nv12_reader import parse_header, session_packet_paths  # noqa: E402

DEFAULT_PARAM = _ROOT / "godot-android" / "ncnn" / "yolov8n_320.opt.ncnn.param"
DEFAULT_BIN = _ROOT / "godot-android" / "ncnn" / "yolov8n_320.opt.ncnn.bin"


def _make_detector(args):
    from yolov8n_ncnn_detector import Yolov8nNcnnDetector  # tools/ on sys.path

    return Yolov8nNcnnDetector(
        Path(args.param), Path(args.bin), conf_threshold=args.conf
    )


def _session_dirs(capture_root: Path) -> list[Path]:
    captures = capture_root / "captures"
    base = captures if captures.is_dir() else capture_root
    return sorted(p for p in base.iterdir() if p.is_dir() and (p / "nv12_packets").is_dir())


def sweep(args) -> dict:
    detector = _make_detector(args)
    capture_root = Path(args.capture_root)
    report = {"capture_root": str(capture_root), "conf_threshold": args.conf, "step": args.step, "sessions": []}
    for session in _session_dirs(capture_root):
        paths = session_packet_paths(session)
        total = len(paths)
        sampled = 0
        with_person = 0
        person_counts: dict[int, int] = {}
        max_conf = 0.0
        conf_sum = 0.0
        det_total = 0
        for path in paths[:: args.step]:
            dets = detector.detect_nv12(path.read_bytes())
            sampled += 1
            n = len(dets)
            person_counts[n] = person_counts.get(n, 0) + 1
            if n:
                with_person += 1
                det_total += n
                for d in dets:
                    max_conf = max(max_conf, d["confidence"])
                    conf_sum += d["confidence"]
        entry = {
            "session": session.name,
            "frames_total": total,
            "frames_sampled": sampled,
            "frames_with_person": with_person,
            "person_recall_pct": round(100.0 * with_person / sampled, 1) if sampled else 0.0,
            "person_count_histogram": {str(k): v for k, v in sorted(person_counts.items())},
            "max_confidence": round(max_conf, 4),
            "mean_confidence": round(conf_sum / det_total, 4) if det_total else 0.0,
        }
        report["sessions"].append(entry)
        print(json.dumps(entry, ensure_ascii=False))
    return report


def dump_window(args) -> dict:
    detector = _make_detector(args)
    session = Path(args.capture_root) / "captures" / args.dump_session
    if not session.is_dir():
        session = Path(args.capture_root) / args.dump_session
    paths = session_packet_paths(session)
    window = paths[args.dump_start : args.dump_start + args.dump_count]
    out_path = Path(args.dump_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    frames_with_person = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        for offset, path in enumerate(window):
            raw = path.read_bytes()
            header = parse_header(raw)
            dets = detector.detect_nv12(raw)
            if dets:
                frames_with_person += 1
            line = {
                "frame_index": args.dump_start + offset + 1,
                "timestamp_ms": round(header["timestamp_us"] / 1000.0, 3),
                "detections": dets,
            }
            fh.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
            written += 1
    summary = {
        "dump_out": str(out_path),
        "session": session.name,
        "start": args.dump_start,
        "frames_written": written,
        "frames_with_person": frames_with_person,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run yolov8n over VST captures and report person recall.")
    parser.add_argument("--capture-root", required=True)
    parser.add_argument("--param", default=str(DEFAULT_PARAM))
    parser.add_argument("--bin", default=str(DEFAULT_BIN))
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--step", type=int, default=15, help="sweep: sample every Nth frame")
    parser.add_argument("--report-out", help="sweep: write the JSON report here")
    parser.add_argument("--dump-session", help="dump mode: session id to extract detections from")
    parser.add_argument("--dump-start", type=int, default=0)
    parser.add_argument("--dump-count", type=int, default=200)
    parser.add_argument("--dump-out", help="dump mode: detections JSONL output path")
    args = parser.parse_args(argv)

    if args.dump_session:
        if not args.dump_out:
            parser.error("--dump-out is required with --dump-session")
        dump_window(args)
        return 0

    report = sweep(args)
    if args.report_out:
        Path(args.report_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"report written to {args.report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
