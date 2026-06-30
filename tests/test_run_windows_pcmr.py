from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_windows_pcmr.ps1"
LIVE_RUNNER = ROOT / "tools" / "run_windows_pcmr_proxy_targets_live.ps1"
STEREO_LIVE_RUNNER = ROOT / "tools" / "run_windows_pcmr_stereo_proxy_targets_live.ps1"
STEREO_PACKAGE_REPLAY_RUNNER = ROOT / "tools" / "run_windows_pcmr_stereo_package_proxy_targets_replay.ps1"
VISUAL_RUNNER = ROOT / "tools" / "run_windows_pcmr_overlay_visual_check.ps1"
VISUAL_DOC = ROOT / "docs" / "pcmr_overlay_visual_check.md"


class WindowsPcmrRunnerTests(unittest.TestCase):
    def test_runner_can_validate_real_proxy_targets_consumer(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("[switch]$ValidateProxyTargets", source)
        self.assertIn("[switch]$UseAntmanPassthroughOverlay", source)
        self.assertIn('[string]$ProxyTargetsWsUrl = "ws://127.0.0.1:8766/proxy_targets"', source)
        self.assertIn('[ValidateSet("", "dynamic", "world_latched")]', source)
        self.assertIn('[string]$ProxyTargetsAnchorMode = ""', source)
        self.assertIn('[ValidateSet("", "negative_z_forward", "positive_z_forward")]', source)
        self.assertIn('[string]$ProxyTargetsHeadZMode = ""', source)
        self.assertIn('[string]$SmartXROptionsPath = ""', source)
        self.assertIn("[double]$ProxyTargetsTimeoutSeconds = 15.0", source)
        self.assertIn("PROXY_TARGETS_WS_URL", source)
        self.assertIn("SMARTXR_OPTIONS_PATH", source)
        self.assertIn("SMARTXR_PROXY_TARGETS_ANCHOR_MODE", source)
        self.assertIn("SMARTXR_PROXY_TARGETS_HEAD_Z_MODE", source)
        self.assertIn("SMARTXR_USE_PASSTHROUGH_OVERLAY", source)
        self.assertIn("SMARTXR_STATUS_HUD_VISIBLE", source)
        self.assertIn("passthrough_overlay_status.json", source)
        self.assertIn("proxy_targets_live_status.json", source)
        self.assertIn("validate_proxy_targets_live_status.py", source)
        self.assertIn("--require", source)
        self.assertIn("attached", source)
        self.assertIn("SmartXR-PCMR proxy_targets live validation", source)
        self.assertIn("ProxyTargets anchor mode: $ProxyTargetsAnchorMode", source)
        self.assertIn("ProxyTargets head Z mode: $ProxyTargetsHeadZMode", source)
        self.assertIn("SmartXR options path: $ResolvedSmartXROptionsPath", source)
        self.assertIn("SmartXR-PCMR Antman passthrough overlay", source)
        self.assertIn("Restore-EnvVar -Name \"SMARTXR_OPTIONS_PATH\"", source)
        self.assertIn("Restore-EnvVar -Name \"SMARTXR_PROXY_TARGETS_ANCHOR_MODE\"", source)
        self.assertIn("Restore-EnvVar -Name \"SMARTXR_PROXY_TARGETS_HEAD_Z_MODE\"", source)
        self.assertIn("Restore-EnvVar -Name \"SMARTXR_USE_PASSTHROUGH_OVERLAY\"", source)
        self.assertIn("Restore-EnvVar -Name \"SMARTXR_STATUS_HUD_VISIBLE\"", source)
        self.assertIn("Restore-EnvVar -Name \"PROXY_TARGETS_WS_URL\"", source)
        self.assertIn('if (-not [string]::IsNullOrWhiteSpace($ProxyTargetsAnchorMode)) {', source)
        self.assertIn('if (-not [string]::IsNullOrWhiteSpace($ProxyTargetsHeadZMode)) {', source)

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

    def test_validate_proxy_targets_can_keep_godot_open_for_manual_inspection(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("[switch]$KeepGodotOpen", source)
        self.assertIn("Keep running: Godot stays open after attached validation succeeds.", source)
        self.assertIn("if (-not $KeepGodotOpen) {", source)
        self.assertIn("Stop-ChildProcess -Process $GodotProcess", source)

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
        self.assertIn('`$ArgsList["ProxyTargetsAnchorMode"] = $ProxyTargetsAnchorModeLiteral', source)
        self.assertIn('`$ArgsList["ProxyTargetsHeadZMode"] = $ProxyTargetsHeadZModeLiteral', source)
        self.assertIn("ws://${HostName}:${Port}/proxy_targets", source)
        self.assertIn("depth_confidence=high", source)

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
        self.assertIn('`$ArgsList["ProxyTargetsAnchorMode"] = $ProxyTargetsAnchorModeLiteral', source)
        self.assertIn('`$ArgsList["ProxyTargetsHeadZMode"] = $ProxyTargetsHeadZModeLiteral', source)
        self.assertIn("ProxyTargetsTimeoutSeconds = $ProxyTargetsTimeoutSeconds", source)
        self.assertIn("$MonitorArgs = @{", source)
        self.assertIn("$MonitorArgsList = @(", source)
        self.assertIn("& powershell.exe @MonitorArgsList", source)
        self.assertIn("Url = $WsUrlLiteral", source)
        self.assertIn("MinPackets = $MonitorMinPackets", source)
        self.assertIn("TimeoutSeconds = $MonitorTimeoutSeconds", source)
        self.assertNotIn("& $PythonExeLiteral $PublisherLiteral `", source)
        self.assertNotIn("& $MonitorRunnerLiteral `", source)

    def test_stereo_live_runner_can_keep_receiver_godot_open(self):
        self.assertTrue(STEREO_LIVE_RUNNER.exists())
        source = STEREO_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("[switch]$KeepReceiverOpen", source)
        self.assertIn("Keep receiver Godot open: $KeepReceiverOpen", source)
        self.assertIn("$KeepReceiverOpenLiteral", source)
        self.assertIn('`$ArgsList["KeepGodotOpen"] = `$true', source)
        self.assertIn("Close the receiver tab/window manually", source)

    def test_stereo_live_runner_wires_depth_trace_jsonl(self):
        self.assertTrue(STEREO_LIVE_RUNNER.exists())
        source = STEREO_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("depth_estimation_trace.jsonl", source)
        self.assertIn("$DepthTraceFile", source)
        self.assertIn("$DepthTraceFileLiteral", source)
        self.assertIn('"--depth-trace", $DepthTraceFileLiteral', source)
        self.assertIn("Depth trace:", source)

    def test_stereo_live_runner_uses_vst_ai_shm_consumer_reader_by_default(self):
        self.assertTrue(STEREO_LIVE_RUNNER.exists())
        source = STEREO_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn('[string]$VstAiShmRoot = "E:\\xia\\Antman\\0422\\0527\\P1\\vst_ai_shm"', source)
        self.assertIn("$VstAiShmRootLiteral", source)
        self.assertIn('"--vst-reader", "vst_ai_shm"', source)
        self.assertIn('"--vst-ai-shm-root", $VstAiShmRootLiteral', source)

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

    def test_stereo_live_runner_monitor_mentions_client_disconnect_and_pose_summary(self):
        self.assertTrue(STEREO_LIVE_RUNNER.exists())
        source = STEREO_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("client_label", source)
        self.assertIn("close_reason", source)
        self.assertIn("packets_before_close", source)
        self.assertIn("card_minus_proxy_world", source)
        self.assertIn("proxy_world_position", source)
        self.assertIn("card_resolved_position", source)

    def test_stereo_live_runner_runs_health_even_when_raw_monitor_fails(self):
        self.assertTrue(STEREO_LIVE_RUNNER.exists())
        source = STEREO_LIVE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("`$RawMonitorFailed = `$false", source)
        self.assertIn("`$RawMonitorFailed = `$true", source)
        self.assertIn("Raw stream monitor failed; continuing to end-to-end health verdict.", source)
        self.assertIn("if (`$HealthExitCode -ne 0) {", source)
        self.assertIn("if (`$RawMonitorFailed) {", source)

    def test_stereo_package_replay_runner_launches_sender_receiver_monitor_and_diagnostics(self):
        self.assertTrue(STEREO_PACKAGE_REPLAY_RUNNER.exists())
        source = STEREO_PACKAGE_REPLAY_RUNNER.read_text(encoding="utf-8")

        self.assertIn("[string]$PackageDir", source)
        self.assertIn("antman_vst_stereo_package_proxy_targets_live_publisher.py", source)
        self.assertIn('"--package-dir", $PackageDirLiteral', source)
        self.assertIn("$ReplayTimingLiteral = ConvertTo-PowerShellLiteral $ReplayTiming", source)
        self.assertIn('"--replay-timing", $ReplayTimingLiteral', source)
        self.assertIn('"--source-hz", "$SourceHz"', source)
        self.assertIn("depth_estimation_trace.jsonl", source)
        self.assertIn("live_run_diagnostics.json", source)
        self.assertIn("run_windows_pcmr.ps1", source)
        self.assertIn("run_proxy_targets_live_monitor.ps1", source)
        self.assertIn("analyze_live_run_diagnostics.py", source)
        self.assertIn('Open-RunnerTab -WindowName $WindowName -Title "SmartXR package replay sender"', source)
        self.assertIn('Open-RunnerTab -WindowName $WindowName -Title "SmartXR package replay receiver"', source)
        self.assertIn('Open-RunnerTab -WindowName $WindowName -Title "SmartXR proxy_targets monitor"', source)
        self.assertIn("package proxy_targets live replay publisher listening", source)

    def test_stereo_package_replay_runner_exposes_position_filter_tuning(self):
        self.assertTrue(STEREO_PACKAGE_REPLAY_RUNNER.exists())
        source = STEREO_PACKAGE_REPLAY_RUNNER.read_text(encoding="utf-8")

        self.assertIn("[double]$PositionFilterMinCutoff = 1.0", source)
        self.assertIn("[double]$PositionFilterBeta = 0.08", source)
        self.assertIn('"--position-filter-min-cutoff", "$PositionFilterMinCutoff"', source)
        self.assertIn('"--position-filter-beta", "$PositionFilterBeta"', source)
        self.assertIn("Position filter: min_cutoff=$PositionFilterMinCutoff beta=$PositionFilterBeta", source)

    def test_stereo_runners_expose_proxy_targets_anchor_mode(self):
        for runner in (STEREO_LIVE_RUNNER, STEREO_PACKAGE_REPLAY_RUNNER):
            with self.subTest(runner=runner.name):
                self.assertTrue(runner.exists())
                source = runner.read_text(encoding="utf-8")
                self.assertIn('[ValidateSet("", "dynamic", "world_latched")]', source)
                self.assertIn('[string]$ProxyTargetsAnchorMode = ""', source)
                self.assertIn("$ProxyTargetsAnchorModeLiteral = ConvertTo-PowerShellLiteral $ProxyTargetsAnchorMode", source)
                self.assertIn('if ($ProxyTargetsAnchorModeLiteral -ne \'\') {', source)
                self.assertIn('`$ArgsList["ProxyTargetsAnchorMode"] = $ProxyTargetsAnchorModeLiteral', source)
                self.assertIn("Anchor mode: $ProxyTargetsAnchorMode", source)

    def test_stereo_runners_expose_proxy_targets_head_z_mode(self):
        for runner in (STEREO_LIVE_RUNNER, STEREO_PACKAGE_REPLAY_RUNNER):
            with self.subTest(runner=runner.name):
                self.assertTrue(runner.exists())
                source = runner.read_text(encoding="utf-8")
                self.assertIn('[ValidateSet("", "negative_z_forward", "positive_z_forward")]', source)
                self.assertIn('[string]$ProxyTargetsHeadZMode = ""', source)
                self.assertIn("$ProxyTargetsHeadZModeLiteral = ConvertTo-PowerShellLiteral $ProxyTargetsHeadZMode", source)
                self.assertIn('if ($ProxyTargetsHeadZModeLiteral -ne \'\') {', source)
                self.assertIn('`$ArgsList["ProxyTargetsHeadZMode"] = $ProxyTargetsHeadZModeLiteral', source)
                self.assertIn("Head Z mode: $ProxyTargetsHeadZMode", source)

    def test_stereo_runners_pass_shared_smartxr_options_path_to_sender_and_receiver(self):
        for runner in (STEREO_LIVE_RUNNER, STEREO_PACKAGE_REPLAY_RUNNER):
            with self.subTest(runner=runner.name):
                self.assertTrue(runner.exists())
                source = runner.read_text(encoding="utf-8")
                self.assertIn('[string]$SmartXROptionsPath = "config\\smartxr_options.json"', source)
                self.assertIn("$SmartXROptionsPathLiteral = ConvertTo-PowerShellLiteral $ResolvedSmartXROptionsPath", source)
                self.assertIn('"--smartxr-options", $SmartXROptionsPathLiteral', source)
                self.assertIn("SmartXROptionsPath = $SmartXROptionsPathLiteral", source)
                self.assertIn("SmartXR options: $ResolvedSmartXROptionsPath", source)

    def test_stereo_package_replay_runner_supports_demo_only_receiver(self):
        self.assertTrue(STEREO_PACKAGE_REPLAY_RUNNER.exists())
        source = STEREO_PACKAGE_REPLAY_RUNNER.read_text(encoding="utf-8")

        self.assertIn("[switch]$DemoOnly", source)
        self.assertIn("$ProjectDir = Join-Path -Path $RepoRoot -ChildPath \"godot-android\"", source)
        self.assertIn("$GxrExtensionSwitch = Join-Path -Path $RepoRoot -ChildPath \"tools\\set_gxr_extension.ps1\"", source)
        self.assertIn("if ($DemoOnlyLiteral) {", source)
        self.assertIn("& $GxrExtensionSwitchLiteral -Mode disable -ProjectDir $ProjectDirLiteral", source)
        self.assertIn('$env:PROXY_TARGETS_WS_URL = $WsUrlLiteral', source)
        self.assertIn('$env:SMARTXR_OPTIONS_PATH = $SmartXROptionsPathLiteral', source)
        self.assertIn('if ($ProxyTargetsHeadZModeLiteral -ne \'\') {', source)
        self.assertIn('`$env:SMARTXR_PROXY_TARGETS_HEAD_Z_MODE = $ProxyTargetsHeadZModeLiteral', source)
        self.assertIn('$env:SMARTXR_STATUS_HUD_VISIBLE = "1"', source)
        self.assertIn('`$OldGodotErrorActionPreference = `$ErrorActionPreference', source)
        self.assertIn('`$ErrorActionPreference = "Continue"', source)
        self.assertIn("& $GodotExeLiteral --xr-mode off --path $ProjectDirLiteral", source)
        self.assertIn('`$ErrorActionPreference = `$OldGodotErrorActionPreference', source)
        self.assertIn("& $GxrExtensionSwitchLiteral -Mode enable -ProjectDir $ProjectDirLiteral", source)

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
