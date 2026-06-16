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
- `assistant/session.py` contains the provider-neutral `VoiceSession` contract,
  `GeminiLiveVoiceSession` and `QwenOmniRealtimeVoiceSession` adapters, and
  `SimulatedVoiceSession` for local headless runs.
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
```

## Environment

The S1 simulator does not require headset hardware, microphone access, Gemini
credentials, Qwen credentials, or a Godot runtime.

Live provider sessions read model IDs from environment variables so model names
can be confirmed at startup without code changes:

```powershell
$env:SMARTMR_VOICE_GEMINI_MODEL = "gemini-3.1-flash-live-preview"
$env:SMARTMR_VOICE_QWEN_MODEL = "qwen3.5-omni-plus"
$env:GEMINI_API_KEY = "<runtime secret>"
$env:DASHSCOPE_API_KEY = "<runtime secret>"
```

The API key values stay in the runtime environment only. The dispatcher receives
only C4 tool-call objects and never reads audio, model IDs, or provider secrets.
As of 2026-06-16, Google lists `gemini-3.1-flash-live-preview` as the current
Live API preview model. Alibaba Cloud's current Qwen-Omni documentation lists
`qwen3.5-omni-plus` for streaming omni-modal invocation; if a Qwen Realtime
endpoint exposes a different model ID in the target region, set
`SMARTMR_VOICE_QWEN_MODEL` to that value at startup.

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
