# Notes — M1+M2 change log (YAN-73)

## Files added

- `smartxr/__init__.py`, `smartxr/schema.py`, `smartxr/transport.py`,
  `smartxr/geometry.py`, `smartxr/frames.py`, `smartxr/publisher.py`,
  `smartxr/cli/{__init__,fake_publisher,vst_publisher,validate_payload}.py`,
  `smartxr/README.md` — the shared Python package (M2).
- `pyproject.toml` — minimal packaging metadata.
- `godot-android/scripts/smartxr_options.gd` — runtime options class (M1).
- `docs/smartxr_options.md` — options documentation.
- `tests/test_godot_smartxr_options.py` — 4 new tests.
- `TASKS.md`, `DECISIONS.md`, `HANDOFF.md`, `Notes.md` — project bookkeeping.

## Files modified

- `tools/fake_proxy_targets_publisher.py` — now a wrapper re-exporting from
  `smartxr` (same public names, same CLI).
- `tools/vst_proxy_targets_publisher.py` — same.
- `tools/validate_proxy_targets_payload_schema.py` — same.
- `tools/capture_vst_target_sample_session.py` — `normalize_frame` and its
  helpers moved to `smartxr/frames.py`; capture/session logic unchanged.
- `tools/antman_vst_proxy_targets_live_publisher.py` — imports switched from
  sibling-tool private functions to `smartxr.transport` /
  `smartxr.publisher` / `smartxr.frames`; serve loop unchanged.
- `windows_server/ws_control.py` — `make_websocket_accept_key` and
  `encode_server_text_frame` now come from `smartxr.transport`; local copies
  removed.
- `godot-android/scripts/AndroidMovingCard.gd` — added `_options`
  (SmartXROptions); `_connect_ws()` uses `_control_ws_url()`;
  `_proxy_targets_ws_url()` and the WS-enable gates route through options.
- `tests/validate_project.ps1` — registers the new options test file.
- `tests/test_fake_proxy_targets_publisher.py` — banner assertion repointed
  to `smartxr/cli/fake_publisher.py`.
- `tests/test_godot_android_mesh_card.py` — publisher-source and URL
  assertions repointed to the package / options delegation.

## Verification run

- `python -m unittest tests/test_*.py` → 118 tests, OK.
- Schema gate on both fixtures → ok.
- `vst_proxy_targets_publisher.py --print-once` against the VST fixture →
  canonical message printed.
