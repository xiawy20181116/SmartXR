# Tracked-target card State/View/Receiver trio (D2 Phase C)

Module-2 standard pattern (architecture_modules.md §16): **State / View /
Receiver**. Phase B landed the trio for the *assistant* card
(`godot-android/scripts/assistant/`). Phase C (this doc, YAN-112) re-expresses
the *tracked-target* (proxy_targets) card on the same pattern and routes the
`AndroidMovingCard.gd` host through it.

The trio is intentionally a re-grouping of helpers the card already had
(`status_snapshot_composer` / `proxy_targets_status_fragment`, `card_view` /
`passthrough_overlay_presenter`, `proxy_targets_consumer` +
`proxy_targets_card_adapter` + `ws_transport`), not a rewrite of their logic.
Runtime behaviour of those helpers is unchanged; only ownership moved into three
named seams.

## The three seams

All three are `RefCounted`, dependency-free, and **loadable in no-project mode**
(no `res://` preloads, no env reads, no tree access, no self-`class_name`
reference). Dependencies are *injected* by the host, which owns the `res://`
preloads — exactly like `assistant_updates_receiver.gd`.

| Seam | File | Role | Composes |
|------|------|------|----------|
| **CardState** | `scripts/tracked_target_card_state.gd` | pure data: validated diagnostic snapshot + `live`/`apply` counters + envelope validation | injected `ProxyTargetsStatusFragment` |
| **CardView** | `scripts/tracked_target_card_view.gd` | presentation only | injected `card_view` + `passthrough_overlay_presenter` |
| **CardReceiver** | `scripts/tracked_target_card_receiver.gd` | boundary glue: live-payload apply path, records into State, emits `last_command` | injected proxy_targets `consumer`/`adapter`/`target_source` + a `WSTransport` |

### CardState

- `validate_envelope(message)` owns the proxy_targets envelope check (type,
  `targets`/`cards` array shape). Geometry validation stays downstream in the
  consumer.
- Owns the two counters the card reports: `record_live_applied()` /
  `record_apply()`.
- `status_values(runtime_values)` injects `live` + `card_apply_count` from its
  own counters and delegates the ordered layout to the fragment, so the host no
  longer threads those through `runtime_values`.

### CardView

- Forwards `build_card` / `build_xr_render_probe` / `viewport` / `anchor` /
  `card_mesh` to `card_view.gd`.
- Forwards `overlay_enabled_from_env` / `build_overlay_layer` /
  `update_overlay_layer` / `overlay_layer_alpha_blend` /
  `overlay_layer_position` / `overlay_status_values` to the passthrough
  presenter.
- All getters are null-safe so the seam is testable unbound.

### CardReceiver

- `apply_live_payload(payload)` is the path lifted verbatim from the card's old
  `_apply_proxy_targets_live_payload`: sanitize → preview → apply via
  target_source → record into State → emit one of `proxy_live` /
  `proxy_live_invalid` / `proxy_live_failed` (or set `adapter_null` with no
  command). The connect-error path emits `proxy_ws_connect_err_<N>`.
- `last_command` ownership stays on the host: the Receiver reports strings via an
  injected `set_on_command` callback (ADR-4). The StatusHud sanitizer is
  injected via `set_packet_sanitizer` so the seam needs no `status_hud` preload.
- The host still builds the consumer/adapter/target_source scene nodes (that
  needs `validation_scene_builder` + the tree + `res://` factories) and injects
  them via `set_proxy_pipeline`, which also wires `on_message_parsed` back into
  the seam.

## What stays in the host

`AndroidMovingCard.gd` remains the host and **owns the XR lifecycle and the
native VST/ncnn pipeline** (xr_bootstrap, vst_capture, vst_debug_ui), the
control WS, command dispatcher, card_attachment, target_registry, status_hud,
and the 3DoF/bbox anchor math. This matches the §16 guardrail: *do not port
native VST/XR toward the card layer*. The host news the underlying card helpers
(it owns the preloads) and binds them into the trio in `_setup_card_trio()`,
then delegates the card/presentation seams through the trio.

## Verification (script-only, no device)

One probe per seam, headless no-project Godot 4.6.2, in the `gdscript-probes`
CI list:

```powershell
powershell -File tools/run_godot_tracked_target_card_state_probe.ps1
powershell -File tools/run_godot_tracked_target_card_view_probe.ps1
powershell -File tools/run_godot_tracked_target_card_receiver_probe.ps1
```

The pre-existing `card_view` / `card_attachment` / `status_snapshot_composer` /
`passthrough_overlay_presenter` / `proxy_targets_status_fragment` probes stay
green as the regression net for the extracted helpers.

The host itself cannot be probed in no-project mode (it has `res://` preloads)
and full-project headless startup hangs on the GXR/OpenXR path (see
`docs/gdscript_probes_ci.md`). It is compile-checked by loading it under
`--path godot-android` with `openxr/enabled` temporarily off, and otherwise
needs on-device/Godot verification — the deferred Phase C risk noted in §16.
