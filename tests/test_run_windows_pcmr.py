from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_windows_pcmr.ps1"


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


if __name__ == "__main__":
    unittest.main()
