# MR integration (module 3): C1 -> C2 alignment + display wiring

Module 3 of the architecture baseline (`docs/architecture_modules.md`). It is the
**convergence/alignment seam**: it consumes C1 (`tracking_raw`, raw 3D tracking in
the camera frame) from module 1, applies the camera->head calibration, and emits
C2 (`proxy_targets`, head/world transforms) for module 2 (the Godot card). C1
carries 3D geometry in camera axes; C2 carries head/world transforms; module 3 is
the only place the two meet.

Code: `smartxr/mr_integration.py` (converter + calibration), wiring tool
`tools/convert_tracking_raw_to_proxy_targets.py`. It is the only **device-gated**
data module (alignment correctness needs a real headset), but the conversion math
itself is fully headless and locked in CI.

## What it does

For each C1 detection:

| C1 field (in) | C2 field (out) | Rule |
|---|---|---|
| `landmark.point` (camera axes) | `transform.position` (head/world) | camera->head via the owned calibration (`smartxr.geometry`) |
| `source_frame.coordinate_space` | `coordinate_space` / `transform_space` | `head`/`world` pass through unconverted; anything else is treated as a camera frame and flipped to `head` |
| `state` (lifecycle) | `state` | explicit map, see below |
| `confidence` | `confidence` | passed through, clamped to `[0, 1]` |
| `timestamp_ms` | `timestamp_ms` | per-detection (a held/lost track keeps its lagging observed time) |
| `id` | `target_id` | source-prefixed (`<source>-<id>`, not double-prefixed) |
| (none) | `transform.rotation_xyzw` / `scale` | identity for v1 (axis-aligned box, no orientation) |

A single card is bound to the **primary (first)** target with the default offset
rule. Per-target multi-card lifecycle (appear/expand/contract/disappear) is
module 2's job via the C3 contract, not module 3's.

**Empty frame == no message.** A C1 frame with no detections is the valid
"no people" state (baseline §12), but C2 requires non-empty targets/cards, so the
converter returns `None` and nothing is published — the cards idle/hide. The
`TrackingRawToProxyTargetsConverter` advances its C2 `sequence` only on emitted
frames.

### State mapping (C1 lifecycle -> C2 target state)

`smartxr.schema.canonical_state` is **not** reused here (it maps C1 `lost` to
`tracked`); module 3 owns this dedicated map:

| C1 (`tentative`/`confirmed`/`lost`/`deleted`) | C2 | Meaning |
|---|---|---|
| `tentative` | `tracked` | newly seen, actively detected |
| `confirmed` | `tracked` | stable across N frames |
| `lost` | `predicted` | missed M frames, pose held/predicted |
| `deleted` | `lost` | removed; consumer fades/detaches the card |
| (unknown) | `lost` | fail safe |

Optional **stale-pose downgrade** (`stale_after_ms`): a `tracked` target whose
per-detection timestamp lags the frame timestamp by more than the threshold is
reported as `stale` (baseline §12 "stale depth"), so the consumer can weight
confidence by age. Disabled by default.

## Calibration ownership

Module 3 owns the camera->head conversion (baseline §8 data need #2).

- **v1 monocular** (`Calibration.monocular()`): the default axis flip
  `[x, -y, -z]` (camera `+X right/+Y down/+Z forward` -> head `+X right/+Y up/-Z
  forward`). The default FOV (70/43 deg) lives in **module 1's** projection
  (`smartxr.box_builder_2_5d`) because C1 is already 3D; module 3 only applies the
  extrinsic. The FOV is held on `Calibration` for completeness but not used by the
  conversion.
- **binocular** (`Calibration.with_right_eye_to_head(matrix)`): a row-major 4x4
  `right_eye_to_head` extrinsic applied instead of the flip. A missing/short/
  non-numeric matrix degrades to the monocular flip (never errors). This is the
  seam for the dual-eye iteration — swapping the calibration changes neither C1,
  C2, nor the consumer.

All point math is delegated to `smartxr.geometry`, the single source of truth that
is dual-locked against the GDScript card by
`godot-android/fixtures/bbox_math_test_vectors.json`. The converter therefore
cannot drift from the on-device math.

## Latency (baseline §13)

The C1->C2 + alignment stage budgets ~10-20 ms of the 150 ms end-to-end. The
conversion is pure arithmetic over a handful of points per detection (one flip or
4x4 multiply per target), comfortably inside that slice. Modules 3 and 6 own the
on-device end-to-end measurement.

## Display wiring (the tool)

`tools/convert_tracking_raw_to_proxy_targets.py` bridges a C1 producer/replay to
the existing proxy_targets path:

```
python tools/convert_tracking_raw_to_proxy_targets.py \
    --input  <c1.json | c1.jsonl> \
    --output <c2.json | c2.jsonl> \
    [--right-eye-to-head matrix.json] [--card-id CardAnchor] \
    [--min-confidence 0.0] [--stale-after-ms 200] [--diagnostics]
```

Both ends are validated (C1 against `tracking_raw_schema`, C2 against `schema`),
so the bridge cannot emit a bad payload; empty C1 frames are skipped. The C2
`.jsonl` it produces feeds the existing fake publisher / monitor / Godot consumer
unchanged.

## Verification ladder

- **L0 (schema gate, CI)**: `godot-android/fixtures/proxy_targets_from_c1_sample.json`
  — the canonical C2 output of converting `tracking_raw_sample.json` — is in the
  proxy_targets gate. Regenerate with the wiring tool against the C1 sample.
- **L1 (unit)**: `tests/test_mr_integration.py` — state map, calibration, staleness,
  confidence, empty->None, multi-target, id shaping, diagnostics, plus the
  **bbox-math fixture dual-lock** (every `head_conversion_cases` / `full_chain_cases`
  head point is reproduced by the converter) and the C1-sample -> C2-fixture lock.
- **L2 (fake end-to-end, headless)**: the C1 fake producer
  (`smartxr.tracking_raw_fakes.build_fake_tracking_raw_message`) feeds the converter
  and the canonical C2 consumer (`smartxr.schema`) across a moving sequence with a
  stable id. The wiring tool covers the file/stream path. For the full WS round-trip,
  emit C2 `.jsonl` with the tool and replay it through the existing proxy_targets
  publisher/harness.
- **L3 (device smoke)**: real headset, pending — see below.

## L3 device alignment smoke (pending device)

Run on the headset once module 6 packages a build (YAN-102). Goal: the card sits
near the real person, not behind/beside them.

1. Start a real C1 source (on-device tracker, or PC replay of a calibrated
   capture) and pipe it through `convert_tracking_raw_to_proxy_targets.py` (or the
   in-process converter) into the proxy_targets WS the headset consumes.
2. With a person in view, confirm: the card anchors near the person; it follows as
   they move laterally and in depth; on brief exit it holds last pose (`predicted`)
   then fades (`lost`); no black screen on empty frames.
3. If alignment is biased, capture `right_eye_to_head` on device and supply it via
   `--right-eye-to-head`; the monocular default flip is the v1 fallback.
4. Record evidence: the build commit, a 30 s logcat slice, and a photo/clip of the
   card following the person. Quantitative alignment error needs known-distance
   footage and waits for the dual-eye iteration (baseline §8 #3).
