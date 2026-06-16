from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "godot-android" / "scripts" / "validation_scene_builder.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_validation_scene_builder_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_validation_scene_builder_probe.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DOC = ROOT / "docs" / "gdscript_probes_ci.md"


class GodotValidationSceneBuilderTests(unittest.TestCase):
    def test_builder_is_dependency_free_scene_builder(self):
        source = BUILDER.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name ValidationSceneBuilder", source)
        self.assertIn("func build_debug_target_marker(parent: Node, existing_marker, config: Dictionary, register_target: Callable, attach_card: Callable) -> Dictionary:", source)
        self.assertIn("func update_debug_target_marker(marker, elapsed_seconds: float, delta: float, config: Dictionary) -> float:", source)
        self.assertIn("func build_proxy_targets_validation(parent: Node, wrapper: Node, camera: Node, consumer_factory: Callable, adapter_factory: Callable, target_source_factory: Callable, sample_res: String) -> Dictionary:", source)
        self.assertIn("func apply_proxy_targets_sample(target_source, sample_res: String) -> String:", source)
        self.assertIn("BoxMesh.new()", source)
        self.assertIn('marker.name = str(config.get("marker_name", "MovingTargetMarker"))', source)
        self.assertIn('consumer.name = "ProxyTargetsConsumer"', source)
        self.assertIn('adapter.name = "ProxyTargetsCardAdapter"', source)
        self.assertIn("adapter.bind(consumer, wrapper)", source)
        self.assertIn("target_source_factory.call(adapter)", source)
        self.assertNotIn("preload(", source)
        self.assertNotIn("OS.get_environment", source)
        self.assertNotIn("get_tree()", source)
        self.assertNotIn("ValidationSceneBuilder.new()", source)
        self.assertNotIn(": ValidationSceneBuilder", source)

    def test_moving_card_delegates_validation_scene_construction(self):
        card = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const ValidationSceneBuilderScript := preload("res://scripts/validation_scene_builder.gd")', card)
        self.assertIn("var _validation_scene_builder = ValidationSceneBuilderScript.new()", card)
        self.assertIn("_validation_scene_builder.build_debug_target_marker(", card)
        self.assertIn("_validation_scene_builder.update_debug_target_marker(", card)
        self.assertIn("_validation_scene_builder.build_proxy_targets_validation(", card)
        self.assertIn("var consumer_factory := func():", card)
        self.assertIn("var adapter_factory := func():", card)
        self.assertIn("var target_source_factory := func(adapter):", card)
        self.assertIn("_proxy_targets_target_source.set_on_message_parsed(_on_proxy_targets_message_parsed)", card)
        self.assertNotIn("BoxMesh.new()", card)
        self.assertNotIn('marker.name = "MovingTargetMarker"', card)
        self.assertNotIn("_proxy_targets_card_adapter.bind(_proxy_targets_consumer, self)", card)
        self.assertNotIn("_proxy_targets_target_source.apply_proxy_targets_json(sample)", card)

    def test_runtime_probe_runner_and_ci_docs_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        doc = DOC.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        self.assertIn('OS.get_environment("SMARTXR_VALIDATION_SCENE_BUILDER_SCRIPT")', probe)
        self.assertIn("SMARTXR_VALIDATION_SCENE_BUILDER_PROBE_STATUS_PATH", probe)
        self.assertIn("build_debug_marker_invokes_public_hooks", probe)
        self.assertIn("update_debug_marker_moves_marker", probe)
        self.assertIn("build_proxy_validation_wires_fake_nodes", probe)
        self.assertIn("sample_missing_sets_command", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_VALIDATION_SCENE_BUILDER_SCRIPT", runner)
        self.assertIn("tools/run_godot_validation_scene_builder_probe.ps1", workflow)
        self.assertIn("tools/run_godot_validation_scene_builder_probe.ps1", doc)


if __name__ == "__main__":
    unittest.main()
