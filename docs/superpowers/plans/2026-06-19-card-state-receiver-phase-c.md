# Card State Receiver Phase C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-express the tracked SmartXR card host around `CardState`, `CardView`, and `CardReceiver` while keeping headless status snapshots behavior-identical.

**Architecture:** Add a pure `card_state.gd` for command/bbox/manual anchor data and a `card_receiver.gd` for proxy_targets transport-to-state/view glue. `AndroidMovingCard.gd` remains the XR/VST host, delegates presentation to the existing view/presenter scripts, and delegates proxy_targets live handling to `CardReceiver`.

**Tech Stack:** Godot 4.6 GDScript, no-project script-only probes, Python `unittest` static guards, PowerShell probe runners.

---

### Task 1: Failing Guards

**Files:**
- Modify: `tests/test_godot_android_mesh_card.py`
- Modify: `tests/test_gdscript_probes_ci.py`

- [ ] Add assertions for `card_state.gd`, `card_receiver.gd`, their preloads, and the `run_godot_card_state_probe.ps1` CI/doc entries.
- [ ] Run `python -m unittest tests.test_godot_android_mesh_card tests.test_gdscript_probes_ci`.
- [ ] Expected result: fail because the new scripts and runner do not exist yet.

### Task 2: CardState

**Files:**
- Create: `godot-android/scripts/card_state.gd`
- Create: `godot-android/tests/script_only_card_state_probe.gd`
- Create: `tools/run_godot_card_state_probe.ps1`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/gdscript_probes_ci.md`
- Modify: `godot-android/scripts/AndroidMovingCard.gd`

- [ ] Implement `CardState` as `RefCounted`, with `command_state()`, `apply_command_state()`, bbox payload helpers, manual tick, attach/detach mode transitions, and read accessors.
- [ ] Probe valid command-state copy, invalid bbox rejection, bbox payload clamping, manual yaw wrap, and attach/detach mode behavior.
- [ ] Wire host fields through `_card_state` and keep the same snapshot keys and values.

### Task 3: CardReceiver

**Files:**
- Create: `godot-android/scripts/card_receiver.gd`
- Modify: `godot-android/scripts/AndroidMovingCard.gd`
- Modify: `godot-android/tests/script_only_card_state_probe.gd`

- [ ] Implement `CardReceiver` as the proxy_targets consumer/adapter + `WSTransport` owner.
- [ ] Expose `setup()`, `connect_if_enabled()`, `poll()`, `apply_live_payload()`, `status_values()`, and `target_source()`.
- [ ] Move `_connect_proxy_targets_ws`, `_poll_proxy_targets_ws`, `_on_proxy_targets_ws_packet`, and `_apply_proxy_targets_live_payload` behavior into the receiver.

### Task 4: Verification

**Files:**
- Existing test suite only.

- [ ] Run `python -m unittest tests.test_godot_android_mesh_card tests.test_godot_ws_transport tests.test_godot_target_source tests.test_godot_status_hud tests.test_gdscript_probes_ci`.
- [ ] Run `powershell -ExecutionPolicy Bypass -File tools/run_godot_card_state_probe.ps1` if the configured Godot binary exists.
- [ ] Run broader Python tests if time permits.
