import asyncio
import unittest

from SmartMRAssistant.assistant.card_payload import validate_assistant_card_payload
from SmartMRAssistant.assistant.live_adapter import run_fake_live_task_query_turn
from SmartMRAssistant.assistant.session import LiveVoiceSession
from SmartMRAssistant.assistant.tools import create_default_registry


class SmartMRLiveAssistantE2ETests(unittest.TestCase):
    def test_fake_live_text_turn_runs_l1_l2_tool_chain_to_assistant_card(self):
        published = []
        session = LiveVoiceSession(registry=create_default_registry(card_sink=published.append))

        result = asyncio.run(run_fake_live_task_query_turn("他手上有什么任务", session))

        self.assertEqual(result["text"], "他手上有什么任务")
        self.assertEqual(
            [item["name"] for item in result["tool_responses"]],
            ["scene_status", "identity_lookup", "work_item_lookup", "assistant_card_push"],
        )
        self.assertEqual([item["ok"] for item in result["tool_responses"]], [True, True, True, True])

        card = result["assistant_card"]
        self.assertEqual(validate_assistant_card_payload(card), [])
        self.assertEqual(card["type"], "assistant_card")
        self.assertEqual(card["target_id"], "person-ada")
        self.assertEqual(card["response_text"], "Ada Lovelace is working on XR-42: Prepare MR assistant demo.")
        self.assertEqual(card["tool_summary"]["status_line"], "Ada Lovelace | XR-42 | In Progress")
        self.assertEqual(published, [card])


if __name__ == "__main__":
    unittest.main()
