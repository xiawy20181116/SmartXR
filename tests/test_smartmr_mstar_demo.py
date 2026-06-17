import asyncio
from pathlib import Path
import unittest

from SmartMRAssistant.assistant.card_payload import validate_assistant_card_payload
from SmartMRAssistant.assistant.demo import build_mstar_demo_result


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "tools" / "smartmr_mstar_demo_publisher.py"
RUNNER = ROOT / "tools" / "run_smartmr_mstar_demo.ps1"


class SmartMRMStarDemoTests(unittest.TestCase):
    def test_builds_demo_payload_from_simulated_identity_and_jira_tool_calls(self):
        result = asyncio.run(build_mstar_demo_result())

        self.assertEqual(result["question"], "他手上有什么任务")
        self.assertEqual(
            [item["name"] for item in result["tool_responses"]],
            ["scene_status", "identity_lookup", "work_item_lookup", "assistant_card_push"],
        )
        self.assertEqual(result["tool_responses"][1]["tool_call_id"], "mstar-identity-1")
        self.assertEqual(result["tool_responses"][2]["tool_call_id"], "mstar-work-item-1")
        self.assertEqual(result["tool_responses"][3]["tool_call_id"], "mstar-card-push-1")

        payload = result["assistant_card"]
        self.assertEqual(validate_assistant_card_payload(payload), [])
        self.assertEqual(payload["type"], "assistant_card")
        self.assertEqual(payload["card_id"], "CardAnchor")
        self.assertEqual(payload["target_id"], "person-ada")
        self.assertEqual(payload["assistant_state"], "responding")
        self.assertEqual(payload["response_text"], "Ada Lovelace is working on XR-42: Prepare MR assistant demo.")
        self.assertEqual(payload["tool_summary"]["status_line"], "Ada Lovelace | XR-42 | In Progress")
        self.assertEqual(payload["person"]["display_name"], "Ada Lovelace")
        self.assertEqual(payload["issue"]["key"], "XR-42")

    def test_demo_publisher_serves_demo_payload_on_assistant_updates(self):
        source = PUBLISHER.read_text(encoding="utf-8")

        self.assertIn("build_mstar_demo_result_sync", source)
        self.assertIn('return path == "/assistant_updates"', source)
        self.assertIn("encode_websocket_text_frame", source)
        self.assertIn("serve_single_client", source)
        self.assertIn("assistant_updates M-star demo publisher listening", source)
        self.assertIn('message = build_mstar_demo_result_sync()["assistant_card"]', source)

    def test_runner_reuses_assistant_updates_probe_with_mstar_demo_publisher(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("smartmr_mstar_demo_publisher.py", source)
        self.assertIn("script_only_assistant_updates_probe.gd", source)
        self.assertIn("SMARTXR_ASSISTANT_UPDATES_LIVE_WS_URL", source)
        self.assertIn("SMARTXR_ASSISTANT_UPDATES_EXPECTED_RESPONSE_TEXT", source)
        self.assertIn("Ada Lovelace is working on XR-42: Prepare MR assistant demo.", source)
        self.assertIn("assistant_updates M-star demo publisher listening", source)
        self.assertIn('"--script", $ProbeScript', source)
        self.assertNotIn('"--path"', source)


if __name__ == "__main__":
    unittest.main()
