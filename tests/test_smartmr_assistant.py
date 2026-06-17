import asyncio
import json
import unittest
from pathlib import Path

from SmartMRAssistant.assistant.dispatcher import ToolCall, dispatch_tool_call
from SmartMRAssistant.assistant.session import LiveVoiceSession, SimulatedVoiceSession
from SmartMRAssistant.assistant.tools import ToolRegistry, create_default_registry


class SmartMRAssistantToolTests(unittest.TestCase):
    def test_default_registry_exports_real_capability_tools(self):
        registry = create_default_registry()

        exported = registry.export_schemas()

        self.assertEqual(
            set(exported),
            {
                "scene_status",
                "identity_lookup",
                "work_item_lookup",
                "card_command",
                "assistant_card_push",
            },
        )
        self.assertNotIn("echo", exported)
        self.assertNotIn("jira_lookup", exported)
        self.assertEqual(exported["scene_status"]["scheduling"], "NON_BLOCKING")
        self.assertEqual(exported["assistant_card_push"]["output_schema"]["required"], ["status", "assistant_card"])

    def test_default_registry_runs_identity_lookup_tool(self):
        registry = create_default_registry()

        result = asyncio.run(
            registry.run(
                "identity_lookup",
                {
                    "person_ref": "person-ada",
                    "identity_source": {
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

    def test_default_registry_runs_work_item_lookup_tool(self):
        registry = create_default_registry()

        result = asyncio.run(
            registry.run(
                "work_item_lookup",
                {
                    "issue_key": "XR-42",
                    "work_item_source": {
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
                "work_item": {
                    "key": "XR-42",
                    "summary": "Prepare MR assistant demo",
                    "status": "In Progress",
                    "assignee": "Ada",
                },
            },
        )

    def test_scene_status_returns_latest_context_snapshot(self):
        registry = create_default_registry()

        result = asyncio.run(
            registry.run(
                "scene_status",
                {
                    "scene_snapshot": {
                        "last_user_text": "他手上有什么任务",
                        "facts": {"active_card_id": "CardAnchor"},
                    }
                },
            )
        )

        self.assertEqual(
            result,
            {
                "status": "ok",
                "scene": {
                    "last_user_text": "他手上有什么任务",
                    "facts": {"active_card_id": "CardAnchor"},
                },
            },
        )

    def test_card_command_returns_c3_control_payload(self):
        registry = create_default_registry()

        result = asyncio.run(
            registry.run(
                "card_command",
                {
                    "card_id": "CardAnchor",
                    "command": "expand",
                    "target_id": "person-ada",
                },
            )
        )

        self.assertEqual(
            result,
            {
                "status": "accepted",
                "control": {
                    "type": "control",
                    "command": "expand",
                    "card_id": "CardAnchor",
                    "target_id": "person-ada",
                },
            },
        )

    def test_assistant_card_push_builds_c6_payload_and_records_sink(self):
        published = []
        registry = create_default_registry(card_sink=published.append)

        result = asyncio.run(
            registry.run(
                "assistant_card_push",
                {
                    "card_id": "CardAnchor",
                    "target_id": "person-ada",
                    "assistant_state": "responding",
                    "response_text": "Ada Lovelace is working on XR-42.",
                    "tool_summary": {"status_line": "Ada Lovelace | XR-42 | In Progress"},
                    "person": {"id": "person-ada", "display_name": "Ada Lovelace"},
                    "issue": {"key": "XR-42", "summary": "Prepare MR assistant demo"},
                },
            )
        )

        self.assertEqual(result["status"], "published")
        self.assertEqual(result["assistant_card"]["type"], "assistant_card")
        self.assertEqual(result["assistant_card"]["response_text"], "Ada Lovelace is working on XR-42.")
        self.assertEqual(published, [result["assistant_card"]])

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

            asyncio.run(registry.run("identity_lookup", {"person_ref": "missing", "identity_source": {"people": []}}))
            with self.assertRaises(ValueError):
                asyncio.run(registry.run("work_item_lookup", {}))

            records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        finally:
            trace_path.unlink(missing_ok=True)

        self.assertEqual([record["tool_name"] for record in records], ["identity_lookup", "work_item_lookup"])
        self.assertEqual(records[0]["success"], True)
        self.assertEqual(records[0]["args_summary"], {"person_ref": "missing"})
        self.assertNotIn("identity_source", records[0]["args_summary"])
        self.assertIn("duration_ms", records[0])
        self.assertEqual(records[1]["success"], False)
        self.assertEqual(records[1]["error_type"], "ValueError")


class SmartMRAssistantDispatcherTests(unittest.TestCase):
    def test_dispatcher_executes_non_blocking_scene_status_call(self):
        registry = create_default_registry()
        call = ToolCall(
            id="call-1",
            name="scene_status",
            args={"scene_snapshot": {"last_user_text": "ping", "facts": {}}},
            scheduling="NON_BLOCKING",
        )

        response = asyncio.run(dispatch_tool_call(call, registry))

        self.assertEqual(
            response,
            {
                "tool_call_id": "call-1",
                "name": "scene_status",
                "response": {"status": "ok", "scene": {"last_user_text": "ping", "facts": {}}},
            },
        )

    def test_simulated_voice_session_turn_invokes_capabilities_and_pushes_card(self):
        published = []
        session = SimulatedVoiceSession(registry=create_default_registry())
        session.card_sink = published.append

        responses = asyncio.run(session.run_text_turn("他手上有什么任务"))

        self.assertEqual(
            [response["name"] for response in responses],
            ["scene_status", "identity_lookup", "work_item_lookup", "assistant_card_push"],
        )
        self.assertEqual(session.context.last_user_text, "他手上有什么任务")
        self.assertEqual(responses[-1]["response"]["status"], "published")
        self.assertEqual(responses[-1]["response"]["assistant_card"]["type"], "assistant_card")
        self.assertEqual(published, [responses[-1]["response"]["assistant_card"]])

    def test_simulated_voice_session_can_run_named_tool_call(self):
        session = SimulatedVoiceSession(registry=create_default_registry())

        response = asyncio.run(
            session.run_tool_call(
                "identity_lookup",
                {
                    "person_ref": "person-grace",
                    "identity_source": {
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
                    "name": "scene_status",
                    "args": {"scene_snapshot": {"last_user_text": "from live", "facts": {}}},
                    "scheduling": "NON_BLOCKING",
                }
            )
        )

        self.assertEqual(response["tool_call_id"], "live-call-1")
        self.assertEqual(response["response"], {"status": "ok", "scene": {"last_user_text": "from live", "facts": {}}})


if __name__ == "__main__":
    unittest.main()
