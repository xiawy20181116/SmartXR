# TASKS — encapsulation plan (YAN-73)

Roadmap agreed in Multica issue YAN-73: adopt xrblocks-style runtime
encapsulation on the Godot side and pi-style layered packaging on the Python
side.

## Completed

- [x] **M1 — Configuration**: `SmartXROptions` (`godot-android/scripts/smartxr_options.gd`)
  with env → `user://smartxr_options.json` → const-default resolution.
  Control WS URL (previously a hardcoded LAN IP at the call site),
  proxy_targets WS URL, and the live-consumer enable flag now route through it.
  Docs: `docs/smartxr_options.md`. Tests: `tests/test_godot_smartxr_options.py`.
- [x] **M2 — Python packaging**: `smartxr/` package
  (schema / geometry / transport / frames / publisher / cli) with strict
  one-way deps; `tools/*.py` reduced to compatibility wrappers; WebSocket
  framing deduplicated out of `ws_control.py`, `fake_*` and `vst_*`
  publishers; antman live publisher no longer imports private functions from
  sibling tools. `pyproject.toml` added.
- [x] **M3 step 1 — StatusHud** (YAN-74): status label rendering and the
  `user://` status-file writers (`proxy_targets_live_status.json`,
  `passthrough_overlay_status.json`) extracted from `AndroidMovingCard.gd`
  into `godot-android/scripts/status_hud.gd`. Seam: the card assembles a
  per-frame snapshot Dictionary (`_build_status_snapshot()`), StatusHud only
  formats and writes (ADR-4). Runtime probe:
  `tools/run_godot_status_hud_probe.ps1` (29 checks). Tests:
  `tests/test_godot_status_hud.py`.
- [x] **M3 step 2 — TargetRegistry** (YAN-75): the TargetRegistry and
  Node3DTargetAdapter inner classes extracted from `AndroidMovingCard.gd`
  into `godot-android/scripts/target_registry.gd` (RefCounted,
  dependency-free; the card passes itself as the adapters' lookup root).
  Card public API unchanged (`register_node3d_target`, `unregister_target`,
  `attach_to_target`). TrackableTarget / VSTTargetAdapter stay in the card
  (target-source subsystem, M4). Runtime probe:
  `tools/run_godot_target_registry_probe.ps1` (32 checks). Tests:
  `tests/test_godot_target_registry.py`.
- [x] **M3 step 3 — WSTransport** (YAN-76): the two near-duplicate
  WebSocketPeer connect/poll/retry loops (control + proxy_targets) extracted
  from `AndroidMovingCard.gd` into `godot-android/scripts/ws_transport.gd`
  (RefCounted, dependency-free; the card instantiates two and keeps URL /
  enable-gate resolution, packet handling, error formatting, and the status
  snapshot per ADR-4). Also fixed a latent bug: the old subscribe path
  called the nonexistent `WebSocketPeer.set_write_mode()`, so the subscribe
  payload was never actually sent; WSTransport uses `send_text()`. Runtime
  probe: `tools/run_godot_ws_transport_probe.ps1` (30 checks, live fake
  publisher + accept-then-close retry listener). Tests:
  `tests/test_godot_ws_transport.py`.
- [x] **M3 step 4 — CardAttachment** (YAN-77): the card_id -> attachment
  store (`_card_attachments`), the `attach_to_target` / `detach_card`
  bodies, the `_update_target_attachments` per-frame pass, the fallback
  state machine (`hold_last_pose` / `detach` / `fade_out`), and the
  offset-rule math (modes right_top / right / top / front / custom-xyz,
  offset_space world / target, `TARGET_DEFAULT_OFFSET_RULE` defaults)
  extracted from `AndroidMovingCard.gd` into
  `godot-android/scripts/card_attachment.gd` (RefCounted, dependency-free;
  target lookup wired back into target_registry.gd via a resolver Callable,
  apply counter and detach-fallback mode flip stay card-side per ADR-4).
  Card public API and every status-snapshot key unchanged. Runtime probe:
  `tools/run_godot_card_attachment_probe.ps1` (48 checks). Tests:
  `tests/test_godot_card_attachment.py`.

## Next (not started)

- [ ] **M3 — Split `AndroidMovingCard.gd`** remaining subsystem:
  XRBootstrap (`_try_init_xr` + camera/origin setup), with the scene tree
  unchanged. Move one subsystem at a time; keep
  `tests/test_godot_android_mesh_card.py` green at each step (update pinned
  assertions alongside each move). StatusHud (step 1), TargetRegistry
  (step 2), WSTransport (step 3), and CardAttachment (step 4) are done —
  see above.
- [ ] **M4 — TargetSource strategy interface**: unify on-device ncnn, remote
  proxy_targets WS, and fixture replay behind one source interface; promote
  the payload contract doc into shared test vectors used by both the Python
  and GDScript bbox math.
- [ ] **M5 — Per-subsystem docs** following `docs/smartxr_options.md` style.

## Verification

```powershell
# Full suite (131 tests)
python -m unittest (Get-ChildItem tests\test_*.py | ForEach-Object { "tests/$($_.Name)" })

# Schema gate
python tools\validate_proxy_targets_payload_schema.py --input godot-android\fixtures\proxy_targets_sample.json --input godot-android\fixtures\vst_proxy_targets_sample.json

# Godot runtime probes (headless, no-project mode)
powershell -File tools\run_godot_smartxr_options_probe.ps1
powershell -File tools\run_godot_status_hud_probe.ps1
powershell -File tools\run_godot_target_registry_probe.ps1
powershell -File tools\run_godot_ws_transport_probe.ps1
powershell -File tools\run_godot_card_attachment_probe.ps1
powershell -File tools\run_godot_script_only_websocket_probe.ps1
# consumer-only needs a publisher on :8766 first (fake_proxy_targets_publisher.py)
powershell -File tools\run_godot_proxy_targets_consumer_only.ps1
```
