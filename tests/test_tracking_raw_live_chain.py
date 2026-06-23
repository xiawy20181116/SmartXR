"""Tests for the live C1 (tracking_raw) WebSocket chain (YAN-108 PC chain).

Covers the dependency-free publisher + consumer harness: the message analyzer,
the detection-JSONL source, exception classification, the PS1 runners, and a
real end-to-end socket round-trip (publisher thread -> monitor client) over the
committed real-capture detection fixture. No ncnn/numpy, no device.
"""

from __future__ import annotations

import socket
import threading
import time
import unittest
from pathlib import Path

from smartxr.cli import tracking_raw_monitor as mon
from smartxr.cli import tracking_raw_publisher as pub
from smartxr.tracker import HumanTracker
from smartxr.tracking_raw_producer import TrackingRawProducer

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "godot-android" / "fixtures" / "tracking_raw_replay_detections.jsonl"
HARNESS_PS1 = ROOT / "tools" / "run_tracking_raw_live_harness.ps1"
PC_CHAIN_PS1 = ROOT / "tools" / "run_tracking_raw_pc_chain.ps1"
LIVE_DRIVER = ROOT / "tools" / "run_tracking_raw_live_publisher.py"


def _build_stream(records_per_frame: list[list[dict]]) -> list[dict]:
    producer = TrackingRawProducer(HumanTracker(n_confirm=2))
    out = []
    for seq, recs in enumerate(records_per_frame):
        from smartxr.detection_backend import detections_from_records

        out.append(producer.produce_frame(detections_from_records(recs), seq, seq * 33.0))
    return out


class AnalyzeTests(unittest.TestCase):
    def test_healthy_stream_is_ok(self):
        person = [{"bbox": [0.4, 0.3, 0.2, 0.5], "confidence": 0.9}]
        stream = _build_stream([person, person, person, [], person])
        status = mon.analyze_c1_messages(stream, min_packets=5)
        self.assertTrue(status["ok"], status["errors"])
        self.assertEqual(status["packets"], 5)
        self.assertEqual(status["accepted"], 5)
        self.assertEqual(status["rejected"], 0)
        self.assertTrue(status["sequence_contiguous"])
        self.assertIn("person-1", status["track_ids"])
        self.assertIn("confirmed", status["lifecycle_states"])
        self.assertEqual(status["errors"], [])

    def test_too_few_packets_flagged(self):
        person = [{"bbox": [0.4, 0.3, 0.2, 0.5], "confidence": 0.9}]
        stream = _build_stream([person, person])
        status = mon.analyze_c1_messages(stream, min_packets=5)
        self.assertFalse(status["ok"])
        self.assertTrue(any("not enough packets" in e for e in status["errors"]))

    def test_schema_violation_and_rejection_flagged(self):
        person = [{"bbox": [0.4, 0.3, 0.2, 0.5], "confidence": 0.9}]
        stream = _build_stream([person, person, person])
        # Corrupt one message: forbidden raw 2D field leaks in.
        stream[1]["detections"][0]["bbox"] = [1, 2, 3, 4]
        status = mon.analyze_c1_messages(stream, min_packets=3)
        self.assertFalse(status["ok"])
        self.assertEqual(status["rejected"], 1)
        self.assertTrue(any("raw source field" in e for e in status["errors"]))

    def test_sequence_gap_flagged(self):
        person = [{"bbox": [0.4, 0.3, 0.2, 0.5], "confidence": 0.9}]
        stream = _build_stream([person, person, person])
        stream[2]["sequence"] = 99
        status = mon.analyze_c1_messages(stream, min_packets=3)
        self.assertFalse(status["ok"])
        self.assertFalse(status["sequence_contiguous"])

    def test_status_from_connection_refused(self):
        status = mon.status_from_exception(
            ConnectionRefusedError(10061, "refused"), mon.DEFAULT_URL, 10.0
        )
        self.assertFalse(status["ok"])
        self.assertEqual(status["reason"], "connection_refused")
        self.assertIn("tracking_raw_publisher", status["hint"])


class DetectionSourceTests(unittest.TestCase):
    def test_iter_detection_jsonl_no_loop(self):
        frames = list(pub.iter_detection_jsonl(FIXTURE, loop=False))
        self.assertGreaterEqual(len(frames), 100)
        ts, records = frames[0]
        self.assertIsInstance(records, list)
        # Each item is (timestamp_ms, records).
        self.assertTrue(any(recs for _ts, recs in frames))
        self.assertTrue(any(not recs for _ts, recs in frames))

    def test_iter_detection_jsonl_loops(self):
        n = len(list(pub.iter_detection_jsonl(FIXTURE, loop=False)))
        looped = pub.iter_detection_jsonl(FIXTURE, loop=True)
        collected = [next(looped) for _ in range(n + 5)]
        self.assertEqual(len(collected), n + 5)  # wrapped past the end


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class EndToEndSocketTests(unittest.TestCase):
    def test_live_publisher_to_monitor_roundtrip(self):
        port = _free_port()
        make_source = pub.make_detection_jsonl_source(FIXTURE, loop=True)
        server = threading.Thread(
            target=pub.serve,
            kwargs=dict(host="127.0.0.1", port=port, make_source=make_source, hz=400.0, log_every=0),
            daemon=True,
        )
        server.start()

        url = f"ws://127.0.0.1:{port}/tracking_raw"
        # Retry until the listener is up, then read a window large enough to
        # reach the dense (multi-person, confirmed) middle of the capture.
        status = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                status = mon.monitor_stream(url, min_packets=130, timeout_seconds=8.0)
                break
            except ConnectionRefusedError:
                time.sleep(0.1)
        self.assertIsNotNone(status, "publisher never accepted a connection")
        self.assertTrue(status["ok"], status["errors"])
        self.assertEqual(status["rejected"], 0)
        self.assertTrue(status["sequence_contiguous"])
        self.assertIsInstance(status["first_sequence"], int)
        self.assertEqual(status["last_sequence"], status["first_sequence"] + status["packets"] - 1)
        self.assertGreaterEqual(len(status["track_ids"]), 1)
        self.assertIn("confirmed", status["lifecycle_states"])


class RunnerContractTests(unittest.TestCase):
    def test_harness_runner_wires_publisher_and_monitor(self):
        src = HARNESS_PS1.read_text(encoding="utf-8")
        self.assertIn("smartxr.cli.tracking_raw_publisher", src)
        self.assertIn("smartxr.cli.tracking_raw_monitor", src)
        self.assertIn("/tracking_raw", src)
        self.assertIn("--min-packets", src)

    def test_pc_chain_runner_uses_nv12_driver_and_venv(self):
        src = PC_CHAIN_PS1.read_text(encoding="utf-8")
        self.assertIn("run_tracking_raw_live_publisher.py", src)
        self.assertIn(".venv-detect", src)
        self.assertIn("smartxr.cli.tracking_raw_monitor", src)

    def test_live_driver_reuses_shared_serve(self):
        src = LIVE_DRIVER.read_text(encoding="utf-8")
        self.assertIn("from smartxr.cli.tracking_raw_publisher import serve", src)
        self.assertIn("detect_nv12", src)
        self.assertIn("Yolov8nNcnnDetector", src)


if __name__ == "__main__":
    unittest.main()
