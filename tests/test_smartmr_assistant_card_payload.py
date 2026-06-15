import unittest

from SmartMRAssistant.assistant.card_payload import (
    ASSISTANT_CARD_SCHEMA_VERSION,
    build_assistant_card_payload,
    summarize_tool_results,
    validate_assistant_card_payload,
)


class SmartMRAssistantCardPayloadTests(unittest.TestCase):
    def test_builds_minimal_assistant_card_payload(self):
        payload = build_assistant_card_payload(
            card_id="CardAnchor",
            target_id="person-ada",
            assistant_state="responding",
            response_text="Ada is working on XR-42.",
        )

        self.assertEqual(payload["type"], "assistant_card")
        self.assertEqual(payload["schema_version"], ASSISTANT_CARD_SCHEMA_VERSION)
        self.assertEqual(payload["card_id"], "CardAnchor")
        self.assertEqual(payload["target_id"], "person-ada")
        self.assertEqual(payload["assistant_state"], "responding")
        self.assertEqual(payload["response_text"], "Ada is working on XR-42.")
        self.assertEqual(payload["tool_summary"], {})
        self.assertIsNone(payload["person"])
        self.assertIsNone(payload["issue"])
        self.assertEqual(validate_assistant_card_payload(payload), [])

    def test_rejects_missing_required_payload_fields(self):
        payload = {
            "type": "assistant_card",
            "schema_version": ASSISTANT_CARD_SCHEMA_VERSION,
            "card_id": "",
            "target_id": "person-ada",
            "assistant_state": "responding",
            "response_text": "Ada is working on XR-42.",
        }

        self.assertEqual(
            validate_assistant_card_payload(payload),
            ["$.card_id must be a non-empty string"],
        )

    def test_summarizes_identity_and_jira_results_for_card_text(self):
        summary = summarize_tool_results(
            identity_result={
                "status": "found",
                "person": {
                    "id": "person-ada",
                    "display_name": "Ada Lovelace",
                    "role": "Demo Lead",
                },
            },
            jira_result={
                "status": "found",
                "issue": {
                    "key": "XR-42",
                    "summary": "Prepare MR assistant demo",
                    "status": "In Progress",
                    "assignee": "Ada",
                },
            },
        )

        self.assertEqual(
            summary,
            {
                "identity_status": "found",
                "jira_status": "found",
                "person_label": "Ada Lovelace",
                "issue_label": "XR-42: Prepare MR assistant demo",
                "status_line": "Ada Lovelace | XR-42 | In Progress",
            },
        )


if __name__ == "__main__":
    unittest.main()
