from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "godot-android" / "scripts" / "target_source.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
CARD_RECEIVER = ROOT / "godot-android" / "scripts" / "card_receiver.gd"
VALIDATION_SCENE_BUILDER = ROOT / "godot-android" / "scripts" / "validation_scene_builder.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_target_source_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_target_source_probe.ps1"


class GodotTargetSourceTests(unittest.TestCase):
    def test_target_source_owns_vst_trackable_state_machine(self):
        source = SOURCE.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name TargetSource", source)
        self.assertNotIn("TargetSource.new()", source)
        self.assertNotIn(": TargetSource", source)
        self.assertIn("class TrackableTarget:", source)
        self.assertIn("class VSTTargetAdapter:", source)
        self.assertIn("class VSTTargetSource:", source)
        self.assertIn("class ProxyTargetsTargetSource:", source)
        self.assertIn('const TRACKABLE_STATE_TRACKED := "tracked"', source)
        self.assertIn('const TRACKABLE_SOURCE_VST := "vst"', source)
        self.assertIn("func update_target(target_id: String, transform: Transform3D, confidence: float, timestamp_ms: float) -> bool:", source)
        self.assertIn("func apply_proxy_targets_json(payload: String) -> bool:", source)
        self.assertIn("func apply_proxy_targets_message(message: Dictionary) -> bool:", source)
        self.assertIn("func set_on_message_parsed(on_message_parsed: Callable) -> void:", source)
        self.assertIn("func last_error() -> String:", source)
        self.assertIn("func advance(now_ms: float) -> void:", source)
        self.assertIn("func target_state() -> String:", source)
        self.assertIn("func target() -> TrackableTarget:", source)
        self.assertIn("func set_on_target_updated(on_target_updated: Callable) -> void:", source)
        self.assertIn("func set_on_target_lost(on_target_lost: Callable) -> void:", source)
        self.assertIn("velocity: Vector3", source)
        self.assertIn("_hold_last_pose", source)
        self.assertIn("_predict_pose", source)
        self.assertIn("_set_state(TRACKABLE_STATE_PREDICTED)", source)
        self.assertIn("_set_state(TRACKABLE_STATE_STALE)", source)
        self.assertIn("_set_state(TRACKABLE_STATE_LOST)", source)
        self.assertNotIn("preload(", source)
        self.assertNotIn("OS.get_environment", source)
        self.assertNotIn("get_tree()", source)

    def test_moving_card_wires_vst_target_source_boundary(self):
        card = SCRIPT.read_text(encoding="utf-8")
        receiver = CARD_RECEIVER.read_text(encoding="utf-8")
        builder = VALIDATION_SCENE_BUILDER.read_text(encoding="utf-8")

        self.assertIn('const TargetSourceScript := preload("res://scripts/target_source.gd")', card)
        self.assertIn("var _vst_target_source = null", card)
        self.assertIn("var _proxy_targets_target_source = null", card)
        self.assertIn("TargetSourceScript.VSTTargetSource.new(", card)
        self.assertIn("TargetSourceScript.ProxyTargetsTargetSource.new(", card)
        self.assertIn('"target_source": _proxy_targets_target_source', card)
        self.assertIn("_target_source.set_on_message_parsed(_on_message_parsed)", receiver)
        self.assertIn("_vst_target_source.set_on_target_updated(_on_vst_target_updated)", card)
        self.assertIn("_vst_target_source.set_on_target_lost(_on_vst_target_lost)", card)
        self.assertIn("_vst_target_source.update_target(target_id, transform, confidence, timestamp_ms)", card)
        self.assertIn("target_source.apply_proxy_targets_json(sample)", builder)
        self.assertIn("_target_source.apply_proxy_targets_json(payload)", receiver)
        self.assertIn("_target_source.last_error()", receiver)
        self.assertIn("_vst_target_source.advance(float(Time.get_ticks_msec()))", card)
        self.assertIn("if _vst_target_source.target_state() == TargetSourceScript.TRACKABLE_STATE_LOST:", card)
        self.assertIn("func _on_message_parsed(message: Dictionary) -> void:", receiver)
        self.assertIn("func _on_vst_target_updated(_target_id: String, _transform: Transform3D) -> void:", card)
        self.assertIn("func _on_vst_target_lost(_target_id: String) -> void:", card)
        self.assertNotIn("class TrackableTarget:", card)
        self.assertNotIn("class VSTTargetAdapter:", card)

    def test_runtime_probe_and_runner_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        self.assertIn('OS.get_environment("SMARTXR_TARGET_SOURCE_SCRIPT")', probe)
        self.assertIn("SMARTXR_TARGET_SOURCE_PROBE_STATUS_PATH", probe)
        self.assertIn("func _process(_delta: float) -> bool:", probe)
        self.assertIn("low_confidence_rejected", probe)
        self.assertIn("first_update_tracks", probe)
        self.assertIn("second_update_smooths_and_sets_velocity", probe)
        self.assertIn("advance_predicts", probe)
        self.assertIn("advance_stales", probe)
        self.assertIn("advance_loses", probe)
        self.assertIn("lost_callback_fired", probe)
        self.assertIn("proxy_source_rejects_invalid_json", probe)
        self.assertIn("proxy_source_applies_json_via_adapter", probe)
        self.assertIn("proxy_source_reports_apply_failed", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_TARGET_SOURCE_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
