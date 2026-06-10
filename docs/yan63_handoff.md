# YAN-63 Handoff: VST / External Target Attach

## Summary

YAN-63 implements the core path for attaching the SmartXR Card to a live VST or
external tracked target:

```text
Antman VST / external detector
-> proxy_targets WebSocket
-> Godot ProxyTargetsConsumer
-> ProxyTargetsCardAdapter
-> CardAnchor attach/apply
-> optional passthrough overlay for VST background + Godot Card
```

The basic function is working in Windows PCMR validation. The remaining known
gap is strict visual alignment between the Card and the person in the VST image.
That calibration work has been split to backlog issue YAN-71.

## Current Branch And Commits

Working branch:

```text
agent/agent/170798bc-proxy-binding
```

Relevant local commits:

```text
51cb18b YAN-63: apply VST head targets in world space
a442f36 YAN-63: add Antman passthrough overlay path
6a94ee7 Set proxy target zero offset and 5m depth
fc7b773 Fix proxy target adapter startup
1e1873b YAN-63: bind single proxy target to card
19fd8da YAN-63: add proxy target apply gate
```

Known local untracked files at handoff time:

```text
godot-android/Logs/
yolov8n.pt
```

These were not part of the YAN-63 implementation commits.

## What Is Complete

The following pieces are implemented and validated:

- Godot can consume `proxy_targets` messages over WebSocket.
- A live target can be represented as a proxy `Node3D`.
- A single live proxy target can bind to `CardAnchor` without an explicit card
  payload.
- Card offset defaults for the live VST path are zeroed.
- Default projected depth is 5m.
- Apply-layer observability is written to `proxy_targets_live_status.json`.
- Windows PCMR runner can validate `proxy_targets` with an attached Card.
- Antman-style passthrough overlay is available with alpha blend.
- `source=vst` defaults to `coordinate_space=head`.
- Godot applies `head_reference.global_transform * head_transform` before
  writing the proxy target global transform.
- Status reports `world_from_head_applied=true` when the head-to-world transform
  is applied.

## Known Not Complete

Strict Card-to-person visual alignment is not complete.

The current implementation assumes VST publisher output is already in Godot head
convention:

```text
x right
y up
z forward as negative
```

If the publisher is still outputting raw VST camera convention:

```text
x right
y down
z forward as positive
```

then a `vst_camera -> head -> world` conversion is still needed. This is tracked
under YAN-71.

Other likely calibration work for YAN-71:

- right-eye-to-head transform
- FOV / focal length model
- bbox anchor point selection
- fixed 5m depth error
- optional camera pose diagnostics in status JSON

## Key Files

Godot runtime:

```text
godot-android/scripts/AndroidMovingCard.gd
godot-android/scripts/proxy_targets_consumer.gd
godot-android/scripts/proxy_targets_card_adapter.gd
```

Publisher and tools:

```text
tools/antman_vst_proxy_targets_live_publisher.py
tools/run_antman_vst_proxy_targets_live_publisher.ps1
tools/run_windows_pcmr.ps1
tools/validate_proxy_targets_live_status.py
tools/fake_proxy_targets_publisher.py
```

Tests:

```text
tests/test_godot_android_mesh_card.py
tests/test_proxy_targets_live_status_validator.py
tests/test_run_windows_pcmr.py
tests/test_antman_vst_proxy_targets_live_publisher.py
tests/test_proxy_targets_payload_schema.py
```

Payload contract:

```text
docs/proxy_targets_payload_contract.md
```

## Runtime Commands

Run from repository root:

```powershell
cd C:\Users\wyxia\multica_workspaces_desktop-api.multica.ai\3d9e7c6a-abbf-4866-b438-34afef9277d0\170798bc\workdir\SmartXR
```

Start the Antman VST live publisher in one PowerShell window:

```powershell
.\tools\run_antman_vst_proxy_targets_live_publisher.ps1 -AntmanRoot E:\xia\Antman_smart -Port 8766
```

Short automatic gate check:

```powershell
.\tools\run_windows_pcmr.ps1 -UseAntmanPassthroughOverlay -ValidateProxyTargets -ProxyTargetsWsUrl ws://127.0.0.1:8766/proxy_targets -ProxyTargetsTimeoutSeconds 20
```

Important: `-ValidateProxyTargets` is a short validation mode. It starts Godot,
waits until the status satisfies the attached gate, then stops Godot. This is
expected and is not a crash.

Long-running visual PCMR session:

```powershell
.\tools\run_windows_pcmr.ps1 -UseAntmanPassthroughOverlay -ProxyTargetsWsUrl ws://127.0.0.1:8766/proxy_targets
```

Use the long-running mode for headset visual checks.

## Status Files

Proxy target / Card attach status:

```powershell
Get-Content "$env:APPDATA\Godot\app_userdata\demo_run\proxy_targets_live_status.json"
```

Important fields:

```json
{
  "ws_connected": true,
  "ws_subscribed": true,
  "parsed": 1,
  "live": 1,
  "attachments": 1,
  "card_apply_count": 1,
  "card_attach_target_id": "vst-person-*",
  "target_coordinate_space": "head",
  "world_from_head_applied": true,
  "proxy_local_position": "...",
  "proxy_world_position": "...",
  "card_node_position": "..."
}
```

Expected relation:

```text
card_node_position ~= proxy_world_position
```

Passthrough overlay status:

```powershell
Get-Content "$env:APPDATA\Godot\app_userdata\demo_run\passthrough_overlay_status.json"
```

Expected fields:

```json
{
  "overlay_enabled": true,
  "requested_blend_mode": "alpha_blend",
  "viewport_transparent_bg": true,
  "layer_created": true,
  "layer_alpha_blend": true,
  "status": "ready"
}
```

## Validation Commands

Focused head-to-world and status tests:

```powershell
python -m unittest tests.test_godot_android_mesh_card.GodotAndroidMeshCardTests.test_proxy_targets_consumer_converts_vst_head_space_to_world tests.test_godot_android_mesh_card.GodotAndroidMeshCardTests.test_proxy_targets_status_reports_head_to_world_diagnostics
```

Related regression tests:

```powershell
python -m unittest tests.test_godot_android_mesh_card tests.test_proxy_targets_live_status_validator tests.test_run_windows_pcmr tests.test_proxy_targets_payload_schema tests.test_antman_vst_proxy_targets_live_publisher
```

Project validation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests\validate_project.ps1
```

## Interpreting Failures

`adapter_null`

- Godot did not create or bind the proxy target adapter.
- Check `_build_proxy_targets_validation()` in `AndroidMovingCard.gd`.

`ws_connected=false`

- Godot did not connect to the publisher.
- Verify publisher is running and the URL is `ws://127.0.0.1:8766/proxy_targets`.

`parsed=0` or `live=0`

- Godot is not receiving valid `proxy_targets` messages.
- Check publisher output and schema.

`card_apply_count=0`

- The proxy target was not applied to Card.
- Check `ProxyTargetsCardAdapter` and target/card binding.

`world_from_head_applied=false`

- The consumer did not apply head-to-world conversion.
- Check that target `source` is `vst` or `coordinate_space` is `head`, and that
  `set_head_reference(_camera)` ran.

Card visible but not strictly aligned with the person

- This is the known YAN-71 calibration gap.
- Do not debug WebSocket or Card apply first; check coordinate convention,
  camera/head transform, FOV, right-eye-to-head, bbox anchor, and depth.

## Convergence Items For YAN-63

Before closing YAN-63, finish these administrative items:

1. Decide final issue status: `in_review` if a PR/review is needed, or `done` if
   the local validated commits are accepted as the deliverable.
2. Create or update a PR if the workflow requires remote review. No PR was
   created in this local session.
3. Keep YAN-71 as backlog for strict visual calibration.
4. Do not include `godot-android/Logs/` or `yolov8n.pt` in the YAN-63 commit
   unless a later task explicitly decides they are required artifacts.

## Handoff Recommendation

Treat YAN-63 as the completed integration baseline. Future work should start from
the status files above and the YAN-71 calibration task rather than reopening the
WebSocket, adapter, passthrough, or Card apply layers unless those status gates
regress.
