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

## ADR-3: Update static-source tests instead of faking strings in wrappers

**Context.** Several tests assert implementation strings inside specific tool
files (e.g. `def build_proxy_targets_message(` in the fake publisher).

**Decision.** Repoint those assertions at the package file where the
implementation now lives, rather than padding wrapper files with dead strings
to satisfy greps.

**Consequences.** Tests keep guarding the real implementation; two test
methods were updated (`test_fake_proxy_targets_publisher.py` banner check,
`test_godot_android_mesh_card.py` publisher/URL checks).
