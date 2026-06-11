import importlib.util
import math
import random
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOOTHING = ROOT / "tools" / "proxy_targets_smoothing.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_message(position, target_id="vst-person-7", timestamp_ms=1000.0):
    return {
        "type": "proxy_targets",
        "schema_version": 1,
        "sequence": 0,
        "targets": [
            {
                "target_id": target_id,
                "timestamp_ms": timestamp_ms,
                "transform": {
                    "position": list(position),
                    "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                    "scale": [1.0, 1.0, 1.0],
                },
            }
        ],
        "cards": [],
    }


class ProxyTargetsSmoothingTests(unittest.TestCase):
    def setUp(self):
        self.smoothing = load_module(SMOOTHING, "proxy_targets_smoothing")

    def test_none_mode_passes_positions_through_unchanged(self):
        smoother = self.smoothing.TargetPositionSmoother("none")
        message = make_message([0.5, -0.2, -5.0])
        result = smoother.smooth_message(message)
        self.assertEqual(result["targets"][0]["transform"]["position"], [0.5, -0.2, -5.0])

    def test_ema_first_sample_is_identity_then_converges(self):
        smoother = self.smoothing.TargetPositionSmoother("ema", ema_alpha=0.5)
        first = smoother.smooth_position("t", [1.0, 2.0, 3.0], 1000.0)
        self.assertEqual(first, [1.0, 2.0, 3.0])
        second = smoother.smooth_position("t", [3.0, 2.0, 3.0], 1050.0)
        self.assertAlmostEqual(second[0], 2.0)
        for _ in range(50):
            value = smoother.smooth_position("t", [3.0, 2.0, 3.0], 1050.0)
        self.assertAlmostEqual(value[0], 3.0, places=3)

    def test_one_euro_reduces_noise_variance_on_static_target(self):
        smoother = self.smoothing.TargetPositionSmoother(
            "one_euro", one_euro_min_cutoff_hz=1.0, one_euro_beta=0.05
        )
        rng = random.Random(7)
        raw_deltas = []
        smoothed_deltas = []
        previous_raw = None
        previous_smoothed = None
        timestamp_ms = 0.0
        for _ in range(200):
            timestamp_ms += 50.0
            raw = [0.5 + rng.gauss(0.0, 0.03), 0.0 + rng.gauss(0.0, 0.03), -5.0]
            smoothed = smoother.smooth_position("t", raw, timestamp_ms)
            if previous_raw is not None:
                raw_deltas.append(math.dist(raw, previous_raw))
                smoothed_deltas.append(math.dist(smoothed, previous_smoothed))
            previous_raw = raw
            previous_smoothed = smoothed
        raw_mean = sum(raw_deltas) / len(raw_deltas)
        smoothed_mean = sum(smoothed_deltas) / len(smoothed_deltas)
        self.assertLess(smoothed_mean, raw_mean * 0.5)

    def test_one_euro_tracks_fast_motion_with_low_lag(self):
        smoother = self.smoothing.TargetPositionSmoother(
            "one_euro", one_euro_min_cutoff_hz=1.0, one_euro_beta=0.5
        )
        timestamp_ms = 0.0
        value = [0.0, 0.0, -5.0]
        for step in range(100):
            timestamp_ms += 50.0
            raw = [step * 0.05, 0.0, -5.0]
            value = smoother.smooth_position("t", raw, timestamp_ms)
        self.assertLess(abs(raw[0] - value[0]), 0.25)

    def test_targets_keep_independent_filter_state(self):
        smoother = self.smoothing.TargetPositionSmoother("ema", ema_alpha=0.5)
        smoother.smooth_position("a", [0.0, 0.0, 0.0], 1000.0)
        smoother.smooth_position("b", [10.0, 0.0, 0.0], 1000.0)
        second_a = smoother.smooth_position("a", [1.0, 0.0, 0.0], 1050.0)
        self.assertAlmostEqual(second_a[0], 0.5)

    def test_reset_clears_filter_state(self):
        smoother = self.smoothing.TargetPositionSmoother("ema", ema_alpha=0.5)
        smoother.smooth_position("t", [0.0, 0.0, 0.0], 1000.0)
        smoother.reset()
        value = smoother.smooth_position("t", [4.0, 0.0, 0.0], 1050.0)
        self.assertEqual(value, [4.0, 0.0, 0.0])

    def test_smooth_message_handles_missing_transform_fields(self):
        smoother = self.smoothing.TargetPositionSmoother("ema")
        message = {"targets": [{"target_id": "x"}, "junk", {"transform": {}}], "cards": []}
        result = smoother.smooth_message(message)
        self.assertEqual(len(result["targets"]), 3)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            self.smoothing.TargetPositionSmoother("kalman")

    def test_smoother_from_args_reads_cli_arguments(self):
        import argparse

        parser = argparse.ArgumentParser()
        self.smoothing.add_smoothing_arguments(parser)
        args = parser.parse_args(
            ["--smooth", "one_euro", "--smooth-min-cutoff", "0.8", "--smooth-beta", "0.1"]
        )
        smoother = self.smoothing.smoother_from_args(args)
        self.assertEqual(smoother.mode, "one_euro")
        self.assertAlmostEqual(smoother.one_euro_min_cutoff_hz, 0.8)
        self.assertAlmostEqual(smoother.one_euro_beta, 0.1)
        self.assertIn("one_euro", smoother.describe())


if __name__ == "__main__":
    unittest.main()
