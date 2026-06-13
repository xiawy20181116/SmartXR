# SmartMRAssistant

S1 establishes a small Python-side voice assistant skeleton for the future Godot
MR assistant. It keeps the audio transport boundary separate from tool dispatch:
`assistant.session` adapts Live-style tool-call payloads, and
`assistant.dispatcher` only receives structured tool calls.

## Structure

- `assistant/context.py` keeps the scene-context interface. S1 stores only the
  latest text turn and a generic facts map.
- `assistant/tools.py` owns the async-aware tool registry and registers the
  initial `echo` tool.
- `assistant/dispatcher.py` executes a `ToolCall` through the registry and
  returns a tool response payload.
- `assistant/session.py` contains `LiveVoiceSession` for Live tool-call payloads
  and `SimulatedVoiceSession` for local headless runs.
- `assistant/__main__.py` provides the local no-headset simulation entry point.

## Local S1 Run

From the repository root:

```powershell
python -m SmartMRAssistant.assistant --text "hello assistant"
```

Expected output is a JSON object with one echo tool response:

```json
{"tool_responses": [{"tool_call_id": "simulated-echo-1", "name": "echo", "response": {"text": "hello assistant"}}]}
```

## Tests

```powershell
python -m unittest tests.test_smartmr_assistant
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
