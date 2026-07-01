# SmartXR runtime options (Godot)

`godot-android/scripts/smartxr_options.gd` (`SmartXROptions`) centralizes
runtime configuration so deployment differences (developer PC IP, device vs
simulator endpoints, feature toggles) never require source edits.

## Resolution order

For every setting, highest priority first:

1. **Environment variable** — e.g. set per `adb shell setprop` wrapper, test
   harness, or desktop run.
2. **Config file** — `user://smartxr_options.json` on the device by default,
   or the file named by `SMARTXR_OPTIONS_PATH` in desktop runners. The Windows
   live/replay scripts default this path to `config\smartxr_options.json`.
3. **Default** — the script const passed by the caller (unchanged behavior
   when neither override exists).

## Supported settings

| Config key | Environment variable | Default (const) | Meaning |
|---|---|---|---|
| config path | `SMARTXR_OPTIONS_PATH` | `user://smartxr_options.json` | Optional JSON file path override for desktop/manual runs |
| `control_ws_url` | `SMARTXR_CONTROL_WS_URL` | `WS_URL` in `AndroidMovingCard.gd` | Keyboard control channel (`ws_control.py` server) |
| `proxy_targets_ws_url` | `PROXY_TARGETS_WS_URL` | `PROXY_TARGETS_WS_URL` const | proxy_targets live stream endpoint |
| `proxy_targets_ws_enabled` | `SMARTXR_PROXY_TARGETS_WS_ENABLED` | `PROXY_TARGETS_WS_ENABLED` const | Whether the live consumer runs |
| `proxy_targets_anchor_mode` | `SMARTXR_PROXY_TARGETS_ANCHOR_MODE` | `PROXY_TARGETS_ANCHOR_MODE` const (`dynamic`) | Card/proxy comparison mode: `dynamic` updates Godot world pose only on fresh targets and holds the previous world pose for stale/held packets; `world_latched` latches the first fresh target's Godot world pose until lost or reset |
| `proxy_targets_head_z_mode` | `SMARTXR_PROXY_TARGETS_HEAD_Z_MODE` | `PROXY_TARGETS_HEAD_Z_MODE` const (`negative_z_forward`) | Head-space Z convention comparison mode: `negative_z_forward` keeps the publisher's current Godot-style `-Z` forward target; `positive_z_forward` flips head-space Z before applying the XR head reference |
| `proxy_targets_pose_trace_path` | `SMARTXR_PROXY_TARGETS_POSE_TRACE_PATH` | empty | Optional JSONL output path for per-frame Godot pose trace. Each line records head pose, proxy world pose, card world pose, and anchor state; empty disables it |
| `proxy_targets_card_offset_rule` | see flat keys below | `PROXY_TARGETS_CARD_OFFSET_RULE` const / publisher default | Nested object for card placement next to a proxy target. This is read by both the Python sender and Godot fallback |
| `proxy_targets_card_offset_mode` | `SMARTXR_PROXY_TARGETS_CARD_OFFSET_MODE` | `depth_scaled_right_half_width` | Flat override for `proxy_targets_card_offset_rule.mode` |
| `proxy_targets_card_depth_scale` | `SMARTXR_PROXY_TARGETS_CARD_DEPTH_SCALE` | `1.3` | Multiplies target depth before placing the card, so `1.3` moves it behind the person relative to the viewer |
| `proxy_targets_card_depth_offset_m` | `SMARTXR_PROXY_TARGETS_CARD_DEPTH_OFFSET_M` | `0.0` | Adds meters after `depth_scale`; positive moves farther along the viewer-to-target depth ray, negative moves closer |
| `proxy_targets_card_right_width_fraction` | `SMARTXR_PROXY_TARGETS_CARD_RIGHT_WIDTH_FRACTION` | `0.5` | Horizontal offset as a fraction of estimated person width. Positive is viewer-right, negative is viewer-left |
| `proxy_targets_card_right_angle_deg` | `SMARTXR_PROXY_TARGETS_CARD_RIGHT_ANGLE_DEG` | `15.0` | Horizontal offset angle for `depth_scaled_right_angle`; the right offset is `tan(angle) * final_depth` |
| `proxy_targets_card_up_m` | `SMARTXR_PROXY_TARGETS_CARD_UP_M` | `0.0` | Extra vertical offset in meters |
| `status_hud_visible` | `SMARTXR_STATUS_HUD_VISIBLE` | `STATUS_HUD_VISIBLE` const | Whether the in-headset diagnostic text HUD is visible; status JSON is still written when hidden |
| `vst_horizontal_fov_deg` | `SMARTXR_VST_HORIZONTAL_FOV_DEG` | `BBOX_HORIZONTAL_FOV_DEG` const | Right-eye VST horizontal FOV for bbox projection |
| `vst_vertical_fov_deg` | `SMARTXR_VST_VERTICAL_FOV_DEG` | `BBOX_VERTICAL_FOV_DEG` const | Right-eye VST vertical FOV for bbox projection |
| `vst_principal_point_x` | `SMARTXR_VST_PRINCIPAL_POINT_X` | image center fallback | Right-eye principal point X in pixels |
| `vst_principal_point_y` | `SMARTXR_VST_PRINCIPAL_POINT_Y` | image center fallback | Right-eye principal point Y in pixels |
| `vst_focal_length_x` | `SMARTXR_VST_FOCAL_LENGTH_X` | FOV-derived fallback | Right-eye focal length X in pixels; preferred when runtime calibration provides `fx` |
| `vst_focal_length_y` | `SMARTXR_VST_FOCAL_LENGTH_Y` | FOV-derived fallback | Right-eye focal length Y in pixels; preferred when runtime calibration provides `fy` |

`PROXY_TARGETS_WS_URL` keeps its historical environment-variable name (it
predates this class and is referenced by existing harnesses); new settings use
the `SMARTXR_` prefix.

Boolean environment values accept `1/true/yes/on` (case-insensitive); any
other non-empty value is false.

## Example config file

The repo includes an editable desktop config at `config\smartxr_options.json`.
The stereo live and package replay runners pass it to both the Python
publisher and Godot receiver by default, so this is the fastest place to tune
card depth/right offset during PCMR testing.

The stereo live/replay runners also enable Godot pose tracing for experiments
and write it to their work dir as `godot_pose_trace.jsonl`. Override
`proxy_targets_pose_trace_path` or `SMARTXR_PROXY_TARGETS_POSE_TRACE_PATH` when
you want a different location; leave it empty to disable tracing in normal app
runs.

`config\smartxr_options.json` or `user://smartxr_options.json`:

```json
{
  "control_ws_url": "ws://192.168.1.20:8766/control",
  "proxy_targets_ws_url": "ws://192.168.1.20:8766/proxy_targets",
  "proxy_targets_ws_enabled": true,
  "proxy_targets_anchor_mode": "world_latched",
  "proxy_targets_head_z_mode": "negative_z_forward",
  "proxy_targets_pose_trace_path": "",
  "proxy_targets_card_offset_rule": {
    "mode": "depth_scaled_right_angle",
    "offset_space": "world",
    "depth_scale": 1.3,
    "depth_offset_m": 2.0,
    "right_angle_deg": 15.0,
    "right_width_fraction": 0.5,
    "up_m": 0.0,
    "fallback": "hold_last_pose"
  },
  "status_hud_visible": true,
  "vst_horizontal_fov_deg": 70.0,
  "vst_vertical_fov_deg": 43.0,
  "vst_principal_point_x": 436.0,
  "vst_principal_point_y": 326.0,
  "vst_focal_length_x": 0.0,
  "vst_focal_length_y": 0.0
}
```

For quick A/B, edit only these values:

```json
{
  "proxy_targets_card_offset_rule": {
    "depth_scale": 1.15,
    "depth_offset_m": 0.2,
    "right_angle_deg": 12.0,
    "right_width_fraction": -0.5,
    "up_m": 0.0
  }
}
```

You can point a run at another file with:

```powershell
.\tools\run_windows_pcmr_stereo_proxy_targets_live.ps1 `
  -SmartXROptionsPath ".tmp\smartxr_options_ab.json"
```

`VSTCapture.status_snapshot()` reports `horizontal_fov_deg`,
`vertical_fov_deg`, `principal_point_px`, and `focal_length_px`, so
`proxy_targets_live_status.json` can show whether a run used the default image
center/FOV fallback or calibrated right-eye intrinsics.

For the June 23, 2026 Antman dump on YAN-115, choose the calibration matching
the live frame source:

```powershell
# camerapara_RB, 640x480 equidistant stream
powershell -File tools\run_antman_vst_proxy_targets_live_publisher.ps1 `
  -ShmEye Right `
  -PrincipalPointX 318.6850230882512 `
  -PrincipalPointY 240.9308751924166 `
  -FocalLengthX 241.14032906751385 `
  -FocalLengthY 241.60074879502008

# camerapara_Scene_R, 2328x1744 no-distortion scene stream
powershell -File tools\run_antman_vst_proxy_targets_live_publisher.ps1 `
  -ShmEye Right `
  -PrincipalPointX 1164 `
  -PrincipalPointY 872 `
  -FocalLengthX 872 `
  -FocalLengthY 872
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
