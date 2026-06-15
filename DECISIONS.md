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
