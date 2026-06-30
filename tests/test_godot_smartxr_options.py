from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
OPTIONS = ROOT / "godot-android" / "scripts" / "smartxr_options.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
DOC = ROOT / "docs" / "smartxr_options.md"
REPO_CONFIG = ROOT / "config" / "smartxr_options.json"


class GodotSmartXROptionsTests(unittest.TestCase):
    def test_options_class_exists_with_config_file_and_env_resolution(self):
        source = OPTIONS.read_text(encoding="utf-8")

        self.assertIn("class_name SmartXROptions", source)
        self.assertIn('const CONFIG_RES := "user://smartxr_options.json"', source)
        self.assertIn('const ENV_OPTIONS_PATH := "SMARTXR_OPTIONS_PATH"', source)
        # Untyped static constructors on purpose: self-referencing the
        # class_name breaks compilation in no-project (script-only) mode.
        self.assertIn("static func load_options():", source)
        self.assertIn("static func load_options_from(config_path: String):", source)
        self.assertIn("var config_path := OS.get_environment(ENV_OPTIONS_PATH).strip_edges()", source)
        self.assertNotIn("SmartXROptions.new()", source)
        # Resolution order: env var first, then config file, then default.
        self.assertIn("func resolve_string(config_key: String, env_name: String, default_value: String) -> String:", source)
        self.assertIn("func resolve_bool(config_key: String, env_name: String, default_value: bool) -> bool:", source)
        self.assertIn("OS.get_environment(env_name)", source)
        self.assertLess(
            source.index("OS.get_environment(env_name)"),
            source.index("_config.has(config_key)"),
        )

    def test_options_cover_control_and_proxy_targets_ws_settings(self):
        source = OPTIONS.read_text(encoding="utf-8")

        self.assertIn('const ENV_CONTROL_WS_URL := "SMARTXR_CONTROL_WS_URL"', source)
        # Historical env var name is preserved for the proxy_targets stream.
        self.assertIn('const ENV_PROXY_TARGETS_WS_URL := "PROXY_TARGETS_WS_URL"', source)
        self.assertIn('const ENV_PROXY_TARGETS_WS_ENABLED := "SMARTXR_PROXY_TARGETS_WS_ENABLED"', source)
        self.assertIn('const ENV_VST_HORIZONTAL_FOV_DEG := "SMARTXR_VST_HORIZONTAL_FOV_DEG"', source)
        self.assertIn('const ENV_VST_VERTICAL_FOV_DEG := "SMARTXR_VST_VERTICAL_FOV_DEG"', source)
        self.assertIn('const ENV_VST_PRINCIPAL_POINT_X := "SMARTXR_VST_PRINCIPAL_POINT_X"', source)
        self.assertIn('const ENV_VST_PRINCIPAL_POINT_Y := "SMARTXR_VST_PRINCIPAL_POINT_Y"', source)
        self.assertIn('const ENV_VST_FOCAL_LENGTH_X := "SMARTXR_VST_FOCAL_LENGTH_X"', source)
        self.assertIn('const ENV_VST_FOCAL_LENGTH_Y := "SMARTXR_VST_FOCAL_LENGTH_Y"', source)
        self.assertIn('const ENV_STATUS_HUD_VISIBLE := "SMARTXR_STATUS_HUD_VISIBLE"', source)
        self.assertIn('const ENV_PROXY_TARGETS_ANCHOR_MODE := "SMARTXR_PROXY_TARGETS_ANCHOR_MODE"', source)
        self.assertIn('const ENV_PROXY_TARGETS_HEAD_Z_MODE := "SMARTXR_PROXY_TARGETS_HEAD_Z_MODE"', source)
        self.assertIn('const ENV_PROXY_TARGETS_CARD_OFFSET_MODE := "SMARTXR_PROXY_TARGETS_CARD_OFFSET_MODE"', source)
        self.assertIn('const ENV_PROXY_TARGETS_CARD_DEPTH_SCALE := "SMARTXR_PROXY_TARGETS_CARD_DEPTH_SCALE"', source)
        self.assertIn('const ENV_PROXY_TARGETS_CARD_DEPTH_OFFSET_M := "SMARTXR_PROXY_TARGETS_CARD_DEPTH_OFFSET_M"', source)
        self.assertIn('const ENV_PROXY_TARGETS_CARD_RIGHT_WIDTH_FRACTION := "SMARTXR_PROXY_TARGETS_CARD_RIGHT_WIDTH_FRACTION"', source)
        self.assertIn('const ENV_PROXY_TARGETS_CARD_RIGHT_ANGLE_DEG := "SMARTXR_PROXY_TARGETS_CARD_RIGHT_ANGLE_DEG"', source)
        self.assertIn('const ENV_PROXY_TARGETS_CARD_UP_M := "SMARTXR_PROXY_TARGETS_CARD_UP_M"', source)
        self.assertIn("func control_ws_url(default_url: String) -> String:", source)
        self.assertIn("func proxy_targets_ws_url(default_url: String) -> String:", source)
        self.assertIn("func proxy_targets_ws_enabled(default_enabled: bool) -> bool:", source)
        self.assertIn("func proxy_targets_anchor_mode(default_mode: String) -> String:", source)
        self.assertIn('return resolve_string("proxy_targets_anchor_mode", ENV_PROXY_TARGETS_ANCHOR_MODE, default_mode)', source)
        self.assertIn("func proxy_targets_head_z_mode(default_mode: String) -> String:", source)
        self.assertIn('return resolve_string("proxy_targets_head_z_mode", ENV_PROXY_TARGETS_HEAD_Z_MODE, default_mode)', source)
        self.assertIn("func proxy_targets_card_offset_rule(default_rule: Dictionary) -> Dictionary:", source)
        self.assertIn('proxy_targets_card_offset_rule', source)
        self.assertIn('resolve_float("proxy_targets_card_depth_scale"', source)
        self.assertIn('resolve_float("proxy_targets_card_depth_offset_m"', source)
        self.assertIn('resolve_float("proxy_targets_card_right_width_fraction"', source)
        self.assertIn('resolve_float("proxy_targets_card_right_angle_deg"', source)
        self.assertIn("func status_hud_visible(default_visible: bool) -> bool:", source)
        self.assertIn("func vst_camera_calibration(default_hfov_deg: float, default_vfov_deg: float) -> Dictionary:", source)

    def test_moving_card_routes_ws_config_through_options(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const SmartXROptionsScript := preload("res://scripts/smartxr_options.gd")', source)
        self.assertIn("var _options = SmartXROptionsScript.load_options()", source)
        # The control channel URL must no longer be hardwired at the call site.
        # (The peer call site lives in ws_transport.gd since M3 step 3; the
        # card resolves the URL through _options and passes it in.)
        self.assertNotIn("connect_to_url(WS_URL)", source)
        self.assertNotIn("connect_to(WS_URL)", source)
        self.assertIn("connect_to(_control_ws_url())", source)
        self.assertIn("return _options.control_ws_url(WS_URL)", source)
        self.assertIn("return _options.proxy_targets_ws_url(PROXY_TARGETS_WS_URL)", source)
        self.assertIn("return _options.proxy_targets_ws_enabled(PROXY_TARGETS_WS_ENABLED)", source)
        self.assertIn("return _options.proxy_targets_anchor_mode(PROXY_TARGETS_ANCHOR_MODE)", source)
        self.assertIn("return _options.proxy_targets_head_z_mode(PROXY_TARGETS_HEAD_Z_MODE)", source)
        self.assertIn("_options.proxy_targets_card_offset_rule(PROXY_TARGETS_CARD_OFFSET_RULE)", source)
        self.assertIn("_proxy_targets_card_adapter.set_default_offset_rule(_options.proxy_targets_card_offset_rule(PROXY_TARGETS_CARD_OFFSET_RULE))", source)
        self.assertIn("return _options.status_hud_visible(STATUS_HUD_VISIBLE)", source)
        self.assertIn("status_label.visible = _status_hud_visible()", source)
        self.assertIn(
            "var vst_calibration: Dictionary = _options.vst_camera_calibration(BBOX_HORIZONTAL_FOV_DEG, BBOX_VERTICAL_FOV_DEG)",
            source,
        )
        self.assertIn("_vst_capture.set_camera_calibration(", source)
        # Direct enable-flag checks must go through the options-backed helper.
        self.assertNotIn("if not PROXY_TARGETS_WS_ENABLED:", source)

    def test_options_are_documented(self):
        doc = DOC.read_text(encoding="utf-8")

        self.assertIn("smartxr_options.json", doc)
        self.assertIn("SMARTXR_CONTROL_WS_URL", doc)
        self.assertIn("PROXY_TARGETS_WS_URL", doc)
        self.assertIn("SMARTXR_PROXY_TARGETS_WS_ENABLED", doc)
        self.assertIn("SMARTXR_PROXY_TARGETS_ANCHOR_MODE", doc)
        self.assertIn("proxy_targets_anchor_mode", doc)
        self.assertIn("world_latched", doc)
        self.assertIn("SMARTXR_PROXY_TARGETS_HEAD_Z_MODE", doc)
        self.assertIn("proxy_targets_head_z_mode", doc)
        self.assertIn("positive_z_forward", doc)
        self.assertIn("config\\smartxr_options.json", doc)
        self.assertIn("proxy_targets_card_offset_rule", doc)
        self.assertIn("proxy_targets_card_depth_scale", doc)
        self.assertIn("proxy_targets_card_depth_offset_m", doc)
        self.assertIn("SMARTXR_PROXY_TARGETS_CARD_DEPTH_OFFSET_M", doc)
        self.assertIn("proxy_targets_card_right_angle_deg", doc)
        self.assertIn("SMARTXR_PROXY_TARGETS_CARD_RIGHT_ANGLE_DEG", doc)
        self.assertIn("SMARTXR_OPTIONS_PATH", doc)
        self.assertIn("SMARTXR_STATUS_HUD_VISIBLE", doc)
        self.assertIn("SMARTXR_VST_HORIZONTAL_FOV_DEG", doc)
        self.assertIn("SMARTXR_VST_FOCAL_LENGTH_X", doc)
        self.assertIn("principal_point_px", doc)
        self.assertIn("run_godot_smartxr_options_probe.ps1", doc)

    def test_repo_level_smartxr_options_config_is_editable(self):
        config = json.loads(REPO_CONFIG.read_text(encoding="utf-8"))

        self.assertEqual(config["proxy_targets_anchor_mode"], "world_latched")
        self.assertEqual(config["proxy_targets_head_z_mode"], "negative_z_forward")
        offset_rule = config["proxy_targets_card_offset_rule"]
        self.assertEqual(offset_rule["mode"], "depth_scaled_right_angle")
        self.assertEqual(offset_rule["depth_scale"], 1.3)
        self.assertEqual(offset_rule["depth_offset_m"], 2.0)
        self.assertEqual(offset_rule["right_angle_deg"], 15.0)
        self.assertEqual(offset_rule["up_m"], 0.0)

    def test_runtime_probe_and_runner_exist(self):
        probe = (ROOT / "godot-android" / "tests" / "script_only_smartxr_options_probe.gd").read_text(encoding="utf-8")
        runner = (ROOT / "tools" / "run_godot_smartxr_options_probe.ps1").read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        # No-project mode: scripts and paths are injected via env vars, and
        # quit() must happen in _process, not _initialize.
        self.assertIn('OS.get_environment("SMARTXR_OPTIONS_SCRIPT")', probe)
        self.assertIn("SMARTXR_OPTIONS_PROBE_STATUS_PATH", probe)
        self.assertIn("func _process(_delta: float) -> bool:", probe)
        self.assertIn("load_options_from(_config_path)", probe)
        self.assertIn("env_beats_config", probe)
        self.assertIn("env_proxy_anchor_mode", probe)
        self.assertIn("env_proxy_head_z_mode", probe)
        self.assertIn("config_card_offset_rule", probe)
        self.assertIn("env_card_offset_rule", probe)
        self.assertIn("SMARTXR_OPTIONS_PATH", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_OPTIONS_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
