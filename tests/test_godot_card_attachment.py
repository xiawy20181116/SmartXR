from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ATTACHMENT = ROOT / "godot-android" / "scripts" / "card_attachment.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_card_attachment_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_card_attachment_probe.ps1"


class GodotCardAttachmentTests(unittest.TestCase):
    def test_card_attachment_owns_state_machine_and_offset_math(self):
        source = ATTACHMENT.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name CardAttachment", source)
        # No self-reference to the class_name: the script must stay loadable
        # in no-project (script-only) mode, like the other extracted
        # subsystems.
        self.assertNotIn("CardAttachment.new()", source)
        self.assertNotIn(": CardAttachment", source)
        # The fallback constants and the default offset rule moved here from
        # the card, values unchanged.
        self.assertIn('const TARGET_FALLBACK_HOLD_LAST_POSE := "hold_last_pose"', source)
        self.assertIn('const TARGET_FALLBACK_DETACH := "detach"', source)
        self.assertIn('const TARGET_FALLBACK_FADE_OUT := "fade_out"', source)
        self.assertIn("const TARGET_DEFAULT_OFFSET_RULE := {", source)
        self.assertIn('"mode": "front",', source)
        self.assertIn('"distance_m": 0.35,', source)
        self.assertIn('"fallback": TARGET_FALLBACK_HOLD_LAST_POSE,', source)
        # Bookkeeping + apply counter are owned here; the card reads them via
        # the snapshot-feeding getters.
        self.assertIn("var _attachments := {}", source)
        self.assertIn("var _apply_count := 0", source)
        self.assertIn("_apply_count += 1", source)
        self.assertIn("func attach(card_id: String, target_id: String, offset_rule = {}) -> bool:", source)
        self.assertIn("func detach(card_id: String) -> void:", source)
        self.assertIn("func update_attachments() -> void:", source)
        self.assertIn("func apply_fallback(attachment: Dictionary) -> void:", source)
        self.assertIn("func attachment_count() -> int:", source)
        self.assertIn("func has_attachment(card_id: String) -> bool:", source)
        self.assertIn("func get_attachment(card_id: String):", source)
        self.assertIn("func card_target_id(card_id: String) -> String:", source)
        self.assertIn("func card_resolved_position(card_id: String):", source)
        self.assertIn("func apply_count() -> int:", source)
        # Wiring follows the WSTransport Callable pattern: registry lookups,
        # the card anchor, and the two mode-transition hooks are injected.
        self.assertIn("func set_primary_card_id(card_id: String) -> void:", source)
        self.assertIn("func set_resolve_target(resolve_target: Callable) -> void:", source)
        self.assertIn("func set_card_anchor_provider(card_anchor_provider: Callable) -> void:", source)
        self.assertIn("func set_on_attachments_updated(on_attachments_updated: Callable) -> void:", source)
        self.assertIn("func set_on_all_detached(on_all_detached: Callable) -> void:", source)
        # The single-attachment fallback lookup (primary key first, else the
        # only entry) moved verbatim.
        self.assertIn("var attachment = _attachments.get(_primary_card_id)", source)
        self.assertIn("_attachments.values()[0]", source)
        self.assertIn("attachment[\"last_transform\"] = next_transform", source)
        # Dependency-free: no preloads, no env reads, no tree walks of its
        # own (the anchor and the registry arrive through Callables).
        self.assertNotIn("preload(", source)
        self.assertNotIn("OS.get_environment", source)
        self.assertNotIn("get_tree()", source)

    def test_moving_card_delegates_to_extracted_attachment(self):
        card = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const CardAttachmentScript := preload("res://scripts/card_attachment.gd")', card)
        self.assertIn("var _card_attachment = CardAttachmentScript.new()", card)
        # Wiring per ADR-4: the registry, anchor, and mode transitions stay
        # card-owned and are injected as Callables.
        self.assertIn("func _setup_card_attachment() -> void:", card)
        self.assertIn("_card_attachment.set_primary_card_id(CARD_ANCHOR_NAME)", card)
        self.assertIn("_card_attachment.set_resolve_target(_resolve_attachment_target)", card)
        self.assertIn("_card_attachment.set_card_anchor_provider(_get_card_anchor)", card)
        self.assertIn("_card_attachment.set_on_attachments_updated(_on_card_attachments_updated)", card)
        self.assertIn("_card_attachment.set_on_all_detached(_on_card_attachments_all_detached)", card)
        self.assertIn("return _target_registry.resolve(target_id)", card)
        # Public API unchanged; the card keeps _anchor_mode / _last_command
        # transitions around the subsystem calls.
        self.assertIn("if not _card_attachment.attach(card_id, target_id, offset_rule):", card)
        self.assertIn('_last_command = "attach_target:" + target_id', card)
        self.assertIn("_card_attachment.detach(card_id)", card)
        self.assertIn('if _anchor_mode == "target":', card)
        self.assertIn('_anchor_mode = "manual"', card)
        # VST interactions read the attachment through the subsystem.
        self.assertIn('_card_attachment.get_attachment(CARD_ANCHOR_NAME)', card)
        self.assertIn("_card_attachment.apply_fallback(attachment)", card)
        self.assertIn("_card_attachment.has_attachment(CARD_ANCHOR_NAME)", card)
        # The state machine and the offset math moved out of the card.
        self.assertNotIn("var _card_attachments :=", card)
        self.assertNotIn("func _update_target_attachments", card)
        self.assertNotIn("func _apply_target_fallback", card)
        self.assertNotIn("func _normalize_target_offset_rule", card)
        self.assertNotIn("func _target_offset_vector", card)
        self.assertNotIn("const TARGET_DEFAULT_OFFSET_RULE", card)
        # The VST offset rule keeps referencing the shared fallback constant.
        self.assertIn('"fallback": CardAttachmentScript.TARGET_FALLBACK_HOLD_LAST_POSE,', card)

    def test_runtime_probe_and_runner_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        # No-project mode: the script under test is injected via env vars, and
        # quit() must happen in _process, not _initialize.
        self.assertIn('OS.get_environment("SMARTXR_CARD_ATTACHMENT_SCRIPT")', probe)
        self.assertIn("SMARTXR_CARD_ATTACHMENT_PROBE_STATUS_PATH", probe)
        self.assertIn("func _process(_delta: float) -> bool:", probe)
        self.assertIn("attach_unknown_target_rejected", probe)
        self.assertIn("detach_fallback_transitions_to_manual", probe)
        self.assertIn("hold_restores_last_transform", probe)
        self.assertIn("fade_out_hides_anchor", probe)
        self.assertIn("world_space_ignores_target_rotation", probe)
        self.assertIn("target_space_rotates_offset", probe)
        self.assertIn("single_non_primary_attachment_drives_anchor", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_CARD_ATTACHMENT_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
