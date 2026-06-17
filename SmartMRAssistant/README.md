# SmartMRAssistant

SmartMRAssistant is a small Python-side voice assistant skeleton for the future
Godot MR assistant. It keeps the audio transport boundary separate from tool dispatch:
`assistant.session` adapts Live-style tool-call payloads, and
`assistant.dispatcher` only receives structured tool calls.

## Structure

- `assistant/context.py` keeps the scene-context interface. S1 stores only the
  latest text turn and a generic facts map.
- `assistant/tools.py` owns the async-aware schema registry, fixture-backed
  capability tools, C3/C6 payload builders, and optional JSONL tool-call
  tracing.
- `assistant/dispatcher.py` executes a `ToolCall` through the registry and
  returns a tool response payload.
- `assistant/session.py` contains `LiveVoiceSession` for Live tool-call payloads
  and `SimulatedVoiceSession` for local headless runs.
- `assistant/schema_adapter.py` converts exported C5 tool schemas into
  provider-neutral Live tool declarations.
- `assistant/live_adapter.py` normalizes provider-style tool-call events and
  provides the fake Live L1/L2 task-query path.
- `assistant/__main__.py` provides the local no-headset simulation entry point.

## Tools

The default registry exports schema metadata for real assistant capabilities:

- `scene_status` returns the latest scene context snapshot passed by the
  session or Live tool-call adapter.
- `identity_lookup` searches an identity source shaped like
  `{"people": [{"id": "...", "display_name": "..."}]}`.
- `work_item_lookup` searches a Jira/work-item source shaped like
  `{"issues": [{"key": "...", "summary": "..."}]}`.
- `card_command` builds a C3-style control payload such as
  `{"type": "control", "command": "expand", "card_id": "..."}`.
- `assistant_card_push` builds and optionally publishes a C6 `assistant_card`
  payload for the Godot `assistant_updates` path.

The lookup tools are fixture-backed by default. They do not call network
services, read credentials, or require a live Jira/identity connection; real
sources can be injected later at the session boundary without changing the
dispatcher contract.

## Live Adapter L1/L2

The L1 adapter path starts from `create_default_registry().export_schemas()` and
uses `export_live_tool_declarations()` to build provider-neutral Live tool
declarations. Each declaration carries the input schema plus SmartXR metadata
for output schema, latency budget, and scheduling.

The L2 fake Live path uses `handle_live_tool_call_event()` and
`run_fake_live_task_query_turn()` to exercise provider-shaped events without a
real microphone, model session, Jira service, or headset:

```python
published = []
session = LiveVoiceSession(registry=create_default_registry(card_sink=published.append))
result = await run_fake_live_task_query_turn("他手上有什么任务", session)
assistant_card = result["assistant_card"]
```

That path normalizes fake/provider tool calls into
`LiveVoiceSession.handle_tool_call_payload()`, runs the real dispatcher and
handlers, and finishes with a C6 `assistant_card`. Tool failures are returned as
structured error responses so a future Live event loop can send provider-visible
tool errors without crashing.

Pass `trace_path` to `create_default_registry()` to append one JSON object per
tool call. Trace records include the tool name, summarized non-sensitive args,
start/end timestamps, duration, success flag, and error type for failures.

## Local Run

From the repository root:

```powershell
python -m SmartMRAssistant.assistant --text "hello assistant"
```

Expected output is a JSON object with scene, lookup, work-item, and card-push
tool responses:

```json
{"tool_responses": [{"tool_call_id": "simulated-scene-status-1", "name": "scene_status", "response": {"status": "ok", "scene": {"last_user_text": "hello assistant", "facts": {}}}}, {"tool_call_id": "simulated-identity-1", "name": "identity_lookup", "response": {"status": "found", "person": {"id": "person-ada", "display_name": "Ada Lovelace", "role": "Demo Lead", "confidence": 0.93}}}, {"tool_call_id": "simulated-work-item-1", "name": "work_item_lookup", "response": {"status": "found", "work_item": {"key": "XR-42", "summary": "Prepare MR assistant demo", "status": "In Progress", "assignee": "Ada"}}}, {"tool_call_id": "simulated-card-push-1", "name": "assistant_card_push", "response": {"status": "published", "assistant_card": {"type": "assistant_card", "schema_version": 1, "card_id": "CardAnchor", "target_id": "person-ada", "assistant_state": "responding", "response_text": "Ada Lovelace is working on XR-42: Prepare MR assistant demo.", "tool_summary": {"identity_status": "found", "jira_status": "found", "person_label": "Ada Lovelace", "issue_label": "XR-42: Prepare MR assistant demo", "status_line": "Ada Lovelace | XR-42 | In Progress"}, "person": {"id": "person-ada", "display_name": "Ada Lovelace", "role": "Demo Lead", "confidence": 0.93}, "issue": {"key": "XR-42", "summary": "Prepare MR assistant demo", "status": "In Progress", "assignee": "Ada"}}}}]}
```

Headless tests and text debug code can also call a named tool without audio:

```python
session = SimulatedVoiceSession()
response = await session.run_tool_call(
    "identity_lookup",
    {"person_ref": "person-1", "identity_source": {"people": [{"id": "person-1"}]}},
)
```

## Tests

```powershell
python -m unittest tests.test_smartmr_assistant
python -m unittest tests.test_smartmr_live_adapter tests.test_smartmr_live_assistant_e2e
```

## Environment

The S1 simulator does not require headset hardware, microphone access, Gemini
credentials, or a Godot runtime. Future Live integration should add provider
credentials at the session/transport layer, not inside the dispatcher.

## Source Relationship

SmartXR remains the device-side and shared Python baseline for Godot transport,
schemas, and probe patterns. SmartMRAssistant is a new project root layered next
to that baseline so later work can connect assistant behavior to Godot without
coupling S1 to the existing target-publisher path.

Antman_smart is treated as a capability source for future voice/session
behavior. S1 does not copy Antman_smart code because this checkout does not
contain that project; the current implementation preserves the intended
boundary for later migration by keeping Live session adaptation separate from
tool dispatch.
