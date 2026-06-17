# tracking_raw (C1) producer — module 1 (YAN-108)

The module-1 **human tracking** producer. It turns VST camera frames into the
canonical C1 `tracking_raw` payload (`docs/tracking_raw_payload_contract.md`):
detect people, track them with stable ids and a lifecycle, and extrude each
track into a 2.5D 3D box + landmark. Module 3 consumes C1 and converts it to
`proxy_targets` (C2).

This is the real producer behind the seam the project previously stubbed with
`fake_proxy_targets_publisher.py`. `smartxr/tracking_raw_fakes.py` stays as the
contract-only fake (one synthetic moving box) for consumer-side development.

## Pipeline

```
NV12 frame ─▶ detection backend ─▶ HumanTracker ─▶ 2.5D box builder ─▶ C1 message
 (camera)     (2D person boxes)    (id+lifecycle)   (3D box+landmark)   (validated)
```

| Stage | Code | Notes |
|---|---|---|
| NV12 read | `smartxr/nv12_reader.py` | pure stdlib; `<6I Q` header, 880×660 stride 896 |
| Detection backend | `smartxr/detection_backend.py` | pluggable; `ReplayDetectionBackend` (no model) + ncnn (tools) |
| Tracking | `smartxr/tracker.py` | greedy IOU + `tentative→confirmed→lost→deleted` |
| 2.5D box | `smartxr/box_builder_2_5d.py` | project center to depth, extrude, landmark rule |
| Producer | `smartxr/tracking_raw_producer.py` | assembles + **validates** the C1 message |

Everything in `smartxr/` is dependency-free (stdlib only), so it stays inside
the Python CI gate. The ncnn detector and the capture-verification / fixture
tooling live in `tools/` behind optional `numpy`/`opencv`/`ncnn`.

## NV12 reader

`smartxr/nv12_reader.py` reads the recorded replay captures. A packet is a
32-byte header `<6I Q` (magic `0x4E563132` "NV12", header_size, width, height,
stride, payload_size, `timestamp_us`) + an NV12 payload (Y plane `stride*height`,
then interleaved UV `stride*height/2`). The reader validates the magic, header
size, geometry and payload size, splits the planes, and can iterate a session
directory (`metadata.json` + `nv12_packets/`) with a `start/limit/step` window
so the multi-GB sessions never load fully into memory.

## Detection backend topology

Where detection runs is a deployment choice **behind** C1
(`architecture_modules.md` "Detection backend topology"): `on_device` ncnn,
`pc_offload` over LAN, or `hybrid`. All emit the same per-frame list of
normalized 2D boxes, so the tracker and producer are identical. The committed
PC-offload detector (`tools/yolov8n_ncnn_detector.py`) runs the same
`godot-android/ncnn/yolov8n_320` model on a PC; `ReplayDetectionBackend` serves
pre-recorded detections so the contract and L2 replay run with no model.

## 2.5D box builder

v1 approximates the 3D box from a single VST eye (`pose_quality = fixed_depth`):

1. Project the 2D bbox center through the camera FOV onto a point at the scalar
   depth (reuses `smartxr/geometry.py`), in `vst_right_camera` axes (+X right,
   +Y down, +Z forward). Module 3 applies the camera→head conversion.
2. X/Y half-extents come from the 2D bbox extent projected to metric at that
   depth (`extent_mode=projected_bbox`, the default) — a closer person yields a
   larger box. The Z (toward-camera) half-extent is a nominal human thickness
   (un-measurable from one eye). `extent_mode=nominal_human` uses fixed nominal
   width/height instead.
3. Emit the 8 box vertices in the contract's canonical sign order.
4. Derive the `landmark` from a rule over the 8 vertices: `centroid` (default),
   `bottom_center` (feet, max y), `top_center` (head, min y), or
   `front_top_center`. Changing the landmark = changing the rule, not the shape.

### Pluggable depth

Depth is a scalar resolved by a `DepthSource` (`tracking_raw_producer.py`).
v1 = `ConstantDepthSource` → (`constant_depth`, `fixed_depth`). A future
`mono_metric` or `stereo` source returns a different value and different tags;
the C1 shape never changes (verified by `test_pluggable_depth_*` and
`test_alternate_depth_source_only_swaps_tags`). Detection/tracking run at full
rate; depth may update at a lower rate and be held between updates (a `lost`
track keeps its last observed timestamp — the contract's stale-depth note).

## Track lifecycle

`HumanTracker` (greedy IOU matching, configurable thresholds):

- unmatched detection → `tentative`; confirmed after `n_confirm` consecutive
  hits → `confirmed`.
- `tentative` miss → dropped (`deleted`) — no long-lived ghosts.
- `confirmed` miss → `lost` after `m_to_lost` misses (pose held/predicted), id
  retained; re-matched → back to `confirmed` (lost→reacquire, same id).
- `lost` for `k_to_delete` frames → `deleted` (emitted once, then removed).
- ids are monotonic per session, never reused; re-entry gets a new id.

## Validation ladder (no device)

- **L0** C1 schema: every produced message passes `validate_message`
  (`tests/test_tracking_raw_producer.py`, `test_box_builder_2_5d.py`).
- **L1** projection/derivation + lifecycle math: `tests/test_box_builder_2_5d.py`
  (projection, extent scaling, landmark rules) and `tests/test_tracker.py`
  (confirm/lost/reacquire/delete, id stability, 2-person, lateral motion).
  `tests/test_nv12_reader.py` covers the reader.
- **L2** recording replay publisher→consumer: `tests/test_tracking_raw_producer.py`
  replays a window of **real** recorded detections through the producer and the
  fake consumer; asserts every message validates and is accepted, the full
  lifecycle and multiple ids appear, empty frames are valid, and the committed
  golden C1 fixture is reproduced within tolerance.

## Fixtures and reproduction

- `godot-android/fixtures/tracking_raw_replay_detections.jsonl` — real 2D
  detections (200-frame window, capture `capture_20260415T065340Z` frames
  351–550, conf 0.25), produced by:

  ```
  .venv-detect/Scripts/python.exe tools/verify_yolov8n_on_capture.py \
      --capture-root "<fixed_replay_captures-20260429-194546>" \
      --dump-session capture_20260415T065340Z --dump-start 350 --dump-count 200 \
      --dump-out godot-android/fixtures/tracking_raw_replay_detections.jsonl
  ```

- `godot-android/fixtures/tracking_raw_replay_c1.jsonl` — the golden C1 stream,
  rebuildable with the pinned producer recipe (dependency-free):

  ```
  python tools/build_tracking_raw_replay_fixture.py \
      --input  godot-android/fixtures/tracking_raw_replay_detections.jsonl \
      --output godot-android/fixtures/tracking_raw_replay_c1.jsonl
  ```

See `docs/yolov8n_vst_verification.md` for the on-device detector recall on the
real captures.

## Live PC chain (WebSocket publisher + consumer harness)

The producer can stream **live** C1 over a WebSocket so module 3 (or CI) develops
against a moving C1 source, not just a static fixture — entirely on PC, no device.

```
NV12 session ─▶ ncnn yolov8n ─▶ producer ─▶ C1 WS publisher ═══▶ consumer harness
  (recorded)    (PC-offload)    (validate)   /tracking_raw       (validate + report)
```

| Piece | Code | Deps |
|---|---|---|
| Publisher (serve loop) | `smartxr/cli/tracking_raw_publisher.py` | stdlib |
| Consumer harness | `smartxr/cli/tracking_raw_monitor.py` | stdlib |
| Full NV12→ncnn driver | `tools/run_tracking_raw_live_publisher.py` | numpy/opencv/ncnn |

The publisher serves one client at a time on `/tracking_raw` (reusing
`smartxr/transport.py`), one C1 message per frame at `--hz`, with a fresh
producer+tracker per connection. Its frame source is pluggable: the default
replays the recorded **detections JSONL** through the producer (dependency-free,
CI-testable); the NV12→ncnn driver builds an NV12+ncnn source and calls the same
`serve()`, so the wire path is shared, not forked. The harness connects,
subscribes, reads N messages, validates each against the C1 schema + the
`TrackingRawConsumer`, checks sequence contiguity, and reports ids / lifecycle
states / rejections.

Runners:

```powershell
# Dependency-free closed loop (replay detections -> publisher -> harness):
tools\run_tracking_raw_live_harness.ps1 -Port 8770 -MinPackets 60

# Full PC chain from real NV12 (needs .venv-detect):
tools\run_tracking_raw_pc_chain.ps1 -CaptureRoot "<...>\fixed_replay_captures-20260429-194546" `
    -Session capture_20260415T065340Z -Start 350 -Count 200 -Port 8770
```

Or by hand:

```
# terminal A (full chain): .venv-detect/Scripts/python.exe tools/run_tracking_raw_live_publisher.py \
#     --capture-root "<...>" --session capture_20260415T065340Z --start 350 --count 200 --port 8770
# terminal B: python -m smartxr.cli.tracking_raw_monitor --url ws://127.0.0.1:8770/tracking_raw --min-packets 60
```

The end-to-end socket round-trip (publisher thread → monitor) is covered
dependency-free in `tests/test_tracking_raw_live_chain.py`; the full NV12→ncnn
chain was run on real capture and confirmed healthy (all four lifecycle states,
multiple ids, contiguous, zero rejects).
