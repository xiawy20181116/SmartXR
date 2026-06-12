from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ATTACHMENT = ROOT / "godot-android" / "scripts" / "card_attachment.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_card_attachment_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_card_attachment_probe.ps1"


class GodotCardAttachmentTests(unittest.TestCase):
    def test_card_attachment_owns_store_fallbacks_and_offset_math(self):
        source = ATTACHMENT.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name CardAttachment", source)
        # No self-reference to the class_name: the script must stay loadable
        # in no-project (script-only) mode, like the other extracted
        # subsystem scripts.
        self.assertNotIn("CardAttachment.new()", source)
        self.assertNotIn(": CardAttachment", source)
        # The fallback names and the default offset rule moved here from the
        # card.
        self.assertIn('const TARGET_FALLBACK_HOLD_LAST_POSE := "hold_last_pose"', source)
        self.assertIn('const TARGET_FALLBACK_DETACH := "detach"', source)
        self.assertIn('const TARGET_FALLBACK_FADE_OUT := "fade_out"', source)
        self.assertIn("const DEFAULT_OFFSET_RULE := {", source)
        self.assertIn('"distance_m": 0.35,', source)
        self.assertIn("var _attachments := {}", source)
        # Lifecycle + per-frame pass + fallback state machine.
        self.assertIn("func attach(card_id: String, target_id: String, offset_rule = {}) -> bool:", source)
        self.assertIn("func detach(card_id: String) -> void:", source)
        self.assertIn("func update_attachments(card_anchor: Node3D, primary_card_id: String) -> bool:", source)
        self.assertIn("func apply_fallback(attachment: Dictionary, card_anchor: Node3D, primary_card_id: String) -> void:", source)
        self.assertIn("adapter.is_available()", source)
        self.assertIn('attachment["last_transform"] = next_transform', source)
        # Read-only accessors feeding the card's status snapshot.
        self.assertIn("func size() -> int:", source)
        self.assertIn("func is_empty() -> bool:", source)
        self.assertIn("func has_attachment(card_id: String) -> bool:", source)
        self.assertIn("func attached_target_id(card_id: String) -> String:", source)
        self.assertIn("func last_resolved_position(card_id: String):", source)
        # The offset-rule math, moved verbatim from the card (static so the
        # probe can exercise it without wiring an instance).
        self.assertIn("static func normalize_offset_rule(offset_rule) -> Dictionary:", source)
        self.assertIn("static func offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:", source)
        self.assertIn("static func world_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:", source)
        self.assertIn("static func local_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:", source)
        self.assertIn("static func offset_vector(offset_rule) -> Vector3:", source)
        self.assertIn('"right_top", "top_right":', source)
        # The subsystem is dependency-free: target lookup and the detach
        # route come in as Callables from the card, and it never resolves
        # configuration or walks the tree on its own.
        self.assertIn("func set_resolver(resolver: Callable) -> void:", source)
        self.assertIn("func set_on_applied(on_applied: Callable) -> void:", source)
        self.assertIn("func set_on_detach_card(on_detach_card: Callable) -> void:", source)
        self.assertNotIn("preload(", source)
        self.assertNotIn("OS.get_environment", source)
        self.assertNotIn("get_tree()", source)

    def test_moving_card_delegates_to_extracted_attachment_subsystem(self):
        card = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const CardAttachmentScript := preload("res://scripts/card_attachment.gd")', card)
        self.assertIn("var _card_attachment = CardAttachmentScript.new()", card)
        # Wiring: target lookup stays in target_registry.gd, the apply
        # counter and the detach-fallback mode flip stay card-side (ADR-4).
        self.assertIn("func _setup_card_attachment() -> void:", card)
        self.assertIn("_card_attachment.set_resolver(_target_registry.resolve)", card)
        self.assertIn("_card_attachment.set_on_applied(_on_card_attachment_applied)", card)
        self.assertIn("_card_attachment.set_on_detach_card(detach_card)", card)
        self.assertIn("_setup_card_attachment()", card)
        # Public API stays on the card and delegates.
        self.assertIn("if not _card_attachment.attach(card_id, target_id, offset_rule):", card)
        self.assertIn("_card_attachment.detach(card_id)", card)
        self.assertIn("if not _card_attachment.update_attachments(_card_anchor, CARD_ANCHOR_NAME):", card)
        self.assertIn("_card_attachment.has_attachment(CARD_ANCHOR_NAME)", card)
        self.assertIn("_card_attachment.attached_target_id(CARD_ANCHOR_NAME)", card)
        self.assertIn("_card_attachment.last_resolved_position(CARD_ANCHOR_NAME)", card)
        self.assertIn("_card_attachment.apply_fallback(attachment, _card_anchor, CARD_ANCHOR_NAME)", card)
        # The VST offset rule keeps its fallback name through the subsystem
        # const instead of a card-local copy.
        self.assertIn('"fallback": CardAttachmentScript.TARGET_FALLBACK_HOLD_LAST_POSE,', card)
        # The store and the moved bodies are gone from the card.
        self.assertNotIn("var _card_attachments := {}", card)
        self.assertNotIn("func _apply_target_fallback", card)
        self.assertNotIn("func _normalize_target_offset_rule", card)
        self.assertNotIn("func _target_offset_transform", card)
        self.assertNotIn("func _target_world_offset_transform", card)
        self.assertNotIn("func _target_local_offset_transform", card)
        self.assertNotIn("func _target_offset_vector", card)
        self.assertNotIn("const TARGET_DEFAULT_OFFSET_RULE", card)

    def test_runtime_probe_and_runner_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        # No-project mode: the script under test is injected via env vars, and
        # quit() must happen in _process, not _initialize.
        self.assertIn('OS.get_environment("SMARTXR_CARD_ATTACHMENT_SCRIPT")', probe)
        self.assertIn("SMARTXR_CARD_ATTACHMENT_PROBE_STATUS_PATH", probe)
        self.assertIn("func _process(_delta: float) -> bool:", probe)
        # The contract surface the issue asks for: lifecycle, both offset
        # modes/spaces, every fallback against a missing target, defaults.
        self.assertIn("attach_unknown_target_rejected", probe)
        self.assertIn("attach_default_rule_when_omitted", probe)
        self.assertIn("offset_vector_right_top", probe)
        self.assertIn("offset_vector_front_default", probe)
        self.assertIn("world_offset_ignores_rotation", probe)
        self.assertIn("local_offset_follows_rotation", probe)
        self.assertIn("offset_transform_target_space_local", probe)
        self.assertIn("fallback_hold_restores_last_pose", probe)
        self.assertIn("fallback_fade_out_hides", probe)
        self.assertIn("fallback_detach_empties_store", probe)
        self.assertIn("fallback_detach_routes_callable", probe)
        self.assertIn("fallback_missing_target_holds", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_CARD_ATTACHMENT_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
