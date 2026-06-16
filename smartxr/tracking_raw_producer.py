"""The module-1 C1 (tracking_raw) producer (YAN-108).

Wires the pieces into a real C1 producer: a detection backend yields per-frame
2D person detections, the :class:`~smartxr.tracker.HumanTracker` assigns stable
ids and lifecycle state, the :mod:`smartxr.box_builder_2_5d` builder extrudes
each track into a 2.5D 3D box + landmark, and this producer assembles and
**validates** a canonical C1 message. This is the real producer the architecture
calls for (the seam previously stubbed by ``fake_proxy_targets_publisher.py``);
``smartxr/tracking_raw_fakes.py`` remains the contract-only fake.

Depth is a **pluggable scalar** (:class:`DepthSource`): v1 uses
:class:`ConstantDepthSource` (``constant_depth`` / ``fixed_depth``). Swapping in
mono-metric or stereo depth changes only the depth value and the tags, never the
C1 shape -- see ``docs/tracking_raw_payload_contract.md``.
"""

from __future__ import annotations

from typing import Iterable, Protocol

from smartxr.box_builder_2_5d import (
    DEFAULT_LANDMARK_RULE,
    EXTENT_PROJECTED_BBOX,
    VST_RIGHT_CAMERA,
    CameraIntrinsics,
    build_2_5d_bbox,
)
from smartxr.tracker import HumanTracker, Track
from smartxr.tracking_raw_schema import (
    MESSAGE_TYPE,
    SCHEMA_VERSION,
    validate_message,
)

POSE_QUALITY_FIXED_DEPTH = "fixed_depth"
DEPTH_SOURCE_CONSTANT = "constant_depth"


class DepthSource(Protocol):
    """Resolves the scalar depth for a track. The pluggable depth axis."""

    def depth_for(self, track: Track) -> tuple[float, str, str]:
        """Return ``(depth_m, depth_source_tag, pose_quality)`` for a track."""
        ...


class ConstantDepthSource:
    """v1 fixed depth: every track sits at a constant given depth."""

    def __init__(self, depth_m: float = 1.8) -> None:
        if depth_m <= 0.0:
            raise ValueError("depth_m must be positive")
        self.depth_m = depth_m

    def depth_for(self, track: Track) -> tuple[float, str, str]:
        return (self.depth_m, DEPTH_SOURCE_CONSTANT, POSE_QUALITY_FIXED_DEPTH)


class TrackingRawProducer:
    """Builds validated C1 messages from per-frame 2D detections."""

    def __init__(
        self,
        tracker: HumanTracker | None = None,
        depth_source: DepthSource | None = None,
        intrinsics: CameraIntrinsics = VST_RIGHT_CAMERA,
        *,
        source: str = "replay",
        coordinate_space: str = "vst_right_camera",
        landmark_rule: str = DEFAULT_LANDMARK_RULE,
        extent_mode: str = EXTENT_PROJECTED_BBOX,
        validate: bool = True,
    ) -> None:
        self.tracker = tracker if tracker is not None else HumanTracker()
        self.depth_source = depth_source if depth_source is not None else ConstantDepthSource()
        self.intrinsics = intrinsics
        self.source = source
        self.coordinate_space = coordinate_space
        self.landmark_rule = landmark_rule
        self.extent_mode = extent_mode
        self.validate = validate

    def _detection_payload(self, track: Track) -> dict:
        depth_m, depth_source_tag, pose_quality = self.depth_source.depth_for(track)
        geom = build_2_5d_bbox(
            track.bbox,
            depth_m,
            self.intrinsics,
            extent_mode=self.extent_mode,
            landmark_rule=self.landmark_rule,
        )
        return {
            "id": track.track_id,
            "state": track.state,
            "age_frames": track.age_frames,
            "confidence": track.confidence,
            # A held/predicted (lost) track keeps its last observed time, which
            # lags the frame clock -- the contract's "stale depth" note.
            "timestamp_ms": track.observed_timestamp_ms,
            "bbox_3d": geom["bbox_3d"],
            "landmark": geom["landmark"],
            "source_frame": {
                "coordinate_space": self.coordinate_space,
                "units": "meters",
                "depth_source": depth_source_tag,
            },
            "pose_quality": pose_quality,
        }

    def produce_frame(self, detections, sequence: int, timestamp_ms: float) -> dict:
        """Advance the tracker one frame and return a validated C1 message.

        An empty ``detections`` list is valid: with no active tracks it yields a
        C1 message with an empty ``detections`` array (a valid "no people" state).
        """
        tracks = self.tracker.update(detections, timestamp_ms)
        message = {
            "type": MESSAGE_TYPE,
            "schema_version": SCHEMA_VERSION,
            "sequence": sequence,
            "source": self.source,
            "timestamp_ms": timestamp_ms,
            "detections": [self._detection_payload(t) for t in tracks],
        }
        if self.validate:
            errors = validate_message(message)
            if errors:
                raise ValueError(
                    "producer emitted invalid C1 message: " + "; ".join(errors)
                )
        return message

    def run(self, frames: Iterable[tuple[int, float, list]]) -> Iterable[dict]:
        """Yield a validated C1 message per ``(sequence, timestamp_ms, detections)``."""
        for sequence, timestamp_ms, detections in frames:
            yield self.produce_frame(detections, sequence, timestamp_ms)
