"""Full PC chain: NV12 session -> PC-offload yolov8n -> producer -> live C1 WS.

This is the real "PC-offload" topology end to end, on a recorded VST session and
with no device: it decodes NV12 packets, runs the ncnn `yolov8n_320` person
detector, and feeds the detections to the same C1 publisher serve loop used by
`smartxr.cli.tracking_raw_publisher` -- so module 3 can subscribe to a **live**
C1 stream produced from real camera frames.

Needs the optional detection deps (numpy, opencv, ncnn). Run from the uv venv::

    .venv-detect/Scripts/python.exe tools/run_tracking_raw_live_publisher.py \
        --capture-root "E:\\...\\fixed_replay_captures-20260429-194546" \
        --session capture_20260415T065340Z --start 350 --count 200 \
        --port 8770 --hz 20

Consume it with the dependency-free harness::

    python -m smartxr.cli.tracking_raw_monitor --url ws://127.0.0.1:8770/tracking_raw --min-packets 30
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from smartxr.cli.tracking_raw_publisher import serve  # noqa: E402
from smartxr.nv12_reader import parse_header, session_packet_paths  # noqa: E402

DEFAULT_PARAM = _ROOT / "godot-android" / "ncnn" / "yolov8n_320.opt.ncnn.param"
DEFAULT_BIN = _ROOT / "godot-android" / "ncnn" / "yolov8n_320.opt.ncnn.bin"


def _session_dir(capture_root: Path, session: str) -> Path:
    candidate = capture_root / "captures" / session
    return candidate if candidate.is_dir() else capture_root / session


def make_nv12_source(
    capture_root: Path, session: str, start: int, count: int, conf: float,
    param_path: Path, bin_path: Path,
):
    """Factory returning a fresh NV12 -> ncnn detection iterator per connection."""
    from yolov8n_ncnn_detector import Yolov8nNcnnDetector  # tools/ on sys.path

    session_dir = _session_dir(capture_root, session)
    paths = session_packet_paths(session_dir)[start : start + count]

    def _iter():
        detector = Yolov8nNcnnDetector(param_path, bin_path, conf_threshold=conf)
        for path in paths:
            raw = path.read_bytes()
            header = parse_header(raw)
            records = detector.detect_nv12(raw)
            yield header["timestamp_us"] / 1000.0, records

    return _iter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live C1 WS publisher from an NV12 session via ncnn yolov8n.")
    parser.add_argument("--capture-root", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--param", default=str(DEFAULT_PARAM))
    parser.add_argument("--bin", default=str(DEFAULT_BIN))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--depth-m", type=float, default=1.8)
    parser.add_argument("--log-every", type=int, default=20)
    args = parser.parse_args(argv)

    make_source = make_nv12_source(
        Path(args.capture_root), args.session, args.start, args.count, args.conf,
        Path(args.param), Path(args.bin),
    )
    serve(args.host, args.port, make_source, hz=args.hz, depth_m=args.depth_m, log_every=args.log_every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
