from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STATUS_HUD = ROOT / "godot-android" / "scripts" / "status_hud.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_status_hud_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_status_hud_probe.ps1"


class GodotStatusHudTests(unittest.TestCase):
    def test_status_hud_renders_label_and_writes_status_files(self):
        source = STATUS_HUD.read_text(encoding="utf-8")

        self.assertIn("extends Node", source)
        self.assertIn("class_name StatusHud", source)
        # No self-reference to the class_name: the script must stay loadable
        # in no-project (script-only) mode, like smartxr_options.gd.
        self.assertNotIn("StatusHud.new()", source)
        self.assertNotIn(": StatusHud", source)
        self.assertIn('const PROXY_TARGETS_STATUS_RES := "user://proxy_targets_live_status.json"', source)
        self.assertIn('const PASSTHROUGH_OVERLAY_STATUS_RES := "user://passthrough_overlay_status.json"', source)
        self.assertIn("const STATUS_FILE_WRITE_INTERVAL_SECONDS := 0.25", source)
        # Paths are overridable vars so the script-only probe can redirect
        # writes to a temp directory.
        self.assertIn("var proxy_targets_status_path: String = PROXY_TARGETS_STATUS_RES", source)
        self.assertIn("var passthrough_overlay_status_path: String = PASSTHROUGH_OVERLAY_STATUS_RES", source)
        self.assertIn("func build_status_label(parent: Node3D) -> Label3D:", source)
        self.assertIn('"MeshCardStatus"', source)
        self.assertIn("func update_status_label(snapshot: Dictionary) -> void:", source)
        self.assertIn("func write_status_files(snapshot: Dictionary, delta: float) -> void:", source)
        self.assertIn("static func sanitize_status_text(value: String) -> String:", source)
        self.assertIn("func _format_vec3(value: Vector3) -> String:", source)
        self.assertIn("func _format_vec3_or_na(value) -> String:", source)
        self.assertIn("FileAccess.open(proxy_targets_status_path, FileAccess.WRITE)", source)
        self.assertIn("FileAccess.open(passthrough_overlay_status_path, FileAccess.WRITE)", source)
        # StatusHud only formats and writes; it must not resolve other nodes
        # or read configuration itself.
        self.assertNotIn("get_node", source)
        self.assertNotIn("OS.get_environment", source)

    def test_moving_card_feeds_status_hud_with_a_per_frame_snapshot(self):
        card = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const StatusHudScript := preload("res://scripts/status_hud.gd")', card)
        self.assertIn("var _status_hud: Node = null", card)
        self.assertIn("func _build_status_hud() -> void:", card)
        self.assertIn("_status_hud.build_status_label(_card_anchor)", card)
        self.assertIn("func _build_status_snapshot() -> Dictionary:", card)
        self.assertIn("func _update_status_hud(delta: float) -> void:", card)
        self.assertIn("_update_status_hud(delta)", card)
        self.assertIn("_status_hud.update_status_label(snapshot)", card)
        self.assertIn("_status_hud.write_status_files(snapshot, delta)", card)
        # The card no longer formats or writes status output itself.
        self.assertNotIn("func _format_vec3", card)
        self.assertNotIn("func _update_status_label", card)
        self.assertNotIn("user://proxy_targets_live_status.json", card)
        self.assertNotIn("user://passthrough_overlay_status.json", card)
        self.assertNotIn("var _status_label", card)

    def test_runtime_probe_and_runner_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        # No-project mode: scripts and paths are injected via env vars, and
        # quit() must happen in _process, not _initialize.
        self.assertIn('OS.get_environment("SMARTXR_STATUS_HUD_SCRIPT")', probe)
        self.assertIn("SMARTXR_STATUS_HUD_PROBE_STATUS_PATH", probe)
        self.assertIn("SMARTXR_STATUS_HUD_PROBE_WORK_DIR", probe)
        self.assertIn("func _process(_delta: float) -> bool:", probe)
        self.assertIn("throttle_skips_below_interval", probe)
        self.assertIn("sanitize_status_text", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_STATUS_HUD_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
