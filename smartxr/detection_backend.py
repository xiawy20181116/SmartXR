"""Pluggable detection-backend seam for module 1 (YAN-108).

Where person detection runs is a deployment choice **behind** the C1 boundary
(``architecture_modules.md`` "Detection backend topology"): on-device ncnn,
PC-offload over LAN, or a hybrid split. Every backend emits the same thing -- a
per-frame list of :class:`~smartxr.tracker.Detection2D` in normalized image
coordinates -- so the tracker and the C1 producer are identical regardless of
topology.

This module is dependency-free. It defines the backend protocol, the topology
tags, and a :class:`ReplayDetectionBackend` that serves pre-recorded detections
(used by the L2 replay fixture and tests, so no ncnn/numpy is needed at runtime).
The real on-device / PC-offload ncnn backend lives in ``tools/`` behind optional
numpy/opencv/ncnn and adapts to this same shape.
"""

from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from smartxr.box_builder_2_5d import Bbox2DNorm
from smartxr.tracker import Detection2D

# Detection backend topologies (architecture "Detection backend topology").
TOPOLOGY_ON_DEVICE = "on_device"
TOPOLOGY_PC_OFFLOAD = "pc_offload"
TOPOLOGY_HYBRID = "hybrid"

ALLOWED_TOPOLOGIES = {TOPOLOGY_ON_DEVICE, TOPOLOGY_PC_OFFLOAD, TOPOLOGY_HYBRID}


@runtime_checkable
class DetectionBackend(Protocol):
    """A person detector for one image frame.

    ``topology`` is one of :data:`ALLOWED_TOPOLOGIES`; ``source_tag`` is the C1
    message ``source`` this backend produces (e.g. ``on_device``, ``pc_offload``,
    ``replay``).
    """

    topology: str
    source_tag: str

    def detect(self, frame: object) -> list[Detection2D]:
        """Return the person detections for one frame."""
        ...


def detections_from_records(records: Iterable[dict]) -> list[Detection2D]:
    """Build :class:`Detection2D` list from normalized-bbox records.

    Each record is ``{"bbox": [x, y, w, h], "confidence": c}`` with a normalized
    top-left x/y + width/height box, or ``{"cx","cy","w","h","confidence"}``.
    """
    out: list[Detection2D] = []
    for rec in records:
        conf = float(rec.get("confidence", rec.get("score", 1.0)))
        if "bbox" in rec:
            x, y, w, h = (float(v) for v in rec["bbox"])
            bbox = Bbox2DNorm.from_xywh_norm(x, y, w, h)
        else:
            bbox = Bbox2DNorm(float(rec["cx"]), float(rec["cy"]), float(rec["w"]), float(rec["h"]))
        out.append(Detection2D(bbox=bbox, confidence=conf))
    return out


class ReplayDetectionBackend:
    """Serves pre-recorded per-frame detections (PC-offload-shaped, no model).

    ``frames`` is a sequence where each item is a list of detection records (see
    :func:`detections_from_records`). Used to replay real recorded detections
    through the producer without running ncnn.
    """

    def __init__(self, frames: list[list[dict]], source_tag: str = "replay") -> None:
        self.topology = TOPOLOGY_PC_OFFLOAD
        self.source_tag = source_tag
        self._frames = frames
        self._cursor = 0

    def __len__(self) -> int:
        return len(self._frames)

    def detect(self, frame: object) -> list[Detection2D]:
        """Return detections for the next recorded frame (``frame`` is ignored)."""
        records = self._frames[self._cursor]
        self._cursor += 1
        return detections_from_records(records)

    def detect_index(self, index: int) -> list[Detection2D]:
        """Return detections for a specific recorded frame index."""
        return detections_from_records(self._frames[index])
