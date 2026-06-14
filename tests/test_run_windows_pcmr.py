from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_windows_pcmr.ps1"
LIVE_RUNNER = ROOT / "tools" / "run_windows_pcmr_proxy_targets_live.ps1"
VISUAL_RUNNER = ROOT / "tools" / "run_windows_pcmr_overlay_visual_check.ps1"
VISUAL_DOC = ROOT / "docs" / "pcmr_overlay_visual_check.md"


class WindowsPcmrRunnerTests(unittest.TestCase):
    def test_runner_can_validate_real_proxy_targets_consumer(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("[switch]$ValidateProxyTargets", source)
        self.assertIn("[switch]$UseAntmanPassthroughOverlay", source)
        self.assertIn('[string]$ProxyTargetsWsUrl = "ws://127.0.0.1:8766/proxy_targets"', source)
        self.assertIn("[double]$ProxyTargetsTimeoutSeconds = 15.0", source)
        self.assertIn("PROXY_TARGETS_WS_URL", source)
        self.assertIn("SMARTXR_USE_PASSTHROUGH_OVERLAY", source)
        self.assertIn("passthrough_overlay_status.json", source)
        self.assertIn("proxy_targets_live_status.json", source)
        self.assertIn("validate_proxy_targets_live_status.py", source)
        self.assertIn("--require", source)
        self.assertIn("attached", source)
        self.assertIn("SmartXR-PCMR proxy_targets live validation", source)
        self.assertIn("SmartXR-PCMR Antman passthrough overlay", source)
        self.assertIn("Restore-EnvVar -Name \"SMARTXR_USE_PASSTHROUGH_OVERLAY\"", source)
        self.assertIn("Restore-EnvVar -Name \"PROXY_TARGETS_WS_URL\"", source)

    def test_runner_copies_proxy_targets_status_into_work_dir(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn('$WorkDirStatusFile = Join-Path $WorkDir "proxy_targets_live_status.json"', source)
        self.assertIn("Copy-Item -LiteralPath $StatusFile -Destination $WorkDirStatusFile -Force", source)
        self.assertIn("Status JSON copy:", source)

    def test_live_runner_starts_isolated_fake_publisher_before_pcmr_validation(self):
        self.assertTrue(LIVE_RUNNER.exists())
        source = LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("fake_proxy_targets_publisher.py", source)
        self.assertIn("run_windows_pcmr.ps1", source)
        self.assertIn("[int]$Port = 8767", source)
        self.assertIn("-ProxyTargetsWsUrl", source)
        self.assertIn("ws://${HostName}:${Port}/proxy_targets", source)
        self.assertIn("-ValidateProxyTargets", source)
        self.assertIn("Stop-ChildProcess -Process $PublisherProcess", source)

    def test_overlay_visual_check_runner_holds_godot_open_for_manual_inspection(self):
        self.assertTrue(VISUAL_RUNNER.exists())
        source = VISUAL_RUNNER.read_text(encoding="utf-8")

        self.assertIn("fake_proxy_targets_publisher.py", source)
        self.assertIn("[int]$Port = 8767", source)
        self.assertIn("ws://${HostName}:${Port}/proxy_targets", source)
        self.assertIn("set_gxr_extension.ps1", source)
        self.assertIn("& $GxrExtensionSwitch -Mode disable -ProjectDir $ProjectDir", source)
        self.assertIn("& $GxrExtensionSwitch -Mode enable -ProjectDir $ProjectDir", source)
        self.assertIn('$env:PROXY_TARGETS_WS_URL = $ProxyTargetsWsUrl', source)
        self.assertIn('$env:SMARTXR_USE_PASSTHROUGH_OVERLAY = "1"', source)
        self.assertIn("& $GodotExe --path $ProjectDir", source)
        self.assertNotIn("-ValidateProxyTargets", source)
        self.assertIn("Stop-ChildProcess -Process $PublisherProcess", source)

    def test_overlay_visual_check_runner_is_documented(self):
        self.assertTrue(VISUAL_DOC.exists())
        source = VISUAL_DOC.read_text(encoding="utf-8")

        self.assertIn("run_windows_pcmr_overlay_visual_check.ps1", source)
        self.assertIn("run_windows_pcmr_proxy_targets_live.ps1", source)
        self.assertIn("holds Godot open", source)
        self.assertIn("PASSTHROUGH OVERLAY", source)
        self.assertIn("fake proxy_targets publisher", source)


if __name__ == "__main__":
    unittest.main()
