from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_windows_pcmr.ps1"
LIVE_RUNNER = ROOT / "tools" / "run_windows_pcmr_proxy_targets_live.ps1"
STEREO_LIVE_RUNNER = ROOT / "tools" / "run_windows_pcmr_stereo_proxy_targets_live.ps1"
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
        self.assertIn("SMARTXR_STATUS_HUD_VISIBLE", source)
        self.assertIn("passthrough_overlay_status.json", source)
        self.assertIn("proxy_targets_live_status.json", source)
        self.assertIn("validate_proxy_targets_live_status.py", source)
        self.assertIn("--require", source)
        self.assertIn("attached", source)
        self.assertIn("SmartXR-PCMR proxy_targets live validation", source)
        self.assertIn("SmartXR-PCMR Antman passthrough overlay", source)
        self.assertIn("Restore-EnvVar -Name \"SMARTXR_USE_PASSTHROUGH_OVERLAY\"", source)
        self.assertIn("Restore-EnvVar -Name \"SMARTXR_STATUS_HUD_VISIBLE\"", source)
        self.assertIn("Restore-EnvVar -Name \"PROXY_TARGETS_WS_URL\"", source)

    def test_validate_proxy_targets_hides_in_headset_status_hud(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn('if ($ValidateProxyTargets -and [string]::IsNullOrWhiteSpace($env:SMARTXR_STATUS_HUD_VISIBLE)) {', source)
        self.assertIn('$env:SMARTXR_STATUS_HUD_VISIBLE = "0"', source)
        self.assertNotIn('if ($ValidateProxyTargets) {\n        $env:SMARTXR_STATUS_HUD_VISIBLE = "0"\n    }', source)

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

    def test_stereo_live_runner_launches_sender_receiver_and_monitor_windows(self):
        self.assertTrue(STEREO_LIVE_RUNNER.exists())
        source = STEREO_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("antman_vst_stereo_proxy_targets_live_publisher.py", source)
        self.assertIn("run_windows_pcmr.ps1", source)
        self.assertIn("run_proxy_targets_live_monitor.ps1", source)
        self.assertIn("validate_proxy_targets_end_to_end_health.py", source)
        self.assertIn("Start-VisiblePowerShellWindow", source)
        self.assertIn('Open-RunnerTab -WindowName $WindowName -Title "SmartXR stereo sender"', source)
        self.assertIn('Open-RunnerTab -WindowName $WindowName -Title "SmartXR PCMR receiver"', source)
        self.assertIn('Open-RunnerTab -WindowName $WindowName -Title "SmartXR proxy_targets monitor"', source)
        self.assertIn("WindowStyle Normal", source)
        self.assertIn("receiver waits for sender_ready", source)
        self.assertIn("ValidateProxyTargets = `$true", source)
        self.assertIn("ProxyTargetsWsUrl = $WsUrlLiteral", source)
        self.assertIn("ws://${HostName}:${Port}/proxy_targets", source)
        self.assertIn("depth_confidence=low", source)

    def test_stereo_live_runner_uses_antman_stack_style_tabs_and_readiness_gates(self):
        self.assertTrue(STEREO_LIVE_RUNNER.exists())
        source = STEREO_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("Open-RunnerTab", source)
        self.assertIn("wt.exe -w $WindowName new-tab", source)
        self.assertIn("Start-VisiblePowerShellWindow", source)
        self.assertIn("Wait-ForLogText", source)
        self.assertIn("proxy_targets live publisher listening", source)
        self.assertIn("sent stereo seq=", source)
        self.assertIn("receiver waits for sender_ready", source)
        self.assertIn("monitor waits for sender_ready", source)
        self.assertIn("sender_ready.txt", source)
        self.assertIn("[double]$SenderReadyTimeoutSeconds = 45.0", source)
        self.assertIn("Get-LogTail", source)
        self.assertIn("Sender log tail:", source)
        self.assertIn("not found yet", source)
        self.assertNotIn("Start-Sleep -Seconds 1", source)

    def test_stereo_live_runner_generates_argument_arrays_not_fragile_backtick_lines(self):
        self.assertTrue(STEREO_LIVE_RUNNER.exists())
        source = STEREO_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("$PublisherArgs = @(", source)
        self.assertIn("& $PythonExeLiteral @PublisherArgs", source)
        self.assertIn("$ArgsList = @{", source)
        self.assertIn("GodotExe = $GodotExeLiteral", source)
        self.assertIn("ValidateProxyTargets = `$true", source)
        self.assertIn("ProxyTargetsWsUrl = $WsUrlLiteral", source)
        self.assertIn("ProxyTargetsTimeoutSeconds = $ProxyTargetsTimeoutSeconds", source)
        self.assertIn("$MonitorArgs = @{", source)
        self.assertIn("$MonitorArgsList = @(", source)
        self.assertIn("& powershell.exe @MonitorArgsList", source)
        self.assertIn("Url = $WsUrlLiteral", source)
        self.assertIn("MinPackets = $MonitorMinPackets", source)
        self.assertIn("TimeoutSeconds = $MonitorTimeoutSeconds", source)
        self.assertNotIn("& $PythonExeLiteral $PublisherLiteral `", source)
        self.assertNotIn("& $MonitorRunnerLiteral `", source)

    def test_stereo_live_runner_monitor_captures_all_streams_and_health_verdict(self):
        self.assertTrue(STEREO_LIVE_RUNNER.exists())
        source = STEREO_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("*>&1 | Tee-Object -FilePath $ReceiverLogLiteral -Append", source)
        self.assertIn("*>&1 | Tee-Object -FilePath $MonitorLogLiteral -Append", source)
        self.assertIn("validate_proxy_targets_end_to_end_health.py", source)
        self.assertIn("--sender-log", source)
        self.assertIn("--raw-status", source)
        self.assertIn("--pcmr-status", source)
        self.assertIn("--timeout-seconds", source)
        self.assertIn("STREAM_OK", source)
        self.assertIn("CARD_BOUND_TO_LIVE_TARGET", source)
        self.assertIn("SAMPLE_FALLBACK_ACTIVE", source)

    def test_stereo_live_runner_runs_health_even_when_raw_monitor_fails(self):
        self.assertTrue(STEREO_LIVE_RUNNER.exists())
        source = STEREO_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("`$RawMonitorFailed = `$false", source)
        self.assertIn("`$RawMonitorFailed = `$true", source)
        self.assertIn("Raw stream monitor failed; continuing to end-to-end health verdict.", source)
        self.assertIn("if (`$HealthExitCode -ne 0) {", source)
        self.assertIn("if (`$RawMonitorFailed) {", source)

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
