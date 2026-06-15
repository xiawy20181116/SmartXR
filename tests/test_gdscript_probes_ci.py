from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DOC = ROOT / "docs" / "gdscript_probes_ci.md"


class GDScriptProbesCITests(unittest.TestCase):
    def test_workflow_has_manual_self_hosted_gdscript_probe_job(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("gdscript-probes:", workflow)
        self.assertIn("name: GDScript probes", workflow)
        self.assertIn("runs-on: self-hosted", workflow)
        self.assertIn("if: github.event_name == 'workflow_dispatch'", workflow)
        self.assertIn("GODOT_BIN:", workflow)
        self.assertIn("tools/run_godot_smartxr_options_probe.ps1", workflow)
        self.assertIn("tools/run_godot_status_hud_probe.ps1", workflow)
        self.assertIn("tools/run_godot_target_registry_probe.ps1", workflow)
        self.assertIn("tools/run_godot_ws_transport_probe.ps1", workflow)
        self.assertIn("tools/run_godot_card_attachment_probe.ps1", workflow)
        self.assertIn("tools/run_godot_xr_bootstrap_probe.ps1", workflow)
        self.assertIn("tools/run_godot_target_source_probe.ps1", workflow)
        self.assertIn("tools/run_godot_vst_debug_ui_probe.ps1", workflow)
        self.assertIn("tools/run_godot_bbox_math_probe.ps1", workflow)
        self.assertNotIn("--path godot-android", workflow)
        self.assertNotIn("--path ./godot-android", workflow)

    def test_self_hosted_runner_docs_cover_required_environment(self):
        doc = DOC.read_text(encoding="utf-8")

        self.assertIn("Godot 4.6.2", doc)
        self.assertIn("GODOT_BIN", doc)
        self.assertIn("E:\\xia\\Godot_v4.6.2-stable_win64.exe\\Godot_v4.6.2-stable_win64.exe", doc)
        self.assertIn("workflow_dispatch", doc)
        self.assertIn("self-hosted", doc)
        self.assertIn("no-project", doc)


if __name__ == "__main__":
    unittest.main()
