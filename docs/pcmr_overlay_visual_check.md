# PCMR overlay visual check

`tools\run_windows_pcmr_overlay_visual_check.ps1` is the one-command manual
runner for checking the Antman passthrough overlay in a PCMR headset.

Use this runner when a human needs to look through the headset and confirm the
overlay is visible, transparent, and positioned correctly. It is intentionally
different from `tools\run_windows_pcmr_proxy_targets_live.ps1`: the live runner
is an automated validation harness and exits as soon as proxy_targets status is
good, while this visual-check runner holds Godot open until the user closes the
Godot window or presses `Ctrl+C`.

## Command

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_windows_pcmr_overlay_visual_check.ps1
```

Optional parameters mirror the managed fake publisher defaults:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_windows_pcmr_overlay_visual_check.ps1 `
  -Port 8767 `
  -Mode moving `
  -Hz 20 `
  -LogEvery 20
```

## What the runner does

The runner wraps the previously manual two-terminal flow with a managed fake proxy_targets publisher:

- Starts `tools\fake_proxy_targets_publisher.py` on
  `ws://127.0.0.1:8767/proxy_targets`.
- Disables the GXR extension for Windows PCMR runtime use via
  `tools\set_gxr_extension.ps1 -Mode disable`.
- Sets `PROXY_TARGETS_WS_URL` to the managed fake publisher URL.
- Sets `SMARTXR_USE_PASSTHROUGH_OVERLAY=1`.
- Launches Godot in the foreground with `--path godot-android`.
- On exit, stops the fake publisher, restores the two environment variables,
  and re-enables the GXR extension for Android export.

## Expected headset view

Look straight ahead in the headset. The expected overlay is a small translucent
green quad with this text:

```text
PASSTHROUGH OVERLAY
```

The quad is approximately `0.42m x 0.20m`, placed in front of the camera at
roughly `1.5m`. It follows the headset camera, so it should stay generally in
front of the user's view rather than staying fixed at a world-space room
position.

Passing visual signs:

- The green panel is visible.
- The `PASSTHROUGH OVERLAY` text is readable.
- The panel is translucent rather than a solid black rectangle.
- There is no obvious flicker or off-screen placement.

If the visible result looks wrong but
`user://passthrough_overlay_status.json` reports `overlay_enabled: true`,
`layer_visible: true`, and `status: "ready"`, continue debugging overlay quad
size/position/UI anchors. The proxy_targets and TargetSource paths are not the
first suspects in that case.

## Related automated checks

Use `tools\run_windows_pcmr_proxy_targets_live.ps1` for automated status
validation. That script starts a managed fake publisher, runs PCMR, validates
`proxy_targets_live_status.json`, and exits once the validation passes. It is
not suitable for slow visual inspection because it intentionally closes Godot
after status is good.

Use the status files for follow-up evidence:

| File | Purpose |
|---|---|
| `%APPDATA%\Godot\app_userdata\demo_run\passthrough_overlay_status.json` | Overlay enablement, layer creation, visibility, alpha blend, and layer position. |
| `%APPDATA%\Godot\app_userdata\demo_run\proxy_targets_live_status.json` | proxy_targets WebSocket, packet, target, and card attachment status. |
