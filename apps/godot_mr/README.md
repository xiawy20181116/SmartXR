# Godot MR Assistant (apps/godot_mr)

`apps/godot_mr` is the headset-facing Godot project root for the SmartMR assistant
(issue YAN-95, S3). It hosts the assistant-card UI subsystem that shows the voice
assistant state and tool-query results, and receives card refreshes pushed from
the Python agent side over WebSocket.

It is deliberately a separate consumer/view layer. It does **not** extend the older
`godot-android/scripts/AndroidMovingCard.gd` display stack; instead it reuses the
already-extracted transport boundary from `godot-android` and keeps assistant state
and rendering in small, single-responsibility scripts.

## What is implemented

- Phase 1 (Python contract): `SmartMRAssistant/assistant/card_payload.py` defines the
  `assistant_card` payload, validation, the payload builder, and a tool-result
  summarizer.
- Phase 3 (Godot UI): `scripts/assistant_card_state.gd` + `scripts/assistant_card_view.gd`
  parse/own assistant-card state and render it to a `Label3D`.
- Phase 4 (WebSocket receive): `scripts/assistant_updates_receiver.gd` wires the
  injected `WSTransport` to `AssistantCardState`/`AssistantCardView`.
- Phase 5 (M-star demo): `SmartMRAssistant/assistant/demo.py` plus the publisher and
  runner under `tools/` drive the end-to-end simulated path.

## Directory layout

```
apps/godot_mr/
  scripts/
    assistant_card_state.gd        # parse/validate/own assistant_card snapshot
    assistant_card_view.gd         # render snapshot to a Label3D
    assistant_updates_receiver.gd  # WSTransport -> state -> view boundary
  tests/
    script_only_assistant_card_probe.gd      # Phase 3 headless probe
    script_only_assistant_updates_probe.gd   # Phase 4 / Phase 5 live WS probe
```

Supporting Python/PowerShell pieces live outside this folder:

```
SmartMRAssistant/assistant/card_payload.py   # payload contract + summarizer
SmartMRAssistant/assistant/demo.py           # M-star demo payload builder + CLI
tools/fake_assistant_updates_publisher.py    # Phase 4 fake WS publisher
tools/smartmr_mstar_demo_publisher.py        # Phase 5 demo WS publisher
tools/run_godot_mr_assistant_card_probe.ps1
tools/run_godot_mr_assistant_updates_probe.ps1
tools/run_smartmr_mstar_demo.ps1
```

## assistant_card payload contract

The canonical message is `type=assistant_card`, `schema_version=1`. The Python builder
(`build_assistant_card_payload`) and the Godot parser (`AssistantCardState`) agree on
the same shape:

| field            | type            | notes                                              |
| ---------------- | --------------- | -------------------------------------------------- |
| `type`           | string          | must be `assistant_card`                           |
| `schema_version` | int             | must be `1`                                        |
| `card_id`        | non-empty str   | which card to refresh                              |
| `target_id`      | non-empty str   | bound target / person ref                          |
| `assistant_state`| non-empty str   | one of idle/listening/thinking/responding/complete/error |
| `response_text`  | string          | spoken/answer text shown on the card               |
| `tool_summary`   | object          | includes `status_line`, `person_label`, `issue_label`, ... |
| `person`         | object or null  | identity_lookup result, optional                   |
| `issue`          | object or null  | jira_lookup result, optional                       |

Transport stays text-only: the WebSocket layer carries the JSON string, and all
parsing/validation stays in `AssistantCardState` (mirrored by the Python validator).

## Run paths

All commands run from the repository root. The Godot probes default to
`E:\xia\Godot_v4.6.2-stable_win64.exe\...`; pass `-GodotExe <path>` to override.

### 1. Headless assistant-card probe (no device, no network) — Phase 3

Validates that a valid payload updates the snapshot, an invalid payload is rejected,
and the view renders the response text and tool summary. Runs Godot in `--headless`
script-only mode (no full project needed).

```powershell
powershell -File tools\run_godot_mr_assistant_card_probe.ps1
```

Expected tail: `assistant card probe PASSED`, and a status JSON under
`.tmp\assistant_card_probe\`.

### 2. WebSocket assistant_updates probe (no device) — Phase 4

Starts the fake publisher on `ws://127.0.0.1:8774/assistant_updates`, then runs the
Godot live probe to confirm subscribe -> packet receive -> snapshot update ->
`Label3D` refresh.

```powershell
powershell -File tools\run_godot_mr_assistant_updates_probe.ps1
```

Expected tail: `assistant_updates probe PASSED`, status JSON under
`.tmp\assistant_updates_probe\`.

### 3. M-star demo end-to-end (no device) — Phase 5

The shortest end-to-end loop: simulated perception/person -> `identity_lookup` ->
`jira_lookup` -> `summarize_tool_results` -> `build_assistant_card_payload` ->
`/assistant_updates` WebSocket -> Godot card update. The runner starts
`tools\smartmr_mstar_demo_publisher.py` on port 8775 and reuses the Phase 4 live
probe with demo-specific expected text.

```powershell
powershell -File tools\run_smartmr_mstar_demo.ps1
```

Expected tail: `SmartMR M-star demo PASSED`, status JSON under
`.tmp\smartmr_mstar_demo\`. The demo fixture is Ada Lovelace / XR-42, producing
`response_text = "Ada Lovelace is working on XR-42: Prepare MR assistant demo."`.

To inspect just the generated payload (no Godot, no WebSocket):

```powershell
python -m SmartMRAssistant.assistant.demo --pretty
```

### 4. With a headset / full Godot project (manual)

The probes above are headless and device-free on purpose. On real hardware:

1. Open `apps/godot_mr` (and the migrated `godot-android` transport scripts) in the
   Godot 4.6 editor and attach `AssistantCardState`/`AssistantCardView` to a card node,
   driven by `AssistantUpdatesReceiver` with a real `WSTransport`.
2. Point the receiver at the agent-side `/assistant_updates` WebSocket
   (`smartmr_mstar_demo_publisher.py` or the real agent push endpoint).
3. Ask "他手上有什么任务"; the voice side answers and the head-mounted card refreshes
   with the same payload the headless probe asserts.

Hardware, microphone, and live provider credentials are only needed for this manual
path; CI and local verification use the headless probes.

## Tests and verification

```powershell
python -m unittest discover tests
powershell -File tools\run_godot_mr_assistant_card_probe.ps1
powershell -File tools\run_godot_mr_assistant_updates_probe.ps1
powershell -File tools\run_smartmr_mstar_demo.ps1
```

Python-only coverage for the contract, receiver wiring, and demo lives in
`tests/test_smartmr_assistant_card_payload.py`, `tests/test_godot_mr_assistant_card.py`,
`tests/test_godot_mr_assistant_updates.py`, and `tests/test_smartmr_mstar_demo.py`.

## Relationship to godot-android (migration source)

`godot-android` remains the device-side baseline and the source of the proven
transport/target/card/status boundaries. This project reuses them rather than copying:

- `godot-android/scripts/ws_transport.gd` (`WSTransport`) is injected into
  `AssistantUpdatesReceiver` as the text-only transport; the probe runners pass it via
  `SMARTXR_WS_TRANSPORT_SCRIPT`.
- Target/card placement stays on the existing `proxy_targets` path in `godot-android`;
  assistant payloads only update content/state for an already-bound card.
- The script-only headless probe pattern and PowerShell runner conventions are carried
  over from `godot-android`'s existing probes.

New assistant behavior (state, view, receiver, payload contract, demo) is added here as
a separate layer so the old `AndroidMovingCard.gd` stack is not extended further.
