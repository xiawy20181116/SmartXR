"""Minimal multi-object tracker with the C1 track lifecycle (YAN-108).

A dependency-free greedy IOU tracker that assigns stable track ids to 2D person
detections and drives the C1 lifecycle state machine
(``tentative -> confirmed -> lost -> deleted``) defined in
``docs/tracking_raw_payload_contract.md``. It operates purely in normalized 2D
image space; the C1 producer turns each surviving track's box into 3D geometry.

Lifecycle (matches the contract):

- A new, unmatched detection starts a ``tentative`` track.
- A ``tentative`` track confirmed across ``n_confirm`` consecutive hits becomes
  ``confirmed``; a ``tentative`` track that misses is dropped (``deleted``) -- no
  long-lived unconfirmed ghosts.
- A ``confirmed`` track keeps its id across a brief miss; after
  ``m_to_lost`` consecutive misses it becomes ``lost`` (pose held/predicted).
- A ``lost`` track re-matched by IOU returns to ``confirmed`` with the SAME id
  (lost -> reacquire). After ``k_to_delete`` lost frames it becomes ``deleted``.
- Ids are monotonic per session and never reused; a person who re-enters after
  deletion gets a new id (cross-session re-id is out of scope for v1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from smartxr.box_builder_2_5d import Bbox2DNorm

STATE_TENTATIVE = "tentative"
STATE_CONFIRMED = "confirmed"
STATE_LOST = "lost"
STATE_DELETED = "deleted"


@dataclass(frozen=True)
class Detection2D:
    """One 2D person detection in a frame (normalized image coords)."""

    bbox: Bbox2DNorm
    confidence: float


@dataclass
class Track:
    track_id: str
    bbox: Bbox2DNorm
    confidence: float
    state: str
    age_frames: int = 0
    hit_streak: int = 0
    time_since_update: int = 0
    # Capture time of the latest real observation. A held/predicted (lost) track
    # keeps the last observed time, so it lags the frame clock (contract: stale depth).
    observed_timestamp_ms: float = 0.0


def _to_xyxy(b: Bbox2DNorm) -> tuple[float, float, float, float]:
    return (b.cx - b.w * 0.5, b.cy - b.h * 0.5, b.cx + b.w * 0.5, b.cy + b.h * 0.5)


def iou(a: Bbox2DNorm, b: Bbox2DNorm) -> float:
    """Intersection-over-union of two normalized boxes."""
    ax1, ay1, ax2, ay2 = _to_xyxy(a)
    bx1, by1, bx2, by2 = _to_xyxy(b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


class HumanTracker:
    def __init__(
        self,
        iou_threshold: float = 0.3,
        n_confirm: int = 3,
        m_to_lost: int = 1,
        k_to_delete: int = 10,
        id_prefix: str = "person-",
    ) -> None:
        self.iou_threshold = iou_threshold
        self.n_confirm = n_confirm
        self.m_to_lost = m_to_lost
        self.k_to_delete = k_to_delete
        self.id_prefix = id_prefix
        self._next_id = 1
        self._tracks: list[Track] = []

    def _new_id(self) -> str:
        track_id = f"{self.id_prefix}{self._next_id}"
        self._next_id += 1
        return track_id

    def _match(
        self, detections: list[Detection2D]
    ) -> tuple[dict[int, int], set[int], set[int]]:
        """Greedy IOU matching. Returns track_idx->det_idx, matched dets, matched tracks."""
        pairs = []
        for ti, track in enumerate(self._tracks):
            for di, det in enumerate(detections):
                score = iou(track.bbox, det.bbox)
                if score >= self.iou_threshold:
                    pairs.append((score, ti, di))
        pairs.sort(reverse=True)
        track_to_det: dict[int, int] = {}
        used_tracks: set[int] = set()
        used_dets: set[int] = set()
        for _score, ti, di in pairs:
            if ti in used_tracks or di in used_dets:
                continue
            track_to_det[ti] = di
            used_tracks.add(ti)
            used_dets.add(di)
        return track_to_det, used_dets, used_tracks

    def update(self, detections: list[Detection2D], timestamp_ms: float) -> list[Track]:
        """Advance one frame. Returns the tracks to publish this frame.

        The returned list includes confirmed/tentative/lost tracks and any track
        that became ``deleted`` on this frame (emitted once, then removed).
        """
        track_to_det, used_dets, used_tracks = self._match(detections)

        published: list[Track] = []
        survivors: list[Track] = []

        for ti, track in enumerate(self._tracks):
            track.age_frames += 1
            if ti in used_tracks:
                det = detections[track_to_det[ti]]
                track.bbox = det.bbox
                track.confidence = det.confidence
                track.time_since_update = 0
                track.hit_streak += 1
                track.observed_timestamp_ms = timestamp_ms
                if track.state in (STATE_TENTATIVE,):
                    if track.hit_streak >= self.n_confirm:
                        track.state = STATE_CONFIRMED
                elif track.state == STATE_LOST:
                    track.state = STATE_CONFIRMED  # reacquired with same id
                published.append(track)
                survivors.append(track)
            else:
                track.time_since_update += 1
                track.hit_streak = 0
                if track.state == STATE_TENTATIVE:
                    # Unconfirmed ghost: drop immediately.
                    track.state = STATE_DELETED
                    published.append(track)
                    continue
                if track.state == STATE_CONFIRMED and track.time_since_update >= self.m_to_lost:
                    track.state = STATE_LOST
                if track.state == STATE_LOST and track.time_since_update >= self.k_to_delete:
                    track.state = STATE_DELETED
                    published.append(track)
                    continue
                published.append(track)
                survivors.append(track)

        # Spawn tentative tracks for unmatched detections.
        for di, det in enumerate(detections):
            if di in used_dets:
                continue
            track = Track(
                track_id=self._new_id(),
                bbox=det.bbox,
                confidence=det.confidence,
                state=STATE_TENTATIVE,
                age_frames=0,
                hit_streak=1,
                time_since_update=0,
                observed_timestamp_ms=timestamp_ms,
            )
            # A single-detection start can confirm immediately only if n_confirm <= 1.
            if track.hit_streak >= self.n_confirm:
                track.state = STATE_CONFIRMED
            published.append(track)
            survivors.append(track)

        self._tracks = survivors
        return published
