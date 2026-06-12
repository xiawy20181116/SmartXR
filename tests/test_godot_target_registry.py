from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "godot-android" / "scripts" / "target_registry.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_target_registry_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_target_registry_probe.ps1"


class GodotTargetRegistryTests(unittest.TestCase):
    def test_target_registry_owns_bookkeeping_and_node_adapter(self):
        source = REGISTRY.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name TargetRegistry", source)
        # No self-reference to the class_name: the script must stay loadable
        # in no-project (script-only) mode, like smartxr_options.gd and
        # status_hud.gd.
        self.assertNotIn("TargetRegistry.new()", source)
        self.assertNotIn(": TargetRegistry", source)
        self.assertIn("class Node3DTargetAdapter:", source)
        self.assertIn("func _init(root: Node, node_or_path) -> void:", source)
        self.assertIn("func get_node3d() -> Node3D:", source)
        self.assertIn("func is_available() -> bool:", source)
        self.assertIn("func get_global_transform() -> Transform3D:", source)
        self.assertIn("return Transform3D.IDENTITY", source)
        self.assertIn("var _targets := {}", source)
        self.assertIn("func register(target_id: String, adapter: Node3DTargetAdapter) -> bool:", source)
        self.assertIn("func unregister(target_id: String) -> void:", source)
        self.assertIn("func resolve(target_id: String) -> Node3DTargetAdapter:", source)
        # Adapters guard against freed nodes and dangling paths.
        self.assertIn("is_instance_valid(_root)", source)
        self.assertIn("is_instance_valid(_node)", source)
        self.assertIn("get_node_or_null(_path)", source)
        # The registry is dependency-free: it resolves no configuration, loads
        # no sibling scripts, and never walks the tree on its own (the card
        # passes the lookup root into each adapter).
        self.assertNotIn("preload(", source)
        self.assertNotIn("OS.get_environment", source)
        self.assertNotIn("get_tree()", source)

    def test_moving_card_delegates_to_extracted_registry(self):
        card = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const TargetRegistryScript := preload("res://scripts/target_registry.gd")', card)
        self.assertIn("var _target_registry = TargetRegistryScript.new()", card)
        self.assertIn(
            "return bool(_target_registry.register(target_id, TargetRegistryScript.Node3DTargetAdapter.new(self, node_or_path)))",
            card,
        )
        self.assertIn("_target_registry.unregister(target_id)", card)
        # Since M3 step 4 (YAN-77) the card resolves targets for attachments
        # through the CardAttachment resolver wiring; lookup still goes
        # through this registry.
        self.assertIn("_card_attachment.set_resolver(_target_registry.resolve)", card)
        # The inner classes moved out of the card.
        self.assertNotIn("class TargetRegistry:", card)
        self.assertNotIn("class Node3DTargetAdapter:", card)
        # TrackableTarget / VSTTargetAdapter stay in the card for now: they
        # belong to the target-source subsystem (M4), not the registry.
        self.assertIn("class TrackableTarget:", card)
        self.assertIn("class VSTTargetAdapter:", card)

    def test_runtime_probe_and_runner_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        # No-project mode: the script under test is injected via env vars, and
        # quit() must happen in _process, not _initialize.
        self.assertIn('OS.get_environment("SMARTXR_TARGET_REGISTRY_SCRIPT")', probe)
        self.assertIn("SMARTXR_TARGET_REGISTRY_PROBE_STATUS_PATH", probe)
        self.assertIn("func _process(_delta: float) -> bool:", probe)
        self.assertIn("register_empty_id_rejected", probe)
        self.assertIn("freed_node_unavailable", probe)
        self.assertIn("nodepath_adapter_tracks_moves", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_TARGET_REGISTRY_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
