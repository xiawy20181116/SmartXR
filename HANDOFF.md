# HANDOFF

## State (after M1+M2, YAN-73)

- All 118 Python tests pass (`python -m unittest tests/test_*.py`).
- Schema gate passes on both fixtures.
- Smoke-tested: `vst_proxy_targets_publisher.py --print-once`, `ws_control.py
  --help`, `windows_server.ws_control` module import.
- **Godot runtime verification done on the dev machine** (Godot 4.6.2
  headless): the new options probe passes all 10 checks
  (`tools\run_godot_smartxr_options_probe.ps1`), and both pipeline harnesses
  pass — `run_godot_script_only_websocket_probe.ps1` (starts the refactored
  M2 publisher itself) and `run_godot_proxy_targets_consumer_only.ps1`
  against a live `fake_proxy_targets_publisher.py` (`parsed=1`,
  `registered_targets=1`). See "Runtime verification" in
  `docs/smartxr_options.md`.
- **Still not verified**: `AndroidMovingCard.gd` as a whole app — headless
  project mode boots the main scene which never exits, so that path needs
  the editor or a device (its options wiring is three one-line delegates
  covered by static tests; the resolution logic they call is the
  runtime-verified part).

## Unfinished / risks

- `WS_URL` still defaults to the historical LAN IP `ws://10.1.98.195:8766/control`
  (kept deliberately for behavior parity). Override via `SMARTXR_CONTROL_WS_URL`
  or `user://smartxr_options.json`; consider changing the default to
  `127.0.0.1` in a follow-up.
- `resolve_bool` returning a Variant from `_config` may emit an UNSAFE_CAST
  style warning in strict Godot editors; harmless, but can be silenced with an
  explicit `bool()` cast if the project enables treat-warnings-as-errors.
- Scripts that script-only probes load must not self-reference their own
  `class_name` (it is unregistered in no-project mode). `smartxr_options.gd`
  was fixed accordingly (untyped static constructors + bare `new()`); keep
  the rule for future probe-visible scripts.
- M3 (god-object split), M4 (TargetSource interface), M5 (docs) not started —
  see TASKS.md.
- GDScript bbox math in `AndroidMovingCard.gd` still duplicates
  `smartxr/geometry.py`; shared test vectors are planned for M4.

## How to continue

Start M3 by extracting the status HUD + diagnostics-file writer (lowest-risk
subsystem) from `AndroidMovingCard.gd` into its own node, updating the pinned
assertions in `tests/test_godot_android_mesh_card.py` in the same commit.
