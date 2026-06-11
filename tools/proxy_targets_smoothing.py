from __future__ import annotations

import argparse
import math
from typing import Any


SMOOTHING_MODES = ("none", "ema", "one_euro")
DEFAULT_EMA_ALPHA = 0.4
DEFAULT_ONE_EURO_MIN_CUTOFF_HZ = 1.0
DEFAULT_ONE_EURO_BETA = 0.05
DEFAULT_ONE_EURO_D_CUTOFF_HZ = 1.0
DEFAULT_FRAME_DT_S = 0.05
MAX_FRAME_DT_S = 1.0


class EmaAxisFilter:
    """Exponential moving average over one scalar axis."""

    def __init__(self, alpha: float) -> None:
        self.alpha = min(max(float(alpha), 0.0), 1.0)
        self._value: float | None = None

    def filter(self, value: float, dt_s: float) -> float:
        del dt_s
        if self._value is None:
            self._value = float(value)
        else:
            self._value += self.alpha * (float(value) - self._value)
        return self._value


class OneEuroAxisFilter:
    """One Euro filter (Casiez et al. 2012) over one scalar axis.

    Adapts its cutoff to speed: low cutoff at rest removes jitter, higher
    cutoff during fast motion keeps lag small.
    """

    def __init__(self, min_cutoff_hz: float, beta: float, d_cutoff_hz: float) -> None:
        self.min_cutoff_hz = max(float(min_cutoff_hz), 1e-6)
        self.beta = max(float(beta), 0.0)
        self.d_cutoff_hz = max(float(d_cutoff_hz), 1e-6)
        self._value: float | None = None
        self._derivative = 0.0

    @staticmethod
    def _smoothing_factor(cutoff_hz: float, dt_s: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff_hz)
        return 1.0 / (1.0 + tau / dt_s)

    def filter(self, value: float, dt_s: float) -> float:
        value = float(value)
        dt_s = max(float(dt_s), 1e-6)
        if self._value is None:
            self._value = value
            self._derivative = 0.0
            return value
        raw_derivative = (value - self._value) / dt_s
        d_alpha = self._smoothing_factor(self.d_cutoff_hz, dt_s)
        self._derivative += d_alpha * (raw_derivative - self._derivative)
        cutoff_hz = self.min_cutoff_hz + self.beta * abs(self._derivative)
        alpha = self._smoothing_factor(cutoff_hz, dt_s)
        self._value += alpha * (value - self._value)
        return self._value


class TargetPositionSmoother:
    """Smooths target transform positions in proxy_targets messages.

    Keeps independent per-axis filter state for every target_id, derives dt
    from target timestamps when available, and resets cleanly between replay
    loops via reset().
    """

    def __init__(
        self,
        mode: str = "none",
        *,
        ema_alpha: float = DEFAULT_EMA_ALPHA,
        one_euro_min_cutoff_hz: float = DEFAULT_ONE_EURO_MIN_CUTOFF_HZ,
        one_euro_beta: float = DEFAULT_ONE_EURO_BETA,
        one_euro_d_cutoff_hz: float = DEFAULT_ONE_EURO_D_CUTOFF_HZ,
        default_dt_s: float = DEFAULT_FRAME_DT_S,
    ) -> None:
        if mode not in SMOOTHING_MODES:
            raise ValueError(f"unknown smoothing mode: {mode}")
        self.mode = mode
        self.ema_alpha = ema_alpha
        self.one_euro_min_cutoff_hz = one_euro_min_cutoff_hz
        self.one_euro_beta = one_euro_beta
        self.one_euro_d_cutoff_hz = one_euro_d_cutoff_hz
        self.default_dt_s = max(float(default_dt_s), 1e-3)
        self._filters: dict[str, list[Any]] = {}
        self._last_timestamp_ms: dict[str, float] = {}

    def describe(self) -> str:
        if self.mode == "ema":
            return f"ema(alpha={self.ema_alpha})"
        if self.mode == "one_euro":
            return (
                f"one_euro(min_cutoff={self.one_euro_min_cutoff_hz}Hz,"
                f"beta={self.one_euro_beta},d_cutoff={self.one_euro_d_cutoff_hz}Hz)"
            )
        return "none"

    def reset(self) -> None:
        self._filters.clear()
        self._last_timestamp_ms.clear()

    def _new_axis_filter(self) -> Any:
        if self.mode == "ema":
            return EmaAxisFilter(self.ema_alpha)
        return OneEuroAxisFilter(
            self.one_euro_min_cutoff_hz,
            self.one_euro_beta,
            self.one_euro_d_cutoff_hz,
        )

    def _dt_for_target(self, target_id: str, timestamp_ms: float | None) -> float:
        if timestamp_ms is None:
            return self.default_dt_s
        last = self._last_timestamp_ms.get(target_id)
        self._last_timestamp_ms[target_id] = float(timestamp_ms)
        if last is None:
            return self.default_dt_s
        dt_s = (float(timestamp_ms) - last) / 1000.0
        if dt_s <= 0.0 or dt_s > MAX_FRAME_DT_S:
            return self.default_dt_s
        return dt_s

    def smooth_position(
        self,
        target_id: str,
        position: list[float],
        timestamp_ms: float | None = None,
    ) -> list[float]:
        if self.mode == "none":
            return [float(value) for value in position[:3]]
        dt_s = self._dt_for_target(target_id, timestamp_ms)
        filters = self._filters.get(target_id)
        if filters is None:
            filters = [self._new_axis_filter() for _ in range(3)]
            self._filters[target_id] = filters
        return [filters[axis].filter(position[axis], dt_s) for axis in range(3)]

    def smooth_message(self, message: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "none":
            return message
        for target in message.get("targets", []):
            if not isinstance(target, dict):
                continue
            transform = target.get("transform")
            if not isinstance(transform, dict):
                continue
            position = transform.get("position")
            if not isinstance(position, list) or len(position) < 3:
                continue
            target_id = str(target.get("target_id", "target-0"))
            timestamp_ms = target.get("timestamp_ms")
            if not isinstance(timestamp_ms, (int, float)) or isinstance(timestamp_ms, bool):
                timestamp_ms = None
            transform["position"] = self.smooth_position(target_id, position, timestamp_ms)
        return message


def add_smoothing_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--smooth", default="none", choices=list(SMOOTHING_MODES))
    parser.add_argument("--smooth-ema-alpha", type=float, default=DEFAULT_EMA_ALPHA)
    parser.add_argument("--smooth-min-cutoff", type=float, default=DEFAULT_ONE_EURO_MIN_CUTOFF_HZ)
    parser.add_argument("--smooth-beta", type=float, default=DEFAULT_ONE_EURO_BETA)
    parser.add_argument("--smooth-d-cutoff", type=float, default=DEFAULT_ONE_EURO_D_CUTOFF_HZ)


def smoother_from_args(args: argparse.Namespace, default_dt_s: float = DEFAULT_FRAME_DT_S) -> TargetPositionSmoother:
    return TargetPositionSmoother(
        getattr(args, "smooth", "none"),
        ema_alpha=getattr(args, "smooth_ema_alpha", DEFAULT_EMA_ALPHA),
        one_euro_min_cutoff_hz=getattr(args, "smooth_min_cutoff", DEFAULT_ONE_EURO_MIN_CUTOFF_HZ),
        one_euro_beta=getattr(args, "smooth_beta", DEFAULT_ONE_EURO_BETA),
        one_euro_d_cutoff_hz=getattr(args, "smooth_d_cutoff", DEFAULT_ONE_EURO_D_CUTOFF_HZ),
        default_dt_s=default_dt_s,
    )
