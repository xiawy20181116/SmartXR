# smartxr — shared Python library

Layered package extracted from the former standalone `tools/*.py` scripts
(M2 of the YAN-73 encapsulation plan). Dependencies point strictly downward:

```
smartxr/cli         thin argparse entry points (wrapped by tools/*.py)
   │
smartxr/publisher   proxy_targets builders, source normalization, replay
   │
smartxr/frames      tracker frame -> source payload normalization
   │
smartxr/schema      canonical message model + validation (the payload contract in code)
smartxr/geometry    pure bbox -> camera -> head math
smartxr/transport   WebSocket handshake/frames/accept-loop (single copy)
```

The `tools/*.py` files remain as compatibility wrappers so existing runners,
PowerShell scripts, tests, and docs keep working unchanged:

- `tools/fake_proxy_targets_publisher.py` → `smartxr.cli.fake_publisher`
- `tools/vst_proxy_targets_publisher.py` → `smartxr.cli.vst_publisher`
- `tools/validate_proxy_targets_payload_schema.py` → `smartxr.cli.validate_payload`
- `tools/capture_vst_target_sample_session.py` keeps its capture logic but
  imports `normalize_frame` from `smartxr.frames`
- `tools/antman_vst_proxy_targets_live_publisher.py` keeps its live-source
  loop but uses `smartxr.transport` / `smartxr.publisher` instead of
  importing private functions from sibling tools
- `windows_server/ws_control.py` reuses the accept-key and frame encoder from
  `smartxr.transport`

Contract reference: `docs/proxy_targets_payload_contract.md`. The schema gate:

```powershell
python tools\validate_proxy_targets_payload_schema.py --input godot-android\fixtures\proxy_targets_sample.json
```
