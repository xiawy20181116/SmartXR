import asyncio
import unittest

from SmartMRAssistant.assistant.session import LiveVoiceSession
from SmartMRAssistant.assistant.tools import create_default_registry
from SmartMRAssistant.assistant.schema_adapter import export_live_tool_declarations
from SmartMRAssistant.assistant.live_adapter import handle_live_tool_call_event, normalize_live_tool_call_event


class SmartMRLiveSchemaAdapterTests(unittest.TestCase):
    def test_exports_c5_registry_schemas_as_live_tool_declarations(self):
        registry = create_default_registry()

        declarations = export_live_tool_declarations(registry.export_schemas())

        self.assertEqual(
            [item["name"] for item in declarations["function_declarations"]],
            ["scene_status", "identity_lookup", "work_item_lookup", "card_command", "assistant_card_push"],
        )
        identity = declarations["function_declarations"][1]
        self.assertEqual(identity["parameters"]["required"], ["person_ref"])
        self.assertEqual(identity["x_smartxr"]["scheduling"], "NON_BLOCKING")
        self.assertEqual(identity["x_smartxr"]["latency_budget_ms"], 150)


class SmartMRLiveToolCallAdapterTests(unittest.TestCase):
    def test_normalizes_provider_function_call_event(self):
        payload = normalize_live_tool_call_event(
            {
                "function_call": {
                    "id": "provider-call-1",
                    "name": "scene_status",
                    "arguments": '{"scene_snapshot": {"last_user_text": "ping", "facts": {}}}',
                }
            }
        )

        self.assertEqual(
            payload,
            {
                "id": "provider-call-1",
                "name": "scene_status",
                "args": {"scene_snapshot": {"last_user_text": "ping", "facts": {}}},
                "scheduling": "NON_BLOCKING",
            },
        )

    def test_handles_live_tool_call_event_through_session(self):
        session = LiveVoiceSession(registry=create_default_registry())

        response = asyncio.run(
            handle_live_tool_call_event(
                {
                    "tool_call": {
                        "id": "live-identity-1",
                        "name": "identity_lookup",
                        "args": {
                            "person_ref": "person-ada",
                            "identity_source": {"people": [{"id": "person-ada", "display_name": "Ada Lovelace"}]},
                        },
                    }
                },
                session,
            )
        )

        self.assertEqual(response["ok"], True)
        self.assertEqual(response["tool_call_id"], "live-identity-1")
        self.assertEqual(response["response"]["person"]["display_name"], "Ada Lovelace")

    def test_returns_tool_error_response_without_crashing_event_loop(self):
        session = LiveVoiceSession(registry=create_default_registry())

        response = asyncio.run(
            handle_live_tool_call_event(
                {
                    "tool_call": {
                        "id": "live-work-item-err",
                        "name": "work_item_lookup",
                        "args": {},
                    }
                },
                session,
            )
        )

        self.assertEqual(response["ok"], True)
        self.assertEqual(response["tool_call_id"], "live-work-item-err")
        self.assertEqual(response["name"], "work_item_lookup")
        self.assertEqual(response["response"]["status"], "error")
        self.assertEqual(response["response"]["error_type"], "MissingRequiredArgumentError")
        self.assertIn("missing required", response["response"]["message"])


if __name__ == "__main__":
    unittest.main()
