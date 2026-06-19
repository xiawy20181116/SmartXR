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

This module/contract split is the structural realization of three founding product
principles — **capability encapsulation, business-driven invocation, and intelligent
voice control**. Section 17 pins the explicit mapping from each principle to the
layers, contracts, and code that realize it.

## 2. Layered model

Single-direction dependency. Lower layers do not know upper layers exist.

```
[ Android / native plugins ]      <- device-only final gate
[ OpenXR / GXR ]                  <- isolated behind xr_bootstrap + extension toggle
[ Godot presentation: Scene/Card ]<- State/View/Receiver pattern, script-only probes
[ Business / capability bus ]     <- smartxr/ (pure Python, fully unit-tested)
[ Assistant: ToolRegistry/dispatcher/session ] <- function-call, hot-pluggable tools
```

## 3. Modules

| # | Module | Deliverable | Consumes | Produces | Maps to | Device-gated? |
|---|--------|-------------|----------|----------|---------|---------------|
| 1 | human tracking | detection + tracking producer: per target `{id, 3D bbox (8 vertices), 3D landmark, confidence, ts}`; detection backend is pluggable (on-device / PC-offload / hybrid) | camera/VST frames | C1 (tracking-raw) | `godot-android/ncnn/yolov8n` (2D), `smartxr/frames.py` | no (contract verifiable headless; model accuracy needs eval data) |
| 2 | godot card | scene + card subsystem: attach to dynamic/static targets, appear/expand/contract/disappear lifecycle | C2 (proxy_targets), C3 (card-lifecycle) | card status snapshot | `card_attachment.gd`, `card_view.gd`, `card_lifecycle.gd`, `godot-android/scripts/assistant/` | no |
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
| C6 | assistant_card v1 (5 -> display) | **frozen** | `{type, schema_version, card_id, target_id, assistant_state, response_text, tool_summary, person, issue}`. See `godot-android/scripts/assistant/`. |
| C7 | frame-uplink (device -> PC) | **new, optional** | device -> PC frame stream for PC-offload detection. Two layers: `transport` (mjpeg-ws / h264-ws / webrtc) separate from `codec`; raw NV12 is never sent. Every frame carries `frame_id` + `timestamp_ms` (+ width/height, optional pose). Only needed if the PC-offload backend is built; on-device needs no uplink. PC returns detections as C1 over WS. See "Uplink transport". |

Frozen and schema-gated today: C2/C4/C5/C6. **C1** and **C3** are defined in
"Step 0". **C7** is defined only if/when the PC-offload detection backend is built;
it does not block the on-device path.

### Landmark (C1 detail)

The authoritative base is the 8 vertices of the 3D bbox. `landmark` is a derived
point carrying a `rule` (e.g. `centroid`, `front_top_center`, `bottom_center`)
computed from the 8 vertices. Choosing a different landmark later changes the
`rule` value, not the contract shape.

### Track lifecycle and id (C1 detail)

C1 `id` is a track id with a defined lifecycle, so id-stability is testable:

- states: `tentative` (newly seen, unconfirmed) -> `confirmed` (stable across N
  frames) -> `lost` (missed M frames, pose predicted) -> `deleted` (after K lost frames).
- id stability: a `confirmed` track keeps its id across brief occlusion/exit; ids are
  not reused within a session. Re-entry after `deleted` gets a new id
  (cross-session / true re-identification is out of scope for v1).
- C1 carries the current `state` and age; data-grading T1 (enter/leave, 2-person)
  measures id-switch rate against this definition.

Depth is a single **pluggable scalar** input to the 2.5D box builder (the 8
vertices are extruded around the projected anchor using nominal human dimensions).
`smartxr/publisher.py` already treats depth this way (`depth_m` per detection +
`depth_source` tag). The depth source can therefore be swapped without changing
C1's shape; `pose_quality` records the fidelity:

- `fixed_depth` — constant given depth (current).
- `mono_metric` — monocular metric depth estimate (low frame rate; see rate note).
- `stereo` — stereo VST triangulation (arrives with the dual-eye iteration).

Depth rate is decoupled from detection/tracking rate: detection/tracking runs at
full rate while depth may update slowly; the producer holds the last depth per
track between depth updates. Given the high alignment tolerance (card only needs
to sit near the person), holding/smoothing stale depth is acceptable.

### Detection backend topology (C1 producer)

Where detection runs is a deployment-topology choice **behind the C1 boundary**;
the consumer (modules 2/3) never sees it. Module 1 exposes a pluggable detection
backend; all backends emit the same C1. On-device compute is thermally/perf
limited, so the PC-offload option must be preserved from the start.

- **on-device**: capture + detection (ncnn yolov8n) + tracking on the headset.
  Lowest latency, no network, but thermally/perf limited.
- **PC-offload**: headset streams frames over WiFi (C7) to a PC that runs a
  larger/better detector; PC returns detections as C1 over WS. Unlocks heavier
  models (and is the natural home for the `mono_metric` depth / 3D-pose upgrades).
- **hybrid**: PC detects at a low rate; the headset tracks on-device at full rate
  between PC detections — same rate-decoupling pattern as depth above.

Engineering constraints to design for (PC-offload): the uplink must be compressed
(raw 880x660 NV12 at ~40 fps is ~280 Mbps; use jpeg/h264); PC detection runs at a
lower rate with on-device tracking bridging the gap; WiFi loss falls back to the
on-device backend or last-known tracks; results are associated to frames by
`frame_id` + `timestamp_ms` since they arrive late.

For v1 the backend is an interface with the on-device (or replay) backend wired
first; PC-offload is a second backend implementation behind the same interface, so
"preserve the option" means the interface is in place, not that PC-offload must
ship in v1.

### Uplink transport (C7)

The uplink has two layers: **codec** (what the frame is compressed to) and
**transport** (how it is shipped). Raw NV12 is never sent. C7 is transport-agnostic;
every option carries `frame_id` + `timestamp_ms` so late detections associate to the
right frame.

| Option | Transport + codec | Trade-off |
|--------|-------------------|-----------|
| MJPEG over WS | per-frame JPEG over the existing WS | simplest; per-frame `frame_id`/`timestamp` trivial; reuses WS; fine on LAN. **v1 bring-up default.** |
| H.264/H.265 | Android MediaCodec hardware encode -> NAL over WS/UDP, ffmpeg decode on PC | best bandwidth; hardware encode is power/heat friendly; you handle keyframes/sync/loss. |
| WebRTC | hardware encode + congestion control + NACK/FEC + adaptive bitrate | best for lossy / cross-network links; heaviest integration (signaling/ICE, and feeding a custom NV12 camera source into a video track likely needs native libwebrtc — Godot's WebRTC is data-channel oriented). |

Caveat for continuous codecs (H.264/WebRTC): the codec decouples frame identity from
the bitstream, so `frame_id` must be carried out-of-band (RTP timestamp mapping or a
parallel data channel). MJPEG keeps frame identity inline. Lossy compression mildly
degrades detector input but is negligible at sane bitrate.

Recommendation: start with MJPEG-over-WS to bring the path up, then upgrade to H.264
(heat-friendly) or WebRTC after measuring real bandwidth/latency/heat. Do not adopt
the heaviest option before measuring; on a stable LAN, WebRTC's congestion control
adds limited value.

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

Version negotiation: a consumer accepts `schema_version` within its supported range
and ignores unknown additive fields; a producer that bumped a major (shape) version
must not assume an older consumer understands it. For distributed seams (C7 /
PC-offload) the two sides exchange supported `schema_version` at connect and use the
lower common version.

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

1. **[RESOLVED] 3D depth source direction.** Decision: ship a 2.5D approximate box now (high alignment tolerance justifies it), with depth as a pluggable scalar. v1 uses the current fixed depth (`pose_quality: fixed_depth`). Upgrades — monocular metric depth (`mono_metric`, low fps, run asynchronously with per-track last-depth hold) then stereo triangulation (`stereo`, with the dual-eye iteration) — are swapped in behind C1 without a contract change. This no longer blocks module 1 or the issue tree.
2. **[blocks 3] Headset calibration**: camera intrinsics + `right_eye_to_head` extrinsic (device-specific; can be captured on device).
3. **[1/3 verification] Footage with people**: calibrated (ideally stereo) VST sequences; clips with people at known distance/position enable quantitative alignment error; optional 3D bbox / id labels enable quantitative tracking metrics.
4. **[blocks 4] Voice API credentials**: Gemini Live + Qwen Realtime keys (secrets — never in repo/metadata; via env / custom_env).
5. **[5 optional] Real Jira / identity source**: endpoint + credentials; without it, use fixtures (non-blocking).
6. **[6] Device + signing keystore**: real-device adb access; a keystore if non-debug builds are needed.

## 9. Open decisions

- **D1 — 3D depth source** (data need #1): RESOLVED. 2.5D approximate box now (fixed depth), depth as a pluggable scalar; roadmap mono-metric -> stereo behind C1, no contract change. VST is currently monocular; stereo iteration in progress.
- **Voice model ids**: kept as `VoiceSession` config (env/config), not hard-coded. Confirm the current Gemini Live / Qwen Omni Realtime model strings at module-4 kickoff; changing them does not change any contract.
- **Landmark rule**: configurable `rule` over the 8 vertices; default selectable later without a contract change.
- **Latency target**: DECIDED = 150 ms end-to-end camera->card (see section 13).
- **Security posture**: DECIDED = LAN-trusted demo, risks documented (see section 14); harden post-v1.
- **D2 - Godot stack convergence** (`godot-android` vs `apps/godot_mr`): DECIDED = single runtime + adopt the State/View/Receiver pattern. There is no second Godot project (`apps/godot_mr` has no `project.godot`); `godot-android` stays the device host and owns the native VST/XR/ncnn pipeline. See section 16 for the pattern and the Phase A-D operational plan.
- **Module ownership**: proposed mapping pending confirmation (see section 15).

## 10. Parallelization plan

- **Step 0 (unlocks parallelism, highest priority, no data dependency)**: freeze C1 and C3 to the section-5 bar (schema + fake producer/consumer + validator in gate + semantics doc). C2/C4/C5/C6 are already frozen.
- **Track A (device-free, start immediately)**: modules 4 + 5, fully headless.
- **Track B (against fakes)**: module 1 (producer against C1), module 2 (card lifecycle against C2/C3, plus the D2 State/View/Receiver convergence Phase B->C->D, section 16).
- **Track C (convergence)**: module 3 alignment + VST display after C1/C2 are frozen; device-gated.
- **Gate axis**: module 6 packages 1/2/3 to APK and runs on-device smoke (continues YAN-102).

## 11. Coordinate frames, units, and clock base

All seams use these conventions; a payload that does not state otherwise is in head
space, meters, right-handed.

- **Frames**: `vst_right_camera` (raw VST right-eye optical), `head` (OpenXR view),
  `world` (XR reference space). C1 `source_frame.coordinate_space` names the frame;
  C2 transforms are in `world`/`head`. The camera->head conversion is defined in
  `proxy_targets_payload_contract.md` (camera +X right / +Y down / +Z forward;
  default Godot `[x, -y, -z]`; optional `right_eye_to_head` 4x4).
- **Units**: meters and radians; quaternions `[x, y, z, w]`.
- **Clock base**: one monotonic `timestamp_ms` per producer with a documented epoch.
  Across phone<->PC (C7 / PC-offload) the two sides exchange a clock offset at
  handshake so late detections associate to the right capture frame by `frame_id` +
  `timestamp_ms`. (The capture `timeline.json` uses session-relative monotonic ms;
  deltas are authoritative, the absolute offset is informational.)

## 12. Error and degraded-state semantics

Every consumer handles the non-happy path explicitly; "no data" is a state, not a crash.

- **Target lifecycle (C2)**: `tracked` / `predicted` / `stale` / `lost`. Card fallback
  on non-tracked: `hold_last_pose` / `detach` / `fade_out` (per `offset_rule`; default
  in `card_attachment.gd`).
- **Stale depth (C1)**: producer holds last per-track depth; consumer weighs
  `pose_quality` + age as confidence and never blocks.
- **Link loss (C7 / PC-offload)**: fall back to the on-device backend or last-known
  tracks; never black-screen.
- **Malformed payload**: reject at the schema boundary (L0), log, drop the frame; never
  partially apply.
- **Empty result (no targets / no people)**: a valid state; cards idle/hide, assistant
  stays silent.
- **Tool / voice-provider error (C4/C5)**: dispatcher returns a structured error
  response (not an exception); assistant shows an `assistant_state=error` card (C6);
  voice falls back to the other provider or a spoken error.

## 13. Latency and rate budget

End-to-end target: **<= 150 ms** from camera frame to card pose update (person-follow).

Indicative per-stage split (to be measured, not assumed):

- capture + on-device detection/tracking: ~60-80 ms
- C1 -> C2 conversion + alignment: ~10-20 ms
- transport + card update/render: ~20-40 ms
- PC-offload adds a WiFi round-trip; mitigate with on-device tracking bridging
  low-rate PC detection (hybrid) so the *display* stays in budget even when detection lags.

Rates: detection/tracking target the full capture rate (~40-50 fps); depth and
PC-offload detection may run lower with per-track hold. Each module reports its measured
stage latency; modules 3 and 6 own the end-to-end (device) measurement.

## 14. Security and privacy posture (v1)

v1 is a **LAN-trusted demo**: no authentication, no TLS, camera/audio stay on the
intranet. This is an explicit, accepted v1 scope, recorded here with its risks; harden later.

Accepted risks (v1):

- WS / C7 / proxy_targets links are unauthenticated and unencrypted on the LAN; anyone
  on the network can read frames/detections or inject targets.
- Camera frames contain real people (captures include recorded faces); they must stay on
  the intranet and out of git.
- Voice audio is sent to cloud providers (Gemini / Qwen) at the session/transport layer;
  provider terms apply.
- Secrets (voice API keys, future Jira creds) live only in runtime env / custom_env,
  never in repo, metadata, or payloads.

Deferred hardening (post-v1): WS auth + TLS, on-device-only or encrypted PC-offload,
audio redaction/consent, capture retention policy.

## 15. Ownership (confirmed, YAN-96)

Module owners matched to agent specialties (confirmed; the issue tree assigns each
module sub-issue to its owner):

| Scope | Proposed owner | Support |
|-------|----------------|---------|
| Module 1 human tracking | pd-XR (MR/XR, detection) | hard_work_4080-CV (depth/3D), xiami-DSP (on-device perf) |
| Module 2 godot card | pd-XR (Godot/XR) | ui-designer (card UX/visual) |
| Module 3 MR integration | pd-XR (XR/VST) | hard_work_4080-CV (3D/disparity), 2Dto3D架构师 (algorithm route) |
| Module 4 voice | pop-VA (ASR/TTS/LLM/VAD) | laufe-后端 (provider/session plumbing) |
| Module 5 agent assistant | laufe-后端 (tool calling, API integration) | pop-VA (intent) |
| Module 6 Android deploy | 小安开发第二 (win->android) | 小安开发第一 (Android), QA (device/latency/power) |
| Data grading / metrics | yang-QA | QA |
| Contracts C1/C3 freeze (Step 0) | pd-XR + laufe-后端 | TL (Orion-TL) coordinates |

TL (Orion-TL) owns the cross-cutting contracts and this baseline.

## 16. Card/scene convergence and the State/View/Receiver pattern (D2)

D2 decision: **single runtime**. There was in fact never a second Godot project -
`apps/godot_mr` had no `project.godot`; it was three scripts (`assistant_card_state`
/ `assistant_card_view` / `assistant_updates_receiver`) plus two script-only probes,
already reusing godot-android's `WSTransport` by injection. Phase B (YAN-109) moved
those into the device runtime (`godot-android/scripts/assistant/` + `godot-android/tests/`)
and retired `apps/godot_mr/` to a pointer. The device runtime is and stays
`godot-android`. "Convergence" therefore means adopting the layering pattern and
retrofitting the existing card onto it - not merging projects.

Module-2 standard pattern: **State / View / Receiver**.

- **State**: parse / validate / own a snapshot (pure data, script-only testable).
- **View**: render state to nodes (presentation only).
- **Receiver**: wire transport -> state -> view (boundary glue).

godot-android already has the ingredients from A3/A4: State-like
(`status_snapshot_composer`, `proxy_targets_status_fragment`), View-like (`card_view`,
`passthrough_overlay_presenter`), Receiver-like (`proxy_targets_consumer` +
`proxy_targets_card_adapter` + `ws_transport`), orchestrated by `AndroidMovingCard`.

Operational steps (module 2; each a small PR + script-only probe, under existing CI):

- **Phase A (DONE)**: codify State/View/Receiver as the module-2 standard and
  record the D2 decision. No code change.
- **Phase B (DONE, YAN-109)**: relocated the `apps/godot_mr` scripts + probes into the
  runtime tree — the State/View/Receiver trio now lives in
  `godot-android/scripts/assistant/` (`assistant_card_state.gd` /
  `assistant_card_view.gd` / `assistant_updates_receiver.gd`) and the two probes in
  `godot-android/tests/`. `apps/godot_mr/` is retired to a pointer README. The runners
  (`tools/run_godot_mr_assistant_card_probe.ps1`,
  `tools/run_godot_mr_assistant_updates_probe.ps1`, `tools/run_smartmr_mstar_demo.ps1`)
  and the `tests/test_godot_mr_assistant_*` guards now reference the relocated paths;
  the two probes stay as regression anchors. Also under YAN-109: the C3 state machine
  landed as a standalone `godot-android/scripts/card_lifecycle.gd` (the
  appear/expand/contract/disappear lifecycle + attach/detach), with
  `script_only_card_lifecycle_probe.gd` in the gdscript-probes CI list.
- **Phase C (TODO)**: re-express the existing card as `CardState` (data snapshot) /
  `CardView` (`card_view` + overlay presenter) / `CardReceiver` (proxy_targets
  consumer/adapter + ws_transport), shrinking `AndroidMovingCard` to a host that
  instantiates the trio and owns the XR lifecycle. Incremental; needs device/Godot
  verification of the 954-line `AndroidMovingCard` host.
- **Phase D (TODO)**: unify card types - the assistant-card and the tracked-target card
  share one CardState/CardView base, differing only by data source (assistant_updates vs
  proxy_targets). End state: one runtime, one card pattern, two data sources.

Guardrails: do not port native VST/XR/ncnn toward the assistant card layer (reverse
direction = high risk); no big-bang merge; keep the two relocated assistant probes as
regression anchors. Phase A/B can run early/independently; Phase C/D run after C1/C3 are frozen
(the card's data contracts settle first).

## 17. Founding design principles -> architecture mapping (three pillars)

The whole stack is built around three founding product principles. They are not
add-ons; sections 1-16 are *how* these are realized. The single-direction layered
model (§2) is the spine: perception (module 1) and MR presentation (modules 2/3) are
the stage; the capability bus, tool layer, and voice (modules 4/5) are the control
plane on top.

### Pillar 1 - Capability encapsulation (按能力封装)

Each capability is a self-describing, hot-pluggable unit; nothing couples to another
capability's implementation.

- **Macro**: modules 1-6 + frozen versioned contracts C1-C6; pure-Python capability bus
  `smartxr/`. Each module builds against contracts + fakes (§1, §5).
- **Micro (assistant)**: `ToolRegistry` / `ToolSpec` in
  `SmartMRAssistant/assistant/tools.py`. A capability = `name` + `handler` +
  `input_schema` + `output_schema` + `latency_budget_ms` + `scheduling`. `register()`
  is hot-pluggable; `export_schemas()` self-describes (C5). Per-call trace with
  sensitive-arg redaction.
- **Status**: realized. Default capabilities: `scene_status`, `identity_lookup`,
  `work_item_lookup`, `card_command`, `assistant_card_push`.

### Pillar 2 - Business-driven invocation (按业务调用)

Business invokes a capability by contract (name + args), never by implementation.

- **Seam**: C4 `ToolCall` (id/name/args/scheduling) -> `dispatch_tool_call(call, registry)`
  in `dispatcher.py` -> structured `{tool_call_id, name, response}`.
- Capabilities reach the presentation plane by contract too: `card_command` -> control
  payload to the Godot card; `assistant_card_push` -> C6 `assistant_card`.
- **Status**: realized. Limitation: §12 specifies the dispatcher returns a *structured
  error response*; today `dispatch_tool_call` propagates exceptions (traced but not
  normalized) — tracked as a headless follow-up.

### Pillar 3 - Intelligent voice control (智能语音控制)

A provider-neutral LLM voice agent drives capabilities by function-calling.

- `VoiceSession` (ABC, `session.py`) emits C4 tool calls only; audio capture / codec /
  VAD / transport stay outside the interface. Provider adapters
  `GeminiLiveVoiceSession` / `QwenOmniRealtimeVoiceSession` normalize each provider's
  function-call events into the same frozen C4.
- `schema_adapter.export_live_tool_declarations()` advertises C5 capability schemas to
  the voice LLM, closing the loop: C5 declarations -> model function-call -> C4 ->
  dispatcher -> capability -> C6 card.
- `SimulatedVoiceSession` runs the whole loop headless (no mic/headset); e2e covered by
  `tests/test_smartmr_live_assistant_e2e.py`.
- **Status**: realized at the tool-call/event layer and provider-agnostic. Pending: the
  live audio leg (real capture/streaming) is intentionally out of scope of this
  interface and needs voice API credentials (data-need #4) + audio I/O.

### Current limitations / refinements

1. Live audio leg not implemented (Pillar 3) — mock/replay tested headless; live needs
   creds (#4) + audio transport.
2. Dispatcher error contract (Pillar 2) — align with §12 (structured error, not
   exception); headless follow-up.
3. Capability data-source binding (Pillar 1) — `identity_lookup` / `work_item_lookup`
   take their source as a call arg (fixtures, data-need #5); a real integration should
   let the capability own its source adapter.
4. Tool input validation is required-args presence only, not full JSON-schema;
   acceptable for v1.

These are integration-pending items, not structural gaps: the three pillars are
satisfied by construction.
