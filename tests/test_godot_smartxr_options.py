from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
OPTIONS = ROOT / "godot-android" / "scripts" / "smartxr_options.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
DOC = ROOT / "docs" / "smartxr_options.md"


class GodotSmartXROptionsTests(unittest.TestCase):
    def test_options_class_exists_with_config_file_and_env_resolution(self):
        source = OPTIONS.read_text(encoding="utf-8")

        self.assertIn("class_name SmartXROptions", source)
        self.assertIn('const CONFIG_RES := "user://smartxr_options.json"', source)
        # Untyped static constructors on purpose: self-referencing the
        # class_name breaks compilation in no-project (script-only) mode.
        self.assertIn("static func load_options():", source)
        self.assertIn("static func load_options_from(config_path: String):", source)
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
        self.assertIn("func control_ws_url(default_url: String) -> String:", source)
        self.assertIn("func proxy_targets_ws_url(default_url: String) -> String:", source)
        self.assertIn("func proxy_targets_ws_enabled(default_enabled: bool) -> bool:", source)

    def test_moving_card_routes_ws_config_through_options(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const SmartXROptionsScript := preload("res://scripts/smartxr_options.gd")', source)
        self.assertIn("var _options = SmartXROptionsScript.load_options()", source)
        # The control channel URL must no longer be hardwired at the call site.
        self.assertNotIn("connect_to_url(WS_URL)", source)
        self.assertIn("connect_to_url(_control_ws_url())", source)
        self.assertIn("return _options.control_ws_url(WS_URL)", source)
        self.assertIn("return _options.proxy_targets_ws_url(PROXY_TARGETS_WS_URL)", source)
        self.assertIn("return _options.proxy_targets_ws_enabled(PROXY_TARGETS_WS_ENABLED)", source)
        # Direct enable-flag checks must go through the options-backed helper.
        self.assertNotIn("if not PROXY_TARGETS_WS_ENABLED:", source)

    def test_options_are_documented(self):
        doc = DOC.read_text(encoding="utf-8")

        self.assertIn("smartxr_options.json", doc)
        self.assertIn("SMARTXR_CONTROL_WS_URL", doc)
        self.assertIn("PROXY_TARGETS_WS_URL", doc)
        self.assertIn("SMARTXR_PROXY_TARGETS_WS_ENABLED", doc)
        self.assertIn("run_godot_smartxr_options_probe.ps1", doc)

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
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_OPTIONS_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
