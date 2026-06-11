# DECISIONS

## 2026-06-11 — Offline jitter work happens publisher-side, in Python

**Decision:** Implement jitter smoothing as a publisher-side filter on
head-space target positions (per `target_id`), not in the Godot consumer.

**Rationale:** The dominant jitter source is per-frame bbox detection noise,
which originates before the WebSocket send. Publisher-side filtering is pure
Python, so it can be tuned entirely offline against a recorded JSONL session
(`analyze_proxy_targets_jitter.py`) with no headset and no Godot. Consumer-side
(GDScript) smoothing would require launching Godot for every iteration and
cannot be unit-tested as easily. If jitter persists with a perfectly smooth
replayed stream, the remaining source is consumer-side (head-to-world
transform) and becomes a separate follow-up.

## 2026-06-11 — One Euro as default recommendation, EMA as fallback

**Decision:** Ship both EMA and One Euro filters; recommend One Euro.

**Rationale:** One Euro adapts cutoff to speed — strong jitter removal at rest
with low lag during fast motion, which matches the YAN-71 acceptance criteria
(person moving left/right, head turning). EMA is kept as a simpler baseline
for A/B comparison. Verified offline: ~81% frame-delta reduction on a
synthetic noisy session while still tracking a 20 px step within lag bounds.

## 2026-06-11 — Replay reuses the exact live publisher math

**Decision:** The analyzer and replay both go through `normalize_frame` +
`normalize_source_payload` (same code path as the live publisher), rather than
reimplementing projection.

**Rationale:** Offline results must transfer 1:1 to the device. Any divergence
between simulation math and live math would invalidate offline tuning.

## 2026-06-11 — Filter state resets on reconnect and replay wrap

**Decision:** `TargetPositionSmoother.reset()` is called when a WS client
connects and when the replay loops back to frame 0.

**Rationale:** Without the reset, the end-of-recording -> start jump would be
smoothed into a visible swoosh, corrupting visual comparisons.
