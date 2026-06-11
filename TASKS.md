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

## Next (not started)

- [ ] **M3 — Split `AndroidMovingCard.gd`** remaining subsystem nodes:
  XRBootstrap, WSTransport, TargetRegistry, CardAttachment, with the scene
  tree unchanged. Move one subsystem at a time; keep
  `tests/test_godot_android_mesh_card.py` green at each step (update pinned
  assertions alongside each move). StatusHud (step 1) is done — see above.
- [ ] **M4 — TargetSource strategy interface**: unify on-device ncnn, remote
  proxy_targets WS, and fixture replay behind one source interface; promote
  the payload contract doc into shared test vectors used by both the Python
  and GDScript bbox math.
- [ ] **M5 — Per-subsystem docs** following `docs/smartxr_options.md` style.

## Verification

```powershell
# Full suite (122 tests)
python -m unittest (Get-ChildItem tests\test_*.py | ForEach-Object { "tests/$($_.Name)" })

# Schema gate
python tools\validate_proxy_targets_payload_schema.py --input godot-android\fixtures\proxy_targets_sample.json --input godot-android\fixtures\vst_proxy_targets_sample.json

# Godot runtime probes (headless, no-project mode)
powershell -File tools\run_godot_smartxr_options_probe.ps1
powershell -File tools\run_godot_status_hud_probe.ps1
powershell -File tools\run_godot_script_only_websocket_probe.ps1
# consumer-only needs a publisher on :8766 first (fake_proxy_targets_publisher.py)
powershell -File tools\run_godot_proxy_targets_consumer_only.ps1
```
