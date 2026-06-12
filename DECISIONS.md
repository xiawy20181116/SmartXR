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
