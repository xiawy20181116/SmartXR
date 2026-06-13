# StatusHud subsystem (Godot)

`godot-android/scripts/status_hud.gd` (`StatusHud`) owns runtime status
presentation: the floating `Label3D` text and the two `user://` JSON files
used by proxy_targets and passthrough-overlay harnesses.

The card remains the owner of runtime state. It builds a snapshot Dictionary
each frame, then passes that snapshot into StatusHud for formatting and file
output.

## Boundary

StatusHud owns:

- Creating and updating the `Label3D` status label.
- Formatting XR, proxy_targets, and VST status lines.
- Escaping and truncating packet previews for safe label text.
- Writing `user://proxy_targets_live_status.json`.
- Writing `user://passthrough_overlay_status.json`.

`AndroidMovingCard.gd` still owns:

- WebSocket state, packet parsing, and error strings.
- Target registration, attachments, and card placement.
- XR bootstrap results and passthrough-overlay blend values.
- The shape and semantic meaning of the snapshot Dictionary.

This keeps the ADR-4 seam narrow: StatusHud renders and writes diagnostics,
but it does not make runtime decisions.

## Public surface

| API | Caller | Meaning |
|---|---|---|
| `build_status_label(parent)` | `AndroidMovingCard.gd` | Creates the `Label3D`, attaches it to `parent`, and returns it. |
| `update_status_label(snapshot)` | Card `_process` path | Rebuilds the label text from the latest snapshot. |
| `write_status_files(snapshot, delta)` | Card `_process` path | Periodically writes the proxy_targets and passthrough status JSON files. |
| `sanitize_status_text(value)` | Status formatting and probes | Escapes newlines/tabs and caps long packet previews. |
| `proxy_targets_status_path` | Tests / probes | Optional override for the proxy_targets status output path. |
| `passthrough_overlay_status_path` | Tests / probes | Optional override for the passthrough status output path. |

The default file paths are:

| Constant | Path |
|---|---|
| `PROXY_TARGETS_STATUS_RES` | `user://proxy_targets_live_status.json` |
| `PASSTHROUGH_OVERLAY_STATUS_RES` | `user://passthrough_overlay_status.json` |

Status files are throttled by `STATUS_FILE_WRITE_INTERVAL_SECONDS` (0.25 s).

## Snapshot fields

StatusHud expects a Dictionary assembled by the card. The main groups are:

| Field group | Examples | Used for |
|---|---|---|
| XR | `xr_active`, `xr_interface_found`, `xr_initialize_ok`, `xr_init_error` | Headset/bootstrap status line. |
| Passthrough | `passthrough_overlay_supported`, `passthrough_overlay_requested_blend_mode`, `passthrough_overlay_blend_ok` | Passthrough status file. |
| proxy_targets connection | `ws_connected`, `ws_subscribed`, `ws_url`, `last_command`, `error` | Live stream status line and JSON. |
| proxy_targets packets | `packets`, `parsed`, `live`, `sequence`, `packet_bytes`, `packet_preview`, `message_type` | Consumer diagnostics. |
| proxy_targets targets | `proxy_target_count`, `proxy_target_ids`, `last_proxy_position`, `source_coordinate` | Target-source diagnostics. |
| Card attachment | `attachments`, `card_target_id`, `card_attach_target_id`, `card_resolved_position`, `card_node_position`, `card_apply_count` | Attachment diagnostics. |
| VST | `target_state`, `confidence`, `age_ms`, `position` | VST target status line. |

Unknown keys are ignored. Missing keys render as false, zero, empty text, or
`n/a` depending on the formatter.

## Runtime behavior

`update_status_label()` formats three compact lines:

1. XR bootstrap and passthrough state.
2. proxy_targets WebSocket, packet, target, and attachment state.
3. VST target-source state.

`write_status_files()` writes diagnostics as JSON, not as the visible label
text. Harnesses read the JSON files so assertions do not depend on the
human-facing label layout.

## Runtime verification

```powershell
powershell -File tools\run_godot_status_hud_probe.ps1
```

The probe runs `godot-android/tests/script_only_status_hud_probe.gd` in
no-project mode. It verifies label creation, status-line formatting, text
sanitization, path overrides, throttled writes, and the JSON fields consumed by
the live proxy_targets and passthrough harnesses.

Python coverage:

```powershell
python -m unittest tests.test_godot_status_hud
```

## Extending StatusHud

1. Add new runtime data to the card snapshot first.
2. Keep StatusHud as a renderer/writer only; do not move ownership of runtime
   state into this script.
3. Update the status probe and `tests/test_godot_status_hud.py`.
4. Keep probe-visible code free of self-references to `StatusHud` return
   types, because no-project mode does not register global classes.
