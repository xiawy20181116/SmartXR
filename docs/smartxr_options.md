# SmartXR runtime options (Godot)

`godot-android/scripts/smartxr_options.gd` (`SmartXROptions`) centralizes
runtime configuration so deployment differences (developer PC IP, device vs
simulator endpoints, feature toggles) never require source edits.

## Resolution order

For every setting, highest priority first:

1. **Environment variable** — e.g. set per `adb shell setprop` wrapper, test
   harness, or desktop run.
2. **Config file** — `user://smartxr_options.json` on the device, a flat JSON
   object keyed by setting name.
3. **Default** — the script const passed by the caller (unchanged behavior
   when neither override exists).

## Supported settings

| Config key | Environment variable | Default (const) | Meaning |
|---|---|---|---|
| `control_ws_url` | `SMARTXR_CONTROL_WS_URL` | `WS_URL` in `AndroidMovingCard.gd` | Keyboard control channel (`ws_control.py` server) |
| `proxy_targets_ws_url` | `PROXY_TARGETS_WS_URL` | `PROXY_TARGETS_WS_URL` const | proxy_targets live stream endpoint |
| `proxy_targets_ws_enabled` | `SMARTXR_PROXY_TARGETS_WS_ENABLED` | `PROXY_TARGETS_WS_ENABLED` const | Whether the live consumer runs |
| simulator mode | `SMARTXR_SIM_MODE` | unset / false | Forces the desktop simulator path: no OpenXR interface lookup success, fallback camera movement, and HUD `SIM` line |

`PROXY_TARGETS_WS_URL` keeps its historical environment-variable name (it
predates this class and is referenced by existing harnesses); new settings use
the `SMARTXR_` prefix.

Boolean environment values accept `1/true/yes/on` (case-insensitive); any
other non-empty value is false.

## Desktop simulator

Use the desktop simulator when running the SmartXR card on a Windows Godot
editor/player without a headset:

```powershell
powershell -File tools\run_desktop_sim.ps1 [-GodotExe <path to Godot 4 exe>]
```

The wrapper runs `tools\set_gxr_extension.ps1 -Mode disable` before project
startup, launches `godot-android` with `SMARTXR_SIM_MODE=1`, and re-enables the
extension after Godot exits. In simulator mode `AndroidMovingCard.gd` reuses the
normal card scene and card logic, but `SimBootstrap` injects a non-XR interface
provider so OpenXR/GXR startup does not run. The fallback camera becomes the
simulated head pose.

Controls:

- Left click captures the mouse; Esc releases it.
- Mouse motion changes yaw/pitch.
- WASD moves forward/back/left/right in head space.
- Q/E moves down/up.

## Example config file

`user://smartxr_options.json`:

```json
{
  "control_ws_url": "ws://192.168.1.20:8766/control",
  "proxy_targets_ws_url": "ws://192.168.1.20:8766/proxy_targets",
  "proxy_targets_ws_enabled": true
}
```

On Android, `user://` resolves under the app's files directory, e.g.
`/sdcard/Android/data/com.smartxr.godotcontrol/files/`.

## Runtime verification

Three levels, no device needed for the first two:

1. **Options resolution probe** (runtime, headless, ~3 s):

   ```powershell
   powershell -File tools\run_godot_smartxr_options_probe.ps1 [-GodotExe <path to Godot 4 exe>]
   ```

   Runs `godot-android/tests/script_only_smartxr_options_probe.gd` in
   no-project mode and asserts default / config-file / env resolution and
   bool parsing against the real script. Exit 0 + `PASS` means the M1 logic
   works at runtime. Status JSON lands in `.tmp\smartxr_options_probe\`.

2. **End-to-end pipeline harnesses** (runtime, headless):

   ```powershell
   # publisher started for you:
   powershell -File tools\run_godot_script_only_websocket_probe.ps1
   # or against a publisher you started yourself on :8766:
   python tools\fake_proxy_targets_publisher.py --host 127.0.0.1 --port 8766
   powershell -File tools\run_godot_proxy_targets_consumer_only.ps1
   ```

   Verifies Python publisher -> WebSocket -> Godot consumer -> card adapter
   (`ws_connected/parsed/registered_targets` in the status JSON).

3. **Full app** (`AndroidMovingCard.gd` end to end): requires the editor or a
   device — headless project mode boots the main scene, which reconnects
   WebSockets forever and never exits, so it cannot be scripted this way.
   Open the project once in Godot 4 (parse check) and use
   `tools\run_proxy_targets_live_manual_check.ps1` / on-device flows.

Note for probe authors: scripts loaded by the probes must not self-reference
their own `class_name` (no `-> SmartXROptions` return types, use bare
`new()`), because global class registration only happens in project mode.

## Adding a new setting

1. Add an `ENV_*` const and a typed accessor to `smartxr_options.gd`.
2. Keep the default as a script const at the call site and pass it into the
   accessor (`_options.my_setting(MY_CONST)`).
3. Document the key in the table above and pin it in
   `tests/test_godot_smartxr_options.py`.

This is M1 of the encapsulation plan (YAN-73); later milestones move more of
`AndroidMovingCard.gd`'s constants behind this class as subsystems are
extracted.
