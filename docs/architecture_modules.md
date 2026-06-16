# SmartXR Module Architecture and Interface Contracts (baseline)

Status: review baseline for the architecture re-design tracked in YAN-96.
Owner: Orion-TL (tech lead). This document is the shared contract baseline; it is
intentionally implementation-light. Once a contract here is "frozen" (see section 5)
it becomes the authority that both sides of a seam build against.

## 1. Goal

Split SmartXR into independently-developable modules connected by **frozen,
versioned interface contracts**. With the seam contracts frozen, each module is
developed and verified against the contract (and fakes), not against the other
modules' code. Integration then happens against contracts, and only the modules
that genuinely touch hardware require a real-device gate.

## 2. Layered model

Single-direction dependency. Lower layers do not know upper layers exist.

```
[ Android / native plugins ]      <- device-only final gate
[ OpenXR / GXR ]                  <- isolated behind xr_bootstrap + extension toggle
[ Godot presentation: Scene/Card ]<- apps/godot_mr pattern, script-only probes
[ Business / capability bus ]     <- smartxr/ (pure Python, fully unit-tested)
[ Assistant: ToolRegistry/dispatcher/session ] <- function-call, hot-pluggable tools
```

## 3. Modules

| # | Module | Deliverable | Consumes | Produces | Maps to | Device-gated? |
|---|--------|-------------|----------|----------|---------|---------------|
| 1 | human tracking | detection + tracking producer: per target `{id, 3D bbox (8 vertices), 3D landmark, confidence, ts}` | camera/VST frames | C1 (tracking-raw) | `godot-android/ncnn/yolov8n` (2D), `smartxr/frames.py` | no (contract verifiable headless; model accuracy needs eval data) |
| 2 | godot card | scene + card subsystem: attach to dynamic/static targets, appear/expand/contract/disappear lifecycle | C2 (proxy_targets), C3 (card-lifecycle) | card status snapshot | `card_attachment.gd`, `card_view.gd`, `apps/godot_mr` | no |
| 3 | MR integration | publisher-side bbox->head/world conversion + VST alignment + display wiring | C1, calibration | C2 (proxy_targets) | `vst_capture.gd`, `smartxr/geometry.py`, bbox-math fixture | **yes** (alignment correctness) |
| 4 | voice | provider-agnostic `VoiceSession`, backends: Gemini Live + Qwen Omni Realtime | audio, tool responses | C4 (ToolCall) | `SmartMRAssistant/assistant/session.py` | no |
| 5 | agent assistant | real capability tools + dispatcher, real-time tool invocation | C4 | C5 (tool schema), C6 (assistant_card) | `assistant/tools.py`, `assistant/dispatcher.py`, `assistant/card_payload.py` | no |
| 6 | Android | APK build/sign/install pipeline + on-device smoke (deployment axis, not a peer feature module) | runtime contract (GXR toggle, export presets, native staging, OpenXR runtime) | device build of 1/2/3 | `tools/export_android.ps1`, `xr_bootstrap.gd`, YAN-102 | **yes** |

Note: module 6 is a **cross-cutting deployment / integration-gate axis**, not a
sibling feature module. Modules 1/2/3 each reach their Windows/script-only bar
first, then 6 packages them to APK and runs the on-device smoke.

## 4. Interface contracts (seams)

| ID | Seam | Status | Summary |
|----|------|--------|---------|
| C1 | tracking-raw (1 -> 3) | **new** | per detection `{id, bbox_3d (8 vertices, or center+extent+rotation), landmark{rule, point}, confidence, timestamp_ms, source_frame{coordinate_space, units, depth_source}, pose_quality}`. Evolution of the `smartxr/frames.py` source payload. |
| C2 | proxy_targets v1 (3 -> 2) | **frozen** | `{type, schema_version, sequence, targets[{target_id, source, state, confidence, timestamp_ms, transform{position, rotation_xyzw, scale}}], cards[]}`. Raw bbox/detection must NOT reach this layer. See `proxy_targets_payload_contract.md`. |
| C3 | card-lifecycle ((3/5) -> 2) | **new** | card commands + state machine: `attach`/`detach` plus `appear`/`expand`/`contract`/`disappear` (`card_state` enum + transitions), offset_rule, animation durations. |
| C4 | ToolCall (4 -> 5) | **frozen** | `{id, name, args, scheduling}`, provider-agnostic. See `assistant/dispatcher.py`. |
| C5 | tool schema (5 -> capability) | **frozen** | per-tool input/output schema via `ToolRegistry.export_schemas()`. |
| C6 | assistant_card v1 (5 -> display) | **frozen** | `{type, schema_version, card_id, target_id, assistant_state, response_text, tool_summary, person, issue}`. See `apps/godot_mr`. |

4 of 6 seams are already frozen and schema-gated (C2/C4/C5/C6). Only **C1** and
**C3** remain to be defined to the same bar; that is "Step 0".

### Landmark (C1 detail)

The authoritative base is the 8 vertices of the 3D bbox. `landmark` is a derived
point carrying a `rule` (e.g. `centroid`, `front_top_center`, `bottom_center`)
computed from the 8 vertices. Choosing a different landmark later changes the
`rule` value, not the contract shape.

## 5. What "frozen" means

A contract is frozen when all five hold:

1. A versioned schema file (`schema_version` + machine-readable JSON Schema) is checked in.
2. At least one valid fixture and a validator script are in the schema gate (CI fails on a violating payload).
3. A fake producer and a fake consumer exist, each speaking only the schema (neither depends on the other side's code).
4. A semantics doc exists: not only field names but coordinate frame, units, and the meaning of each field.
5. A change policy: after freezing, only additive field changes are allowed; any shape change requires an explicit `schema_version++`. Silent field reshaping is forbidden.

Frozen does not mean final. It means both sides can build in parallel and CI
prevents silent drift; changing a contract becomes an explicit, gated, versioned event.
`proxy_targets` (C2) is the living example that meets all five.

## 6. Verification ladder

Every deliverable declares the highest rung it must pass.

- **L0 contract**: schema validator in the schema gate (CI red/green).
- **L1 unit**: Python unittest / GDScript script-only probe — no engine, no device.
- **L2 fake end-to-end**: fake producer -> real consumer over WebSocket, headless (the existing `run_*_probe` + fake-publisher pattern).
- **L3 device smoke**: real device. Only modules 3 (alignment) and 6 (deployment) require L3.

## 7. Per-module deliverable / verification / data needs

| Module | Key deliverables (one small PR per step) | Closed-loop verification (highest rung) | Data needs |
|--------|------------------------------------------|------------------------------------------|------------|
| 1 tracking | C1 producer: yolov8n 2D detection (present) -> 8-vertex 3D bbox + landmark | L0 C1 schema + L1 projection/derivation math unit tests + L2 recorded-replay publisher -> consumer | large: depth source (#1), recorded footage / labels (#3) |
| 2 godot card | new `card_lifecycle.gd` state machine + attach (dynamic/static) | L1 script-only probe locking each transition + L2 fake proxy_targets -> card | none external (optional card visual assets) |
| 3 MR integration | C1 -> C2 conversion + VST alignment + calibration ownership + display wiring | L0/L1 bbox-math fixture dual-lock + L2 fake -> consumer + L3 device alignment smoke | large: calibration (#2), known-position footage (#3) |
| 4 voice | provider-agnostic `VoiceSession` (Gemini Live + Qwen Omni Realtime) | L1 both providers mock-emit identical C4 + L2 recorded-audio replay | voice API credentials (#4) |
| 5 assistant | real capability tools (card ops / queries) + dispatcher | L1 contract tests + `SimulatedVoiceSession` + L2 ToolCall -> capability -> assistant_card | optional real Jira/identity source (#5) |
| 6 Android | APK build/sign/install pipeline (YAN-102) + on-device smoke | L3 device | device + signing keystore (#6) |

## 8. Data needs (consolidated, prioritized)

1. **[blocks 1+3, highest] 3D depth source direction.** Current pipeline is projected-2D single anchor (`pose_quality: "projected_2d"` in `smartxr/frames.py`). A true 8-vertex 3D bbox needs real depth. Options: (a) stereo VST triangulation; (b) monocular depth / 3D-pose model; (c) external HumanTrackor (Antman) if it already emits 3D. This decision shapes module 1.
2. **[blocks 3] Headset calibration**: camera intrinsics + `right_eye_to_head` extrinsic (device-specific; can be captured on device).
3. **[1/3 verification] Footage with people**: calibrated (ideally stereo) VST sequences; clips with people at known distance/position enable quantitative alignment error; optional 3D bbox / id labels enable quantitative tracking metrics.
4. **[blocks 4] Voice API credentials**: Gemini Live + Qwen Realtime keys (secrets — never in repo/metadata; via env / custom_env).
5. **[5 optional] Real Jira / identity source**: endpoint + credentials; without it, use fixtures (non-blocking).
6. **[6] Device + signing keystore**: real-device adb access; a keystore if non-debug builds are needed.

## 9. Open decisions

- **D1 — 3D depth source** (data need #1): blocks the final shape of modules 1 and 3.
- **Voice model ids**: kept as `VoiceSession` config (env/config), not hard-coded. Confirm the current Gemini Live / Qwen Omni Realtime model strings at module-4 kickoff; changing them does not change any contract.
- **Landmark rule**: configurable `rule` over the 8 vertices; default selectable later without a contract change.

## 10. Parallelization plan

- **Step 0 (unlocks parallelism, highest priority, no data dependency)**: freeze C1 and C3 to the section-5 bar (schema + fake producer/consumer + validator in gate + semantics doc). C2/C4/C5/C6 are already frozen.
- **Track A (device-free, start immediately)**: modules 4 + 5, fully headless.
- **Track B (against fakes)**: module 1 (producer against C1), module 2 (card lifecycle against C2/C3).
- **Track C (convergence)**: module 3 alignment + VST display after C1/C2 are frozen; device-gated.
- **Gate axis**: module 6 packages 1/2/3 to APK and runs on-device smoke (continues YAN-102).
