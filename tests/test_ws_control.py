import json
import unittest

from windows_server import ws_control


class WsControlTests(unittest.TestCase):
    def test_build_control_message_uses_stable_android_protocol(self):
        payload = ws_control.build_control_message("left")

        self.assertEqual(json.loads(payload), {"type": "control", "command": "left"})

    def test_key_mapping_covers_yaw_pitch_depth_speed_pause_and_reset(self):
        cases = {
            "a": "yaw_left",
            "D": "yaw_right",
            "w": "pitch_up",
            "s": "pitch_down",
            "left": "yaw_left",
            "RIGHT": "yaw_right",
            "+": "speed_up",
            "=": "speed_up",
            "-": "speed_down",
            "[": "depth_out",
            "]": "depth_in",
            "space": "pause",
            " ": "pause",
            "r": "reset",
        }

        for key, command in cases.items():
            with self.subTest(key=key):
                self.assertEqual(ws_control.command_for_key(key), command)

    def test_unknown_key_has_no_command(self):
        self.assertIsNone(ws_control.command_for_key("x"))

    def test_websocket_accept_key_matches_protocol_example(self):
        accept = ws_control.make_websocket_accept_key("dGhlIHNhbXBsZSBub25jZQ==")

        self.assertEqual(accept, "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_stdlib_text_frame_encodes_unmasked_server_payload(self):
        frame = ws_control.encode_server_text_frame("hi")

        self.assertEqual(frame, b"\x81\x02hi")


if __name__ == "__main__":
    unittest.main()
