"""L1 lifecycle / id-stability tests for the human tracker (YAN-108)."""

from __future__ import annotations

import unittest

from smartxr.box_builder_2_5d import Bbox2DNorm
from smartxr.tracker import (
    STATE_CONFIRMED,
    STATE_DELETED,
    STATE_LOST,
    STATE_TENTATIVE,
    Detection2D,
    HumanTracker,
    iou,
)


def det(cx, cy, w=0.2, h=0.4, conf=0.9) -> Detection2D:
    return Detection2D(bbox=Bbox2DNorm(cx, cy, w, h), confidence=conf)


def by_id(tracks):
    return {t.track_id: t for t in tracks}


class IouTests(unittest.TestCase):
    def test_identical_boxes(self):
        b = Bbox2DNorm(0.5, 0.5, 0.2, 0.4)
        self.assertAlmostEqual(iou(b, b), 1.0)

    def test_disjoint_boxes(self):
        self.assertEqual(iou(Bbox2DNorm(0.1, 0.1, 0.1, 0.1), Bbox2DNorm(0.9, 0.9, 0.1, 0.1)), 0.0)


class LifecycleTests(unittest.TestCase):
    def test_new_detection_is_tentative(self):
        tr = HumanTracker(n_confirm=3)
        out = tr.update([det(0.5, 0.5)], timestamp_ms=0.0)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].state, STATE_TENTATIVE)
        self.assertEqual(out[0].age_frames, 0)

    def test_confirms_after_n_hits_with_stable_id(self):
        tr = HumanTracker(n_confirm=3)
        ids = []
        states = []
        for f in range(3):
            out = tr.update([det(0.5, 0.5)], timestamp_ms=f * 33.0)
            ids.append(out[0].track_id)
            states.append(out[0].state)
        self.assertEqual(states, [STATE_TENTATIVE, STATE_TENTATIVE, STATE_CONFIRMED])
        self.assertEqual(len(set(ids)), 1)  # same id throughout

    def test_age_frames_increments(self):
        tr = HumanTracker(n_confirm=2)
        ages = []
        for f in range(4):
            out = tr.update([det(0.5, 0.5)], timestamp_ms=f * 33.0)
            ages.append(out[0].age_frames)
        self.assertEqual(ages, [0, 1, 2, 3])

    def test_two_people_get_distinct_stable_ids(self):
        tr = HumanTracker(n_confirm=2)
        seen = []
        for f in range(4):
            out = tr.update([det(0.25, 0.5), det(0.75, 0.5)], timestamp_ms=f * 33.0)
            seen.append(by_id(out))
        # Two distinct ids across the whole sequence.
        all_ids = {tid for frame in seen for tid in frame}
        self.assertEqual(len(all_ids), 2)
        # Each frame after confirmation has both, confirmed.
        last = seen[-1]
        self.assertEqual(len(last), 2)
        self.assertTrue(all(t.state == STATE_CONFIRMED for t in last.values()))

    def test_lateral_motion_keeps_one_id(self):
        tr = HumanTracker(n_confirm=2, iou_threshold=0.2)
        ids = set()
        for f in range(8):
            cx = 0.2 + f * 0.05  # slides right, boxes overlap frame-to-frame
            out = tr.update([det(cx, 0.5, w=0.25, h=0.5)], timestamp_ms=f * 33.0)
            ids.add(out[0].track_id)
        self.assertEqual(len(ids), 1)

    def test_confirmed_track_becomes_lost_then_reacquires_same_id(self):
        tr = HumanTracker(n_confirm=2, m_to_lost=1, k_to_delete=10)
        # Confirm a track.
        for f in range(2):
            out = tr.update([det(0.5, 0.5)], timestamp_ms=f * 33.0)
        confirmed_id = out[0].track_id
        self.assertEqual(out[0].state, STATE_CONFIRMED)
        # Person briefly disappears -> lost (pose held), id retained.
        out = tr.update([], timestamp_ms=2 * 33.0)
        lost = by_id(out)[confirmed_id]
        self.assertEqual(lost.state, STATE_LOST)
        # Reappears -> confirmed again, SAME id (reacquire).
        out = tr.update([det(0.5, 0.5)], timestamp_ms=3 * 33.0)
        self.assertEqual(out[0].track_id, confirmed_id)
        self.assertEqual(out[0].state, STATE_CONFIRMED)

    def test_lost_track_held_timestamp_lags_frame_clock(self):
        tr = HumanTracker(n_confirm=2, m_to_lost=1, k_to_delete=10)
        for f in range(2):
            out = tr.update([det(0.5, 0.5)], timestamp_ms=f * 100.0)
        last_observed = out[0].observed_timestamp_ms  # 100.0
        out = tr.update([], timestamp_ms=999.0)
        self.assertEqual(out[0].state, STATE_LOST)
        self.assertEqual(out[0].observed_timestamp_ms, last_observed)
        self.assertLess(out[0].observed_timestamp_ms, 999.0)

    def test_lost_track_deleted_after_k_frames_and_removed(self):
        tr = HumanTracker(n_confirm=2, m_to_lost=1, k_to_delete=3)
        for f in range(2):
            out = tr.update([det(0.5, 0.5)], timestamp_ms=f * 33.0)
        tid = out[0].track_id
        states = []
        for f in range(2, 6):
            out = tr.update([], timestamp_ms=f * 33.0)
            match = by_id(out).get(tid)
            states.append(match.state if match else None)
        # lost (tsu1), lost (tsu2), deleted (tsu3 emitted once), then gone.
        self.assertEqual(states, [STATE_LOST, STATE_LOST, STATE_DELETED, None])

    def test_tentative_ghost_dropped_on_miss(self):
        tr = HumanTracker(n_confirm=3)
        out = tr.update([det(0.5, 0.5)], timestamp_ms=0.0)
        self.assertEqual(out[0].state, STATE_TENTATIVE)
        out = tr.update([], timestamp_ms=33.0)
        self.assertEqual(out[0].state, STATE_DELETED)
        # Next frame it is gone entirely.
        out = tr.update([], timestamp_ms=66.0)
        self.assertEqual(out, [])

    def test_reentry_after_deletion_gets_new_id(self):
        tr = HumanTracker(n_confirm=2, m_to_lost=1, k_to_delete=2)
        for f in range(2):
            out = tr.update([det(0.5, 0.5)], timestamp_ms=f * 33.0)
        first_id = out[0].track_id
        # Disappear long enough to delete.
        for f in range(2, 6):
            tr.update([], timestamp_ms=f * 33.0)
        # Re-enter: must be a brand new id (no re-use).
        for f in range(6, 8):
            out = tr.update([det(0.5, 0.5)], timestamp_ms=f * 33.0)
        new_id = out[0].track_id
        self.assertNotEqual(new_id, first_id)


if __name__ == "__main__":
    unittest.main()
