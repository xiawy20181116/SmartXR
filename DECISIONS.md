# DECISIONS — architecture decision record

## ADR-1: Layered `smartxr/` Python package; tools become wrappers (M2)

**Context.** WebSocket framing/handshake existed in three hand-rolled copies
(`ws_control.py`, `fake_proxy_targets_publisher.py`,
`vst_proxy_targets_publisher.py`), and tools imported private functions from
sibling tools (`vst_*` ← `fake_*`, `antman_*` ← three different tools).

**Decision.** Extract a `smartxr/` package with strictly one-way layering
(cli → publisher → frames → schema/geometry/transport), modeled on the pi
monorepo's package layering. Keep every `tools/*.py` path as a compatibility
wrapper re-exporting the same names, because tests load tools by file path,
PowerShell runners call them directly, and docs reference them.

**Consequences.** One copy of the wire code and of the bbox→head math on the
Python side; existing entry points unchanged; new code should import from
`smartxr.*`, not from `tools/*`.

## ADR-2: `SmartXROptions` with env → config file → const default (M1)

**Context.** `AndroidMovingCard.gd` hardwired `connect_to_url(WS_URL)` to one
development machine's LAN IP; only the proxy_targets URL had an env override.

**Decision.** Introduce `SmartXROptions` (RefCounted, dependency-free) with
resolution order env var → `user://smartxr_options.json` → caller-provided
default. Script consts stay as the defaults (the repo's static-source tests
pin several of them, and they document baseline behavior); call sites read
through `_options`.

**Consequences.** Deployment differences no longer require source edits; the
historical `PROXY_TARGETS_WS_URL` env name is preserved; defaults are
behavior-identical to before (the LAN IP default was deliberately kept —
flipping it to `127.0.0.1` is a one-line owner decision).

*Update (YAN-76 follow-up):* the owner made that call — `WS_URL` now
defaults to `ws://127.0.0.1:8766/control`; devices that need a remote
control server set `SMARTXR_CONTROL_WS_URL` or the config file.

## ADR-3: Update static-source tests instead of faking strings in wrappers

**Context.** Several tests assert implementation strings inside specific tool
files (e.g. `def build_proxy_targets_message(` in the fake publisher).

**Decision.** Repoint those assertions at the package file where the
implementation now lives, rather than padding wrapper files with dead strings
to satisfy greps.

**Consequences.** Tests keep guarding the real implementation; two test
methods were updated (`test_fake_proxy_targets_publisher.py` banner check,
`test_godot_android_mesh_card.py` publisher/URL checks).

## ADR-4: Snapshot-Dictionary seam for AndroidMovingCard subsystem extraction (M3-1)

**Context.** M3 splits the ~1800-line `AndroidMovingCard.gd` god object into
subsystem nodes. The first slice, the status HUD + diagnostics-file writers,
reads ~40 pieces of card state (WS counters, XR flags, VST tracker state,
attachment positions), so a naive extraction would either need a back-pointer
to the card (circular coupling) or dozens of setter calls per frame.

**Decision.** The card assembles one plain snapshot Dictionary per frame
(`_build_status_snapshot()`, with nested `xr` / `vst` / `proxy_targets` /
`passthrough_overlay` sub-dictionaries) and passes it to the extracted node;
`StatusHud` only formats and writes (label text, the two `user://` status
files, throttling). Nullable values (camera pose, layer position, resolved
card position) travel as `Vector3`-or-`null` and StatusHud renders `null` as
the historical `"n/a"`. Like `smartxr_options.gd`, `status_hud.gd` never
references its own `class_name`, so a script-only probe can load it in
no-project mode (`tools/run_godot_status_hud_probe.ps1`).

**Consequences.** StatusHud is dependency-free and runtime-verifiable headless
(29 probe checks pin label text, JSON keys/format, and throttle behavior);
the card keeps all state resolution; later M3 extractions should reuse the
same pattern (resolve in card, format/act in subsystem node). The JSON shape
of both status files is unchanged, so `validate_proxy_targets_live_status.py`
and on-device pulls keep working.

*Update (YAN-103 A3 first slice):* status snapshot composition itself is now
split into `godot-android/scripts/status_snapshot_composer.gd`. The card still
resolves every live value from nodes and subsystems, while the dependency-free
composer owns only the top-level and nested Dictionary key layout. The new
script-only probe locks that shape headless, so this refactor remains in the
Windows / script-only verification tier and does not require real-device VST
smoke testing.

*Update (YAN-103 A3 overlay slice):* passthrough overlay scene-node ownership is
now split into `godot-android/scripts/passthrough_overlay_presenter.gd`. The card
keeps XR lifecycle state, env-gated enablement state, and status snapshot
composition; the presenter owns the transparent overlay viewport, UI,
`OpenXRCompositionLayerQuad`, camera-relative transform update, alpha/position
helpers, and overlay status values. The script-only probe covers the boundary
without live Godot project runs, PCMR, proxy_targets, or headset smoke tests.

*Update (YAN-103 A3 card-view slice):* main card viewport/mesh/UI ownership is
now split into `godot-android/scripts/card_view.gd`. The card keeps motion,
orientation, target attachment, public API, XR/VST/proxy orchestration, and
status snapshots; CardView owns only `SubViewport`, `MovingCardUI`,
`CardAnchor`, `CardPanel`, material binding, and the small XR render probe. The
script-only probe locks the constructed nodes and material values without live
Godot project runs, PCMR, proxy_targets, or headset smoke tests.

## ADR-5: Shared JSON test vectors lock the duplicated bbox math (M4-1)

**Context.** The bbox→head math exists twice on purpose until M4-2/M4-3:
`smartxr/geometry.py` on the publisher side and four methods inside
`AndroidMovingCard.gd` on the device side. M4 moves the GDScript side into a
TargetSource subsystem; without a cross-language gate, a refactor could
silently change the numbers on one side only.

**Decision.** Promote the conventions in
`docs/proxy_targets_payload_contract.md` into one checked-in fixture,
`godot-android/fixtures/bbox_math_test_vectors.json`, consumed by both
implementations: `tests/test_bbox_math_vectors.py` (Python, abs 1e-9) and a
script-only Godot probe (`tools/run_godot_bbox_math_probe.ps1`, abs 1e-4 —
Godot Vector3 is float32). Expected values are generated from
`smartxr.geometry` (`tools/generate_bbox_math_test_vectors.py`); the
cross-language lock comes from the GDScript probe reproducing the same
numbers at runtime, and the trivial cases are hand-verifiable. GDScript-only
behavior (the <16-element matrix fallback, the yaw/pitch/depth/angular
decomposition, the final anchor position) lives in the same fixture so M4-2+
cannot drift it.

**Consequences.** Any M4 move that changes the math fails the probe or the
Python suite instead of shipping a silent divergence. The full-chain vectors
are pinned to the card's 70/43 FOV consts (the probe fails on drift), so a
FOV default change requires regenerating the fixture deliberately. The probe
loads the card itself, which sets the precedent for staging `scripts\` into
a no-project temp cwd (the compile-gate trick) whenever a probe needs a
script that preloads siblings.

## ADR-6: VSTCapture owns native polling and bbox math, card owns side effects

**Context.** After M3-M5, `AndroidMovingCard.gd` still owned the most fragile
device-specific path: `GXRDualVstCapture` setup, ncnn tracker asset staging,
right-frame polling, tracker boxes, eye-to-head calibration diagnostics, and
bbox-to-head math. That made the card hard to reason about and mixed native SDK
state with scene side effects.

**Decision.** Extract those responsibilities into
`godot-android/scripts/vst_capture.gd` (`VSTCapture`), a dependency-free
`RefCounted` script. The subsystem owns native capture state, calibration
strings, first-box/frame/latency counters, and bbox math. The card wires three
callbacks for side effects it must still own: raw-image texture updates,
tracker-box debug overlays, and target-source updates/attachment through the
existing public APIs.

**Consequences.** `AndroidMovingCard.gd` is reduced to VST orchestration for
this path while preserving public methods such as `update_vst_target`,
`register_node3d_target`, and `attach_to_target`. `StatusHud` receives the same
VST snapshot keys through the card. `tools/run_godot_vst_capture_probe.ps1`
validates the subsystem in no-project mode, and the existing bbox fixture probe
continues to guard numeric drift.

## ADR-7: VSTDebugUI owns VST debug scene visuals, card keeps state

**Context.** After VSTCapture moved native polling and bbox math out of
`AndroidMovingCard.gd`, the card still built and updated the VST world bbox
frame, raw right-image `Sprite3D`, raw bbox overlay quads, and raw debug label.
Those nodes are UI/debug visualization, not capture or target-source state.

**Decision.** Extract that scene-node construction and visual update logic into
`godot-android/scripts/vst_debug_ui.gd` (`VSTDebugUI`), a dependency-free
`RefCounted` script. The card instantiates it, asks it to build the raw panel
and world bbox frame, then delegates raw image texture updates, raw-image bbox
overlay updates, and world-frame sizing/visibility. The card still owns
VSTCapture callbacks, bbox state, target updates, attachment, orientation
policy, and status snapshots.

**Consequences.** The VST debug visuals now have one owner and a script-only
probe (`tools/run_godot_vst_debug_ui_probe.ps1`). `AndroidMovingCard.gd` stays
as orchestration and keeps public APIs unchanged while dropping below 1000
lines for the YAN-100 UI extraction slice.

## ADR-8: C1 tracking-raw frozen as hand-written 3D-only schema (YAN-105)

**Context.** Architecture §10 step 0 requires freezing C1 to the §5 bar. The
repo has no `jsonschema` dependency (`pyproject` deps are empty); C2 is locked
by a hand-written validator in `smartxr/schema.py`. C1's §4 field list places
`source_frame` and `pose_quality` inside the per-detection object and offers
`bbox_3d` as either 8 vertices **or** center+extent+rotation.

**Decision.** Mirror the C2 pattern exactly: a hand-written validator
(`smartxr/tracking_raw_schema.py`), fixtures + a `tools/` wrapper gate, Python
fake producer/consumer, semantics doc. Follow §4 verbatim — `source_frame` and
`pose_quality` are per-detection (self-describing; leaves room for a future
hybrid producer that mixes sources). `bbox_3d` accepts exactly one of the two
forms (both present is rejected), with two fixtures pinning both. C1 is
**3D-only**: the 2D/image domain (`bbox`, `boxes`, `image`, `pixels`, `mask`,
`depth_m`) is rejected anywhere in the message — the mirror of C2's raw-field
ban, enforcing "depth is a pluggable scalar behind the boundary". An empty
`detections` array is a valid state (§12 "no people"). v1 emits
`pose_quality: fixed_depth`; `mono_metric`/`stereo` are swaps behind C1.

**Consequences.** Module 1 (producer) and module 3 (consumer) build against the
schema + fakes, not each other's code. Upgrading depth source is additive.
Any shape change requires `schema_version++`.

## ADR-9: C3 card-lifecycle = command verb x card_state, with a transition machine (YAN-105)

**Context.** §4 describes C3 as "card commands + state machine: attach/detach
plus appear/expand/contract/disappear (card_state enum + transitions),
offset_rule, animation durations". The binding verbs (attach/detach) and the
visual states (appear/expand/contract/disappear) are two distinct axes, and the
expand/contract transitions happen while attached — neither attach nor detach.

**Decision.** Model each command as a `command` verb x a `card_state`, coupled:
`attach`→`appear`, `update`→`{expand, contract}`, `detach`→`disappear`. Adding
`update` (beyond the literal attach/detach) is the minimal way to carry the
mid-lifecycle transitions; documented in the semantics doc. The schema
validates shape + the static verb/state coupling; the **fake consumer**
(`CardLifecycleConsumer`) enforces the dynamic transition machine per card
(`detached`→appear→expand⇄contract→disappear→`detached`) and rejects illegal
transitions (e.g. update-before-attach, appear→contract). `offset_rule` reuses
the C2 shape; per-state default animation durations are documented.

**Consequences.** Module 2 (card) and the producer build against the schema +
the documented machine. `detached` is an implicit null state, never on the
wire. Adding a card_state or transition is a shape change (`schema_version++`),
not an additive field change.

## ADR-10: Module 1 C1 producer = 2.5D builder + IOU tracker + pluggable detection backend (YAN-108)

**Context.** YAN-108 builds the real C1 (`tracking_raw`) producer against the
frozen contract (ADR-8). v1 is yolov8n 2D detection → 2.5D 8-vertex box +
landmark + track lifecycle, depth a pluggable scalar, detection backend a
pluggable topology. No device; validation is L0 schema + L1 math + L2 replay.

**Decision.**
- **C1 lives in `vst_right_camera` native axes** (+X right, +Y down, +Z forward,
  positive z), matching `smartxr/geometry.py`. Module 3 owns the camera→head
  flip when it builds C2; module 1 never converts. (The frozen C1 *fake* used a
  negative-z synthetic anchor; the contract does not pin the sign, and the real
  producer uses the geometry.py convention so module 3's existing
  `vst_camera_point_to_head` consumes it correctly.)
- **2.5D box** (`smartxr/box_builder_2_5d.py`): project the bbox center to the
  scalar depth (reusing `geometry.project_bbox_center_to_camera_point`), size
  X/Y from the 2D bbox extent projected to metric at that depth
  (`extent_mode=projected_bbox`, default; `nominal_human` available), Z from a
  nominal human thickness. `pose_quality=fixed_depth`. `landmark` is derived from
  a rule over the 8 vertices (centroid default).
- **Depth is a `DepthSource`** (`tracking_raw_producer.py`): v1
  `ConstantDepthSource` → `constant_depth`/`fixed_depth`. Swapping to
  mono_metric/stereo changes the value + tags only, never the C1 shape (ADR-8).
- **Detection backend is pluggable** (`smartxr/detection_backend.py`):
  on_device / pc_offload / hybrid all emit normalized 2D boxes; tracker +
  producer are topology-independent. ncnn detector + verification tooling live
  in `tools/` behind optional numpy/opencv/ncnn; `smartxr/` stays dependency-free
  for the CI gate. `ReplayDetectionBackend` runs the contract with no model.
- **Lifecycle** (`smartxr/tracker.py`): greedy IOU,
  `tentative→confirmed→lost→deleted`, monotonic non-reused ids.
- **L2 fixture is built from REAL capture**: yolov8n detections on a 200-frame
  window are recorded to `tracking_raw_replay_detections.jsonl` and replayed
  through the producer into the golden `tracking_raw_replay_c1.jsonl`; the L2
  test reproduces it within a numeric tolerance (libm differs across OS) rather
  than by exact string match.

**Consequences.** Module 3 can build C1→C2 against this producer or the fake.
yolov8n recall on real VST imagery is adequate for v1 (see
`docs/yolov8n_vst_verification.md`), so no T3 frame annotation is needed for v1.
Stereo/mono depth and the on-device ncnn backend are additive swaps behind C1.

## ADR-11: Module 3 C1→C2 converter = landmark→head alignment + owned calibration (YAN-110)

**Context.** YAN-110 builds module 3 (MR integration): convert C1 (`tracking_raw`,
3D camera-frame tracking) to C2 (`proxy_targets`, head/world transforms) for the
Godot card. C1/C2 are both frozen; the conversion is the alignment seam and the
only device-gated data module, but the math is fully headless.

**Decision.**
- **Position comes from the C1 `landmark.point`, not the raw bbox.** The landmark
  is the contract's designated derived anchor (centroid default); module 3
  transforms whatever landmark module 1 chose, sidestepping the
  vertices-vs-OBB bbox forms. Camera→head uses `smartxr.geometry`
  (`vst_camera_point_to_head`), so the converter is automatically pinned to the
  bbox-math dual-lock (ADR-5) and the GDScript card.
- **Calibration is owned here** (`Calibration` in `smartxr/mr_integration.py`):
  v1 monocular = default axis flip `[x,-y,-z]`; binocular = a row-major 4x4
  `right_eye_to_head` applied instead. A short/invalid matrix degrades to the flip
  (never errors). FOV (intrinsics) stays in module 1's projection because C1 is
  already 3D; module 3 applies only the extrinsic. Swapping calibration changes
  no contract or consumer.
- **Dedicated C1→C2 state map**, not `schema.canonical_state` (which maps C1
  `lost`→`tracked`): `tentative/confirmed→tracked`, `lost→predicted`,
  `deleted→lost`, unknown→`lost`. Optional `stale_after_ms` downgrades a lagging
  `tracked` pose to `stale` (baseline §12).
- **Empty C1 frame → no C2 message** (returns `None`). C2 requires non-empty
  targets/cards, so the valid "no people" state is represented by not publishing;
  the stateful converter advances `sequence` only on emitted frames. One card is
  bound to the primary target; per-target card lifecycle is module 2 / C3.
- **`source_frame.coordinate_space`** of `head`/`world` passes through unconverted;
  anything else is treated as a camera frame and flipped.
- **Display wiring** = `tools/convert_tracking_raw_to_proxy_targets.py`, which
  validates both ends (C1 in, C2 out) and feeds the existing proxy_targets path;
  the converted C2 needs no consumer change.

**Consequences.** Module 3's alignment is locked at L0/L1/L2 fully headless
(`tests/test_mr_integration.py` + the new `proxy_targets_from_c1_sample.json`
gate); the GDScript/Godot consumer is unchanged. L3 device alignment smoke is
documented in `docs/mr_integration.md` and pending a headset (with YAN-102). The
binocular `right_eye_to_head` is an additive calibration swap.

## ADR-12: Module 3 live bridge = C1 WS client + C2 WS server, shared transport client (YAN-110 A)

**Context.** With the converter (ADR-11) and the merged live C1 publisher
(`smartxr.cli.tracking_raw_publisher`, the YAN-108 PC chain) both in place, the
missing piece is the live glue that drives the Godot card from a live C1 source
instead of a static file. This closes the full PC headless chain
`NV12 -> ncnn -> C1 producer -> C1 WS -> [align] -> proxy_targets WS -> card`.

**Decision.**
- **The bridge is both a WS client and a WS server**
  (`smartxr/cli/mr_integration_bridge.py`): it subscribes to the upstream C1
  `/tracking_raw` and serves converted C2 on `/proxy_targets` (the stream the card
  already consumes). Per card connection it opens a fresh C1 subscription and a
  fresh `TrackingRawToProxyTargetsConverter`, so the C2 `sequence` restarts per
  card — matching the C1 publisher's per-client producer.
- **It reuses the unchanged converter**, so the live path and the file path
  (`convert_tracking_raw`) emit byte-identical C2. Empty C1 frames convert to
  `None` and are simply not forwarded (the card idles/holds, baseline §12). The
  card disconnect is noticed promptly via a `select` poll timeout on the upstream
  read between forwards.
- **Client WS primitives moved into `smartxr.transport`** (`client_handshake`,
  `encode_masked_text_frame`, `encode_masked_control_frame`,
  `read_server_text_frame`, `read_exact`); the C1 monitor was refactored to use
  them, removing one of the duplicated copies. (`tools/monitor_proxy_targets_live_stream.py`
  keeps its own copy for now — tools-path import, out of this slice's scope.)
- **Calibration loading centralized** as `mr_integration.load_calibration`,
  shared by the convert CLI and the bridge.

**Consequences.** Module 3 now has a live L2: a real C1 publisher -> bridge ->
card reader round-trip (`tests/test_mr_integration_bridge.py`) plus the
dependency-free `tools/run_mr_integration_bridge_harness.ps1`. Still fully
headless and Python-only; the Godot consumer is unchanged. The remaining gap is
unchanged: the L3 on-device alignment smoke (needs a headset + module 6).
