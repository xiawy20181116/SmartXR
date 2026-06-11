# HANDOFF

## State (after M1+M2, YAN-73)

- All 118 Python tests pass (`python -m unittest tests/test_*.py`).
- Schema gate passes on both fixtures.
- Smoke-tested: `vst_proxy_targets_publisher.py --print-once`, `ws_control.py
  --help`, `windows_server.ws_control` module import.
- **Not verified on-device**: the Godot changes (`smartxr_options.gd`,
  `AndroidMovingCard.gd` edits) are validated by the repo's static-source
  tests only — there is no Godot runtime in this environment. Before relying
  on them, open the project in Godot 4 once (script parse check) and run the
  existing live harness against a device or the script-only probes.

## Unfinished / risks

- `WS_URL` still defaults to the historical LAN IP `ws://10.1.98.195:8766/control`
  (kept deliberately for behavior parity). Override via `SMARTXR_CONTROL_WS_URL`
  or `user://smartxr_options.json`; consider changing the default to
  `127.0.0.1` in a follow-up.
- `resolve_bool` returning a Variant from `_config` may emit an UNSAFE_CAST
  style warning in strict Godot editors; harmless, but can be silenced with an
  explicit `bool()` cast if the project enables treat-warnings-as-errors.
- M3 (god-object split), M4 (TargetSource interface), M5 (docs) not started —
  see TASKS.md.
- GDScript bbox math in `AndroidMovingCard.gd` still duplicates
  `smartxr/geometry.py`; shared test vectors are planned for M4.

## How to continue

Start M3 by extracting the status HUD + diagnostics-file writer (lowest-risk
subsystem) from `AndroidMovingCard.gd` into its own node, updating the pinned
assertions in `tests/test_godot_android_mesh_card.py` in the same commit.
