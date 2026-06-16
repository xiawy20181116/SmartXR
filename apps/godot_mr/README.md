# apps/godot_mr — RETIRED (moved into the godot-android runtime)

> **Status: retired.** This folder is a pointer only. Per the D2 decision
> (`docs/architecture_modules.md` section 16) there is a **single Godot
> runtime** — `godot-android` — and the assistant-card scripts/probes that used
> to live here have been relocated into that runtime tree (Phase B). Do **not**
> add new code under `apps/godot_mr/`.

## Where the code went

| Old path (`apps/godot_mr/...`)                       | New home                                                             |
| ---------------------------------------------------- | ------------------------------------------------------------------- |
| `scripts/assistant_card_state.gd`                    | `godot-android/scripts/assistant/assistant_card_state.gd`           |
| `scripts/assistant_card_view.gd`                     | `godot-android/scripts/assistant/assistant_card_view.gd`            |
| `scripts/assistant_updates_receiver.gd`              | `godot-android/scripts/assistant/assistant_updates_receiver.gd`     |
| `tests/script_only_assistant_card_probe.gd`          | `godot-android/tests/script_only_assistant_card_probe.gd`           |
| `tests/script_only_assistant_updates_probe.gd`       | `godot-android/tests/script_only_assistant_updates_probe.gd`        |

The supporting Python/PowerShell pieces did **not** move and keep their paths:

- `SmartMRAssistant/assistant/card_payload.py` — the `assistant_card` (C6)
  payload contract + summarizer.
- `SmartMRAssistant/assistant/demo.py` — the M-star demo payload builder + CLI.
- `tools/fake_assistant_updates_publisher.py`, `tools/smartmr_mstar_demo_publisher.py`
  — the fake WebSocket publishers.
- `tools/run_godot_mr_assistant_card_probe.ps1`,
  `tools/run_godot_mr_assistant_updates_probe.ps1`,
  `tools/run_smartmr_mstar_demo.ps1` — the probe runners (now pointing at the
  relocated scripts).

## Why

The assistant card is module 2 (godot card) and follows the module-2 standard
**State / View / Receiver** pattern (`AssistantCardState` / `AssistantCardView`
/ `AssistantUpdatesReceiver`). `apps/godot_mr` was never a second Godot project
(no `project.godot`); it was three scripts plus two script-only probes already
reusing `godot-android`'s `WSTransport` by injection. Phase B moves them into
the device runtime so module 2 has one home, one card pattern. The two probes
stay as regression anchors (see `docs/gdscript_probes_ci.md`).

## Run paths

Unchanged — run the same PowerShell runners from the repository root:

```powershell
powershell -File tools\run_godot_mr_assistant_card_probe.ps1
powershell -File tools\run_godot_mr_assistant_updates_probe.ps1
powershell -File tools\run_smartmr_mstar_demo.ps1
python -m unittest discover tests
```

For the full contract, the run ladder, and the headset/manual path, see
`docs/architecture_modules.md` (sections 4 and 16) and the C6 entry in the seam
table.
