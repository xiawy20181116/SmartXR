# TargetSource and proxy_targets subsystem (Godot)

`godot-android/scripts/target_source.gd` (`TargetSource`) contains the
duck-typed target-source boundary for VST-derived targets and remote
proxy_targets messages.

The script is dependency-free. It owns target-source state and parsing, while
`AndroidMovingCard.gd` keeps card-facing side effects: registry wiring, card
attachment, bbox/head math, diagnostics counters, and status snapshot assembly.

## Shared constants

| Constant | Value | Meaning |
|---|---|---|
| `TRACKABLE_SOURCE_VST` | `vst` | Target originated from the local VST path. |
| `TRACKABLE_SOURCE_EXTERNAL` | `external` | Target originated from an external source. |
| `TRACKABLE_STATE_TRACKED` | `tracked` | Fresh tracked pose. |
| `TRACKABLE_STATE_PREDICTED` | `predicted` | Pose projected forward after recent tracking. |
| `TRACKABLE_STATE_STALE` | `stale` | Pose is too old for prediction but not fully lost. |
| `TRACKABLE_STATE_LOST` | `lost` | Target is unavailable. |

## VST target path

The VST path is split into a record, an adapter, and a source wrapper.

| Type / API | Meaning |
|---|---|
| `TrackableTarget` | Record containing id, source, state, transform, confidence, velocity, and timestamps. |
| `VSTTargetAdapter.update_target(...)` | Applies confidence gating, smoothing, velocity update, and proxy transform application. |
| `VSTTargetAdapter.advance(now_ms)` | Advances tracked -> predicted -> stale -> lost over time. |
| `VSTTargetSource.set_on_target_updated(callable)` | Notifies the card when a VST target update is accepted. |
| `VSTTargetSource.set_on_target_lost(callable)` | Notifies the card when the target transitions to lost. |
| `VSTTargetSource.update_target(...)` | Public update entry point used by the card. |
| `VSTTargetSource.advance(now_ms)` | Public time-advance entry point used by the card. |
| `VSTTargetSource.target_state()` | Returns the current target state string. |
| `VSTTargetSource.target()` | Returns the current `TrackableTarget` record. |

The card still owns bbox-to-head conversion and proxy node registration. The
source receives already-computed transforms.

## proxy_targets path

`ProxyTargetsTargetSource` routes remote WebSocket packets and fixture replay
through the same target-source boundary.

| API | Caller | Meaning |
|---|---|---|
| `ProxyTargetsTargetSource.new(card_adapter)` | Card setup | Wraps an injected adapter that applies proxy_targets messages to card-owned state. |
| `set_on_message_parsed(callable)` | Card setup / probes | Notifies the caller after JSON parsing succeeds. |
| `apply_proxy_targets_json(payload)` | WebSocket packet path / fixture replay | Parses JSON text and delegates to `apply_proxy_targets_message`. |
| `apply_proxy_targets_message(message)` | Tests / direct replay | Delegates a parsed message Dictionary to the injected card adapter. |
| `last_error()` | Status/probes | Returns the last coarse error string. |

The injected adapter is expected to provide
`apply_proxy_targets_message(message: Dictionary) -> bool`. The source does
not inspect card nodes, register targets, attach cards, or update status
counters directly.

## Error strings

| Error | Meaning |
|---|---|
| `json_invalid` | `apply_proxy_targets_json` could not parse a Dictionary payload. |
| `adapter_null` | No card adapter was supplied. |
| `apply_failed` | The adapter rejected the parsed message. |

An empty error string means the latest apply succeeded.

## Runtime data flow

Live proxy_targets path:

1. `WSTransport` receives packet text from the proxy_targets WebSocket.
2. The card passes packet text to `ProxyTargetsTargetSource.apply_proxy_targets_json`.
3. The source parses JSON and reports the parsed message callback.
4. The source delegates the Dictionary to the injected card adapter.
5. The card adapter applies card-owned behavior: target registration,
   attachment updates, diagnostics counters, and status snapshot fields.

Fixture replay uses the same source entry point, which keeps test and live
payload behavior aligned.

## Runtime verification

```powershell
powershell -File tools\run_godot_target_source_probe.ps1
```

The probe runs `godot-android/tests/script_only_target_source_probe.gd` in
no-project mode. It verifies VST state transitions, callback behavior,
proxy_targets JSON parsing, fixture/direct-message apply, adapter delegation,
and error reporting.

Python coverage:

```powershell
python -m unittest tests.test_godot_target_source
```

End-to-end proxy_targets harnesses:

```powershell
# Publisher started by the harness.
powershell -File tools\run_godot_script_only_websocket_probe.ps1

# Or run a publisher yourself, then run the consumer-only harness.
python tools\fake_proxy_targets_publisher.py --host 127.0.0.1 --port 8766 --hz 20 --mode moving
powershell -File tools\run_godot_proxy_targets_consumer_only.ps1
```

For Windows PCMR manual validation against a local publisher, the current
preflight convention is to run the fake publisher on `127.0.0.1:8776` and pass
`-ValidateProxyTargets -ProxyTargetsWsUrl ws://127.0.0.1:8776/proxy_targets`
to `tools\run_windows_pcmr.ps1`.

## Extending TargetSource

1. Keep target-source scripts dependency-free and callable-driven.
2. Keep card-facing side effects in `AndroidMovingCard.gd` or an injected
   adapter.
3. Do not change the proxy_targets payload schema from this layer; update
   `docs/proxy_targets_payload_contract.md` and schema tests if the schema
   changes elsewhere.
4. Keep bbox-to-head math locked to
   `godot-android/fixtures/bbox_math_test_vectors.json`.
5. Keep probe-visible code free of self-references to `TargetSource` return
   types, because no-project mode does not register global classes.
