from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "godot-android" / "scripts" / "card_lifecycle.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_card_lifecycle_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_card_lifecycle_probe.ps1"


class GodotCardLifecycleTests(unittest.TestCase):
    def test_card_lifecycle_owns_c3_state_machine(self):
        source = LIFECYCLE.read_text(encoding="utf-8")

        # Pure data, script-only loadable (no nodes, no transport, no OS access).
        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name CardLifecycle", source)
        self.assertNotIn("CardLifecycle.new()", source)
        self.assertNotIn(": CardLifecycle", source)
        self.assertNotIn("OS.get_environment", source)
        self.assertNotIn("get_tree()", source)
        self.assertNotIn("preload(", source)

        # C3 envelope constants mirror smartxr/card_lifecycle_schema.py.
        self.assertIn('const MESSAGE_TYPE := "card_lifecycle"', source)
        self.assertIn("const SCHEMA_VERSION := 1", source)
        self.assertIn('const DETACHED := "detached"', source)
        self.assertIn('const ALLOWED_COMMANDS := ["attach", "update", "detach"]', source)
        self.assertIn('const ALLOWED_CARD_STATES := ["appear", "expand", "contract", "disappear"]', source)
        self.assertIn("const COMMAND_CARD_STATES := {", source)
        self.assertIn("const ALLOWED_TRANSITIONS := {", source)
        self.assertIn("const DEFAULT_ANIMATION_MS := {", source)

        # The eight legal edges, including the implicit detached null state.
        for edge in (
            "detached->appear",
            "appear->expand",
            "expand->contract",
            "contract->expand",
            "appear->disappear",
            "expand->disappear",
            "contract->disappear",
            "disappear->detached",
        ):
            self.assertIn(f'"{edge}": true,', source)

        # Default per-state durations from the contract.
        self.assertIn('"appear": 250,', source)
        self.assertIn('"expand": 200,', source)
        self.assertIn('"contract": 200,', source)
        self.assertIn('"disappear": 300,', source)

        # State-machine + validation API surface.
        self.assertIn("func current_state(card_id: String) -> String:", source)
        self.assertIn("func consume(message) -> bool:", source)
        self.assertIn("func consume_json(payload: String) -> bool:", source)
        self.assertIn("func validate_message(message) -> Array:", source)
        self.assertIn("func resolve_duration_ms(command: Dictionary) -> int:", source)
        self.assertIn("func commands_accepted() -> int:", source)
        self.assertIn("func commands_rejected() -> int:", source)
        self.assertIn("func messages_rejected() -> int:", source)
        self.assertIn("func last_error() -> String:", source)

        # The transition guard and the schema command/card_state coupling.
        self.assertIn('ALLOWED_TRANSITIONS.has(current + "->" + target)', source)
        self.assertIn("COMMAND_CARD_STATES.has(verb)", source)
        # Illegal transitions are rejected, legal siblings still applied.
        self.assertIn("_commands_rejected += 1", source)
        self.assertIn("_commands_accepted += 1", source)
        self.assertIn("DETACHED if target == \"disappear\" else target", source)

    def test_runtime_probe_and_runner_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        self.assertIn('OS.get_environment("SMARTXR_CARD_LIFECYCLE_SCRIPT")', probe)
        self.assertIn("SMARTXR_CARD_LIFECYCLE_PROBE_STATUS_PATH", probe)
        self.assertIn("func _process(_delta: float) -> bool:", probe)
        # The contract the probe locks.
        self.assertIn("canonical_message_accepted", probe)
        self.assertIn("canonical_accepts_five_commands", probe)
        self.assertIn("canonical_ends_detached", probe)
        self.assertIn("can_reattach_after_disappear", probe)
        self.assertIn("update_before_attach_rejected", probe)
        self.assertIn("appear_to_contract_rejected", probe)
        self.assertIn("attach_expand_mismatch_rejected", probe)
        self.assertIn("unknown_command_rejected", probe)
        self.assertIn("transition_table_has_8_edges", probe)
        self.assertIn("default_durations_match_contract", probe)
        self.assertIn("resolve_override_duration", probe)

        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_CARD_LIFECYCLE_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
