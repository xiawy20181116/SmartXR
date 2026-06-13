import asyncio
import unittest

from SmartMRAssistant.assistant.dispatcher import ToolCall, dispatch_tool_call
from SmartMRAssistant.assistant.session import LiveVoiceSession, SimulatedVoiceSession
from SmartMRAssistant.assistant.tools import ToolRegistry, create_default_registry


class SmartMRAssistantToolTests(unittest.TestCase):
    def test_default_registry_runs_echo_tool(self):
        registry = create_default_registry()

        result = asyncio.run(registry.run("echo", {"text": "hello"}))

        self.assertEqual(result, {"text": "hello"})

    def test_registry_rejects_unknown_tool(self):
        registry = ToolRegistry()

        with self.assertRaises(KeyError):
            asyncio.run(registry.run("missing", {}))


class SmartMRAssistantDispatcherTests(unittest.TestCase):
    def test_dispatcher_executes_non_blocking_echo_call(self):
        registry = create_default_registry()
        call = ToolCall(
            id="call-1",
            name="echo",
            args={"text": "ping"},
            scheduling="NON_BLOCKING",
        )

        response = asyncio.run(dispatch_tool_call(call, registry))

        self.assertEqual(
            response,
            {
                "tool_call_id": "call-1",
                "name": "echo",
                "response": {"text": "ping"},
            },
        )

    def test_simulated_voice_session_keeps_audio_outside_dispatcher(self):
        session = SimulatedVoiceSession(registry=create_default_registry())

        responses = asyncio.run(session.run_text_turn("repeat after me"))

        self.assertEqual(responses[0]["response"], {"text": "repeat after me"})
        self.assertEqual(session.context.last_user_text, "repeat after me")

    def test_live_voice_session_dispatches_tool_call_payload(self):
        session = LiveVoiceSession(registry=create_default_registry())

        response = asyncio.run(
            session.handle_tool_call_payload(
                {
                    "id": "live-call-1",
                    "name": "echo",
                    "args": {"text": "from live"},
                    "scheduling": "NON_BLOCKING",
                }
            )
        )

        self.assertEqual(response["tool_call_id"], "live-call-1")
        self.assertEqual(response["response"], {"text": "from live"})


if __name__ == "__main__":
    unittest.main()
