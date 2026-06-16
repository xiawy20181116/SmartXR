# tracking_raw (C1) payload contract

## Seam

C1 is the **tracking-raw** seam: module 1 (human tracking) produces it, module 3
(MR integration) consumes it and converts it to canonical `proxy_targets` (C2).
C1 is the evolution of the `smartxr/frames.py` source payload, lifted to
normalized **3D geometry**. Where detection actually runs (on-device,
PC-offload, hybrid) is a deployment choice **behind** this boundary; every
backend emits the same C1.

Code form: `smartxr/tracking_raw_schema.py`. Schema gate, fixtures, fakes and
tests are listed under "Freeze status" below.

## Conventions (architecture_modules.md section 11)

Meters, radians, quaternions `[x, y, z, w]`, right-handed. The frame is named per
detection by `source_frame.coordinate_space` (e.g. `vst_right_camera`, `head`,
`world`). One monotonic `timestamp_ms` per producer with a documented epoch.

## Message shape

Required top-level fields:

- `type`: `tracking_raw`
- `schema_version`: `1`
- `sequence`: integer producer frame sequence
- `source`: producer/backend tag, e.g. `on_device`, `pc_offload`, `hybrid`,
  `replay`, `fake_tracking`
- `timestamp_ms`: producer frame clock (monotonic ms, documented epoch)
- `detections`: array of detections. **An empty array is a valid state** (no
  people in view; architecture section 12) — it is not an error.

Required detection fields (the C1 per-detection object, architecture section 4):

- `id`: track id (string). A track id with a defined lifecycle (see "Track
  lifecycle" below), so id-stability is testable.
- `state`: one of `tentative`, `confirmed`, `lost`, `deleted`.
- `age_frames`: non-negative integer; frames since the track was first seen.
  Supports the T1 id-switch-rate metric.
- `confidence`: number in `[0.0, 1.0]`.
- `timestamp_ms`: capture time of this track's latest observation. For a `lost`
  track whose pose is held/predicted, this lags the frame `timestamp_ms` (the
  producer holds the last per-track depth between depth updates; section 12
  "stale depth").
- `bbox_3d`: the authoritative box, in **exactly one** of two forms (see below).
- `landmark`: `{ rule, point }` — a derived point with the rule used to compute
  it from the 8 vertices.
- `source_frame`: `{ coordinate_space, units, depth_source }`.
- `pose_quality`: one of `fixed_depth`, `mono_metric`, `stereo`.

### `bbox_3d` — two equivalent forms (pick one)

The authoritative base is the 3D oriented bounding box. A detection carries
**exactly one** representation; supplying both is rejected:

1. **8 vertices**: `{ "vertices": [ [x,y,z] x 8 ] }`. Canonical vertex order is
   the sign-product of half-extents over `(x, y, z)`: `(-,-,-), (-,-,+),
   (-,+,-), (-,+,+), (+,-,-), (+,-,+), (+,+,-), (+,+,+)`.
2. **center + extent + rotation**: `{ "center": [x,y,z], "extent": [x,y,z],
   "rotation_xyzw": [x,y,z,w] }`, where `extent` is the half-size on each axis.

Both describe the same box; consumers may convert between them. v1 producers may
emit either — the on-device 2.5D builder naturally emits vertices, an OBB tracker
naturally emits center/extent/rotation.

### `landmark`

`landmark` is a **derived** point carrying a `rule` (e.g. `centroid`,
`front_top_center`, `bottom_center`) computed from the 8 vertices. Choosing a
different landmark later changes the `rule` value and `point`, **not** the
contract shape. Default rule for the fake producer is `centroid`.

### `source_frame`

- `coordinate_space`: the frame the box/landmark/points live in (names a frame
  from section 11).
- `units`: `meters` for v1.
- `depth_source`: a tag describing where depth came from (e.g. `constant_depth`,
  `monodepth`, `stereo_vst`). The depth source is a pluggable scalar input to the
  2.5D box builder and can be swapped without changing C1's shape.

`source_frame` is carried **per detection** (per architecture section 4). In v1
all detections in a message share the same `source_frame`; the per-detection
placement leaves room for a future hybrid producer that mixes sources.

### `pose_quality`

Records pose fidelity, decoupled from the depth source tag:

- `fixed_depth` — constant given depth (**v1 default**).
- `mono_metric` — monocular metric depth estimate (low frame rate).
- `stereo` — stereo VST triangulation (arrives with the dual-eye iteration).

Upgrading the depth source (and `pose_quality`) is a swap **behind** C1 — no
contract change.

## Raw 2D fields are forbidden

C1 is normalized **3D** geometry. The 2D/image domain stays inside module 1 and
must never cross this boundary. The following keys are rejected anywhere in a C1
message: `bbox` (2D pixel box), `boxes`, `image`, `pixels`, `mask`, `depth_m`
(raw scalar — superseded by `bbox_3d` + `pose_quality` + `depth_source`). This is
the mirror of the C2 rule that keeps raw detection fields out of `proxy_targets`.

## Track lifecycle and id

C1 `id` is a track id with a defined lifecycle so id-stability is testable:

- `tentative` (newly seen, unconfirmed) -> `confirmed` (stable across N frames)
  -> `lost` (missed M frames, pose predicted) -> `deleted` (after K lost frames).
- A `confirmed` track keeps its id across brief occlusion/exit; ids are not
  reused within a session. Re-entry after `deleted` gets a new id (cross-session
  re-identification is out of scope for v1).

## Freeze status (architecture section 5)

1. **Versioned schema**: `smartxr/tracking_raw_schema.py` (`schema_version: 1`).
2. **Fixtures + validator in the gate**: `tracking_raw_sample.json` (8-vertex
   form) and `tracking_raw_obb_sample.json` (center+extent+rotation form), both
   in `godot-android/fixtures/`, validated by
   `tools/validate_tracking_raw_payload_schema.py` in CI.
3. **Fake producer + fake consumer**: `smartxr/tracking_raw_fakes.py`
   (`build_fake_tracking_raw_message` + `TrackingRawConsumer`), each speaking
   only the schema. Round-trip in `tests/test_tracking_raw_payload_schema.py`.
4. **Semantics doc**: this file.
5. **Change policy**: after freezing, only additive field changes are allowed.
   Any shape change (renaming/removing a field, changing a representation)
   requires an explicit `schema_version++`. Silent field reshaping is forbidden.
   A consumer accepts a `schema_version` within its supported range and ignores
   unknown additive fields.

## Gate command

```powershell
python tools\validate_tracking_raw_payload_schema.py --input godot-android\fixtures\tracking_raw_sample.json --input godot-android\fixtures\tracking_raw_obb_sample.json
```
