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

`PROXY_TARGETS_WS_URL` keeps its historical environment-variable name (it
predates this class and is referenced by existing harnesses); new settings use
the `SMARTXR_` prefix.

Boolean environment values accept `1/true/yes/on` (case-insensitive); any
other non-empty value is false.

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

## Adding a new setting

1. Add an `ENV_*` const and a typed accessor to `smartxr_options.gd`.
2. Keep the default as a script const at the call site and pass it into the
   accessor (`_options.my_setting(MY_CONST)`).
3. Document the key in the table above and pin it in
   `tests/test_godot_smartxr_options.py`.

This is M1 of the encapsulation plan (YAN-73); later milestones move more of
`AndroidMovingCard.gd`'s constants behind this class as subsystems are
extracted.
