import asyncio
import json
import unittest
from pathlib import Path

from SmartMRAssistant.assistant.dispatcher import ToolCall, dispatch_tool_call
from SmartMRAssistant.assistant.session import LiveVoiceSession, SimulatedVoiceSession
from SmartMRAssistant.assistant.tools import ToolRegistry, create_default_registry


class SmartMRAssistantToolTests(unittest.TestCase):
    def test_default_registry_runs_echo_tool(self):
        registry = create_default_registry()

        result = asyncio.run(registry.run("echo", {"text": "hello"}))

        self.assertEqual(result, {"text": "hello"})

    def test_default_registry_runs_identity_lookup_tool(self):
        registry = create_default_registry()

        result = asyncio.run(
            registry.run(
                "identity_lookup",
                {
                    "person_ref": "person-ada",
                    "snapshot": {
                        "people": [
                            {
                                "id": "person-ada",
                                "display_name": "Ada Lovelace",
                                "role": "Demo Lead",
                                "confidence": 0.93,
                            }
                        ]
                    },
                },
            )
        )

        self.assertEqual(
            result,
            {
                "status": "found",
                "person": {
                    "id": "person-ada",
                    "display_name": "Ada Lovelace",
                    "role": "Demo Lead",
                    "confidence": 0.93,
                },
            },
        )

    def test_default_registry_runs_jira_lookup_tool(self):
        registry = create_default_registry()

        result = asyncio.run(
            registry.run(
                "jira_lookup",
                {
                    "issue_key": "XR-42",
                    "cache": {
                        "issues": [
                            {
                                "key": "XR-42",
                                "summary": "Prepare MR assistant demo",
                                "status": "In Progress",
                                "assignee": "Ada",
                            }
                        ]
                    },
                },
            )
        )

        self.assertEqual(
            result,
            {
                "status": "found",
                "issue": {
                    "key": "XR-42",
                    "summary": "Prepare MR assistant demo",
                    "status": "In Progress",
                    "assignee": "Ada",
                },
            },
        )

    def test_registry_exports_tool_schemas_and_scheduling_metadata(self):
        registry = create_default_registry()

        exported = registry.export_schemas()

        self.assertEqual(
            set(exported),
            {"echo", "identity_lookup", "jira_lookup"},
        )
        self.assertEqual(exported["identity_lookup"]["scheduling"], "NON_BLOCKING")
        self.assertEqual(exported["identity_lookup"]["latency_budget_ms"], 150)
        self.assertEqual(exported["jira_lookup"]["input_schema"]["type"], "object")
        self.assertIn("output_schema", exported["jira_lookup"])

    def test_registry_rejects_unknown_tool(self):
        registry = ToolRegistry()

        with self.assertRaises(KeyError):
            asyncio.run(registry.run("missing", {}))

    def test_registry_validates_required_tool_arguments(self):
        registry = create_default_registry()

        with self.assertRaises(ValueError):
            asyncio.run(registry.run("identity_lookup", {}))

    def test_registry_writes_jsonl_trace_for_success_and_failure(self):
        trace_path = Path("tool_calls_test.jsonl")
        try:
            trace_path.unlink(missing_ok=True)
            registry = create_default_registry(trace_path=trace_path)

            asyncio.run(registry.run("identity_lookup", {"person_ref": "missing", "snapshot": {"people": []}}))
            with self.assertRaises(ValueError):
                asyncio.run(registry.run("jira_lookup", {}))

            records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        finally:
            trace_path.unlink(missing_ok=True)

        self.assertEqual([record["tool_name"] for record in records], ["identity_lookup", "jira_lookup"])
        self.assertEqual(records[0]["success"], True)
        self.assertEqual(records[0]["args_summary"], {"person_ref": "missing"})
        self.assertNotIn("snapshot", records[0]["args_summary"])
        self.assertIn("duration_ms", records[0])
        self.assertEqual(records[1]["success"], False)
        self.assertEqual(records[1]["error_type"], "ValueError")


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

    def test_simulated_voice_session_can_run_named_tool_call(self):
        session = SimulatedVoiceSession(registry=create_default_registry())

        response = asyncio.run(
            session.run_tool_call(
                "identity_lookup",
                {
                    "person_ref": "person-grace",
                    "snapshot": {
                        "people": [
                            {
                                "id": "person-grace",
                                "display_name": "Grace Hopper",
                            }
                        ]
                    },
                },
            )
        )

        self.assertEqual(response["name"], "identity_lookup")
        self.assertEqual(response["response"]["person"]["display_name"], "Grace Hopper")

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
