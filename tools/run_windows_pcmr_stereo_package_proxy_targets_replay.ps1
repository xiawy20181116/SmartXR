param(
    [Parameter(Mandatory = $true)]
    [string]$PackageDir,
    [string]$AntmanRoot = "E:\xia\Antman_smart",
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$SmartXROptionsPath = "config\smartxr_options.json",
    [ValidateSet("capture", "fixed", "fast")]
    [string]$ReplayTiming = "capture",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8766,
    [double]$Hz = 20.0,
    [double]$SourceHz = 45.0,
    [double]$MinConfidence = 0.5,
    [double]$PositionFilterMinCutoff = 1.0,
    [double]$PositionFilterBeta = 0.08,
    [int]$RecordedWidth = 880,
    [int]$RecordedHeight = 660,
    [int]$LogEvery = 20,
    [double]$SenderReadyTimeoutSeconds = 45.0,
    [double]$ProxyTargetsTimeoutSeconds = 60.0,
    [ValidateSet("", "dynamic", "world_latched")]
    [string]$ProxyTargetsAnchorMode = "",
    [ValidateSet("", "negative_z_forward", "positive_z_forward")]
    [string]$ProxyTargetsHeadZMode = "",
    [ValidateSet("real", "fixed", "scale_offset", "noise")]
    [string]$DepthOverrideMode = "real",
    [double]$DepthOverrideFixedM = 1.5,
    [double]$DepthOverrideScale = 1.0,
    [double]$DepthOverrideOffsetM = 0.0,
    [double]$DepthOverrideNoiseStdM = 0.0,
    [int]$DepthOverrideSeed = 0,
    [int]$MonitorMinPackets = 10,
    [double]$MonitorTimeoutSeconds = 20.0,
    [switch]$UseAntmanPassthroughOverlay,
    [switch]$KeepReceiverOpen,
    [switch]$DemoOnly,
    [switch]$EnableKeypointAnchor,
    [string]$PoseModel = "yolov8n-pose.pt",
    [int]$PoseImgsz = 640,
    [double]$PoseConf = 0.25,
    [double]$MinKeypointScore = 0.5,
    [string]$PoseDevice = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$ResolvedSmartXROptionsPath = if ([System.IO.Path]::IsPathRooted($SmartXROptionsPath)) {
    [System.IO.Path]::GetFullPath($SmartXROptionsPath)
} else {
    [System.IO.Path]::GetFullPath((Join-Path -Path $RepoRoot -ChildPath $SmartXROptionsPath))
}
$ProjectDir = Join-Path -Path $RepoRoot -ChildPath "godot-android"
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\antman_vst_stereo_package_proxy_targets_live_publisher.py"
$PcmrRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_windows_pcmr.ps1"
$MonitorRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_proxy_targets_live_monitor.ps1"
$HealthValidator = Join-Path -Path $RepoRoot -ChildPath "tools\validate_proxy_targets_end_to_end_health.py"
$RunDiagnosticsAnalyzer = Join-Path -Path $RepoRoot -ChildPath "tools\analyze_live_run_diagnostics.py"
$GxrExtensionSwitch = Join-Path -Path $RepoRoot -ChildPath "tools\set_gxr_extension.ps1"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\windows_pcmr_stereo_package_proxy_targets_replay"
$SenderScript = Join-Path -Path $WorkDir -ChildPath "sender.ps1"
$ReceiverScript = Join-Path -Path $WorkDir -ChildPath "receiver.ps1"
$MonitorScript = Join-Path -Path $WorkDir -ChildPath "monitor.ps1"
$SenderLog = Join-Path -Path $WorkDir -ChildPath "sender.log"
$ReceiverLog = Join-Path -Path $WorkDir -ChildPath "receiver.log"
$MonitorLog = Join-Path -Path $WorkDir -ChildPath "monitor.log"
$DepthTraceFile = Join-Path -Path $WorkDir -ChildPath "depth_estimation_trace.jsonl"
$PoseTraceFile = Join-Path -Path $WorkDir -ChildPath "godot_pose_trace.jsonl"
$HealthStatusFile = Join-Path -Path $WorkDir -ChildPath "end_to_end_health_status.json"
$RunDiagnosticsFile = Join-Path -Path $WorkDir -ChildPath "live_run_diagnostics.json"
$RawMonitorStatusFile = Join-Path -Path $RepoRoot -ChildPath ".tmp\proxy_targets_live_monitor\proxy_targets_live_monitor_status.json"
$PcmrStatusFile = Join-Path -Path $env:APPDATA -ChildPath "Godot\app_userdata\demo_run\proxy_targets_live_status.json"
$SenderReadyFile = Join-Path -Path $WorkDir -ChildPath "sender_ready.txt"
$WsUrl = "ws://${HostName}:${Port}/proxy_targets"
$WindowName = "smartxr-stereo-package-replay-" + (Get-Date -Format "yyyyMMdd-HHmmss")

function ConvertTo-PowerShellLiteral {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Wait-ForLogText {
    param(
        [string]$Path,
        [string]$Text,
        [double]$TimeoutSeconds
    )

    $Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($Stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (Test-Path -LiteralPath $Path) {
            try {
                if (Select-String -Path $Path -SimpleMatch -Pattern $Text -Quiet) {
                    return $true
                }
            } catch {
            }
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Get-LogTail {
    param(
        [string]$Path,
        [int]$Tail = 40
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return "(sender log not found yet: $Path)"
    }

    try {
        $Lines = Get-Content -LiteralPath $Path -Tail $Tail -ErrorAction Stop
        if ($null -eq $Lines -or $Lines.Count -eq 0) {
            return "(sender log is empty: $Path)"
        }
        return ($Lines -join [Environment]::NewLine)
    } catch {
        return "(failed to read sender log: $($_.Exception.Message))"
    }
}

function Start-VisiblePowerShellWindow {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath
    )

    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Normal | Out-Null
    Write-Host "Opened $Title window: $ScriptPath"
}

function Open-RunnerTab {
    param(
        [string]$WindowName,
        [string]$Title,
        [string]$RunnerPath
    )

    if (Get-Command wt.exe -ErrorAction SilentlyContinue) {
        & wt.exe -w $WindowName new-tab --title $Title powershell.exe -NoExit -ExecutionPolicy Bypass -File $RunnerPath
    } else {
        Write-Host "wt.exe not found; falling back to a standalone PowerShell window for $Title" -ForegroundColor Yellow
        Start-VisiblePowerShellWindow -Title $Title -ScriptPath $RunnerPath
    }
}

if ($PythonExe -eq "") {
    $PythonCandidates = @(
        (Join-Path -Path $AntmanRoot -ChildPath "human_detect\.venv\Scripts\python.exe"),
        (Join-Path -Path $AntmanRoot -ChildPath "demo\.uv-venv\Scripts\python.exe"),
        (Join-Path -Path $AntmanRoot -ChildPath ".venv\Scripts\python.exe")
    )
    foreach ($Candidate in $PythonCandidates) {
        if (Test-Path -LiteralPath $Candidate) {
            $PythonExe = $Candidate
            break
        }
    }
    if ($PythonExe -eq "") {
        $PythonExe = "python"
    }
}

$ResolvedPackageDir = [string](Resolve-Path -LiteralPath $PackageDir)
$RequiredPaths = @($Publisher, $MonitorRunner, $HealthValidator, $RunDiagnosticsAnalyzer, $ResolvedPackageDir, $ResolvedSmartXROptionsPath)
if ($DemoOnly) {
    $RequiredPaths += @($GodotExe, $ProjectDir, $GxrExtensionSwitch)
} else {
    $RequiredPaths += @($PcmrRunner)
}
foreach ($RequiredPath in $RequiredPaths) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path not found: $RequiredPath"
    }
}

if ($PythonExe -ne "python" -and -not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $SenderLog, $ReceiverLog, $MonitorLog, $DepthTraceFile, $PoseTraceFile, $HealthStatusFile, $RunDiagnosticsFile, $SenderReadyFile -Force -ErrorAction SilentlyContinue

$RepoRootLiteral = ConvertTo-PowerShellLiteral $RepoRoot
$PythonExeLiteral = ConvertTo-PowerShellLiteral $PythonExe
$PublisherLiteral = ConvertTo-PowerShellLiteral $Publisher
$ProjectDirLiteral = ConvertTo-PowerShellLiteral $ProjectDir
$PcmrRunnerLiteral = ConvertTo-PowerShellLiteral $PcmrRunner
$MonitorRunnerLiteral = ConvertTo-PowerShellLiteral $MonitorRunner
$HealthValidatorLiteral = ConvertTo-PowerShellLiteral $HealthValidator
$RunDiagnosticsAnalyzerLiteral = ConvertTo-PowerShellLiteral $RunDiagnosticsAnalyzer
$GxrExtensionSwitchLiteral = ConvertTo-PowerShellLiteral $GxrExtensionSwitch
$PackageDirLiteral = ConvertTo-PowerShellLiteral $ResolvedPackageDir
$ReplayTimingLiteral = ConvertTo-PowerShellLiteral $ReplayTiming
$AntmanRootLiteral = ConvertTo-PowerShellLiteral $AntmanRoot
$GodotExeLiteral = ConvertTo-PowerShellLiteral $GodotExe
$ProxyTargetsAnchorModeLiteral = ConvertTo-PowerShellLiteral $ProxyTargetsAnchorMode
$ProxyTargetsHeadZModeLiteral = ConvertTo-PowerShellLiteral $ProxyTargetsHeadZMode
$DepthOverrideModeLiteral = ConvertTo-PowerShellLiteral $DepthOverrideMode
$SmartXROptionsPathLiteral = ConvertTo-PowerShellLiteral $ResolvedSmartXROptionsPath
$PoseModelLiteral = ConvertTo-PowerShellLiteral $PoseModel
$PoseDeviceLiteral = ConvertTo-PowerShellLiteral $PoseDevice
$WsUrlLiteral = ConvertTo-PowerShellLiteral $WsUrl
$SenderLogLiteral = ConvertTo-PowerShellLiteral $SenderLog
$ReceiverLogLiteral = ConvertTo-PowerShellLiteral $ReceiverLog
$MonitorLogLiteral = ConvertTo-PowerShellLiteral $MonitorLog
$DepthTraceFileLiteral = ConvertTo-PowerShellLiteral $DepthTraceFile
$PoseTraceFileLiteral = ConvertTo-PowerShellLiteral $PoseTraceFile
$HealthStatusFileLiteral = ConvertTo-PowerShellLiteral $HealthStatusFile
$RunDiagnosticsFileLiteral = ConvertTo-PowerShellLiteral $RunDiagnosticsFile
$RawMonitorStatusFileLiteral = ConvertTo-PowerShellLiteral $RawMonitorStatusFile
$PcmrStatusFileLiteral = ConvertTo-PowerShellLiteral $PcmrStatusFile
$SenderReadyFileLiteral = ConvertTo-PowerShellLiteral $SenderReadyFile
$UseOverlayLiteral = if ($UseAntmanPassthroughOverlay) { "`$true" } else { "`$false" }
$KeepReceiverOpenLiteral = if ($KeepReceiverOpen) { "`$true" } else { "`$false" }
$DemoOnlyLiteral = if ($DemoOnly) { "`$true" } else { "`$false" }
$EnableKeypointAnchorLiteral = if ($EnableKeypointAnchor) { "`$true" } else { "`$false" }

$SenderContent = @"
`$ErrorActionPreference = "Stop"
`$Host.UI.RawUI.WindowTitle = "SmartXR package replay sender"
Set-Location -LiteralPath $RepoRootLiteral
Write-Host "[sender] SmartXR stereo package replay sender"
Write-Host "[sender] WebSocket: $WsUrl"
Write-Host "[sender] Package: $ResolvedPackageDir"
Write-Host "[sender] Replay timing: $ReplayTiming source_hz=$SourceHz publish_hz=$Hz"
Write-Host "[sender] Position filter: min_cutoff=$PositionFilterMinCutoff beta=$PositionFilterBeta"
Write-Host "[sender] SmartXR options: $ResolvedSmartXROptionsPath"
Write-Host "[sender] Keypoint anchor: $EnableKeypointAnchor pose_model=$PoseModel pose_imgsz=$PoseImgsz min_keypoint_score=$MinKeypointScore"
Write-Host "[sender] Depth trace: $DepthTraceFile"
Write-Host "[sender] Depth override: mode=$DepthOverrideMode fixed_m=$DepthOverrideFixedM scale=$DepthOverrideScale offset_m=$DepthOverrideOffsetM noise_std_m=$DepthOverrideNoiseStdM seed=$DepthOverrideSeed"
Write-Host "[sender] A healthy replay should print published stereo seq=..."
`$PublisherArgs = @(
  $PublisherLiteral,
  "--package-dir", $PackageDirLiteral,
  "--replay-timing", $ReplayTimingLiteral,
  "--source-hz", "$SourceHz",
  "--antman-root", $AntmanRootLiteral,
  "--host", "$HostName",
  "--port", "$Port",
  "--hz", "$Hz",
  "--min-confidence", "$MinConfidence",
  "--position-filter-min-cutoff", "$PositionFilterMinCutoff",
  "--position-filter-beta", "$PositionFilterBeta",
  "--recorded-width", "$RecordedWidth",
  "--recorded-height", "$RecordedHeight",
  "--log-every", "$LogEvery",
  "--smartxr-options", $SmartXROptionsPathLiteral,
  "--depth-override-mode", $DepthOverrideModeLiteral,
  "--depth-override-fixed-m", "$DepthOverrideFixedM",
  "--depth-override-scale", "$DepthOverrideScale",
  "--depth-override-offset-m", "$DepthOverrideOffsetM",
  "--depth-override-noise-std-m", "$DepthOverrideNoiseStdM",
  "--depth-override-seed", "$DepthOverrideSeed",
  "--depth-trace", $DepthTraceFileLiteral
)
if ($EnableKeypointAnchorLiteral) {
  `$PublisherArgs += @(
    "--enable-keypoint-anchor",
    "--pose-model", $PoseModelLiteral,
    "--pose-imgsz", "$PoseImgsz",
    "--pose-conf", "$PoseConf",
    "--min-keypoint-score", "$MinKeypointScore"
  )
  if ($PoseDeviceLiteral -ne '') {
    `$PublisherArgs += @("--pose-device", $PoseDeviceLiteral)
  }
}
& $PythonExeLiteral @PublisherArgs 2>&1 | Tee-Object -FilePath $SenderLogLiteral -Append
`$ExitCode = `$LASTEXITCODE
Write-Host "[sender] Stereo package replay sender exited with code `$ExitCode"
exit `$ExitCode
"@

$ReceiverContent = @"
`$ErrorActionPreference = "Stop"
`$Host.UI.RawUI.WindowTitle = "SmartXR package replay receiver"
Set-Location -LiteralPath $RepoRootLiteral
Write-Host "[receiver] SmartXR package replay receiver"
Write-Host "[receiver] Using proxy_targets: $WsUrl"
Write-Host "[receiver] Waiting for sender_ready marker; receiver waits for sender_ready."
while (-not (Test-Path -LiteralPath $SenderReadyFileLiteral)) {
  Start-Sleep -Milliseconds 250
}
if ($DemoOnlyLiteral) {
  Write-Host "[receiver] Sender ready; starting demo_run without PCMR validation."
  `$OldProxyTargetsWsUrl = `$env:PROXY_TARGETS_WS_URL
  `$OldSmartXROptionsPath = `$env:SMARTXR_OPTIONS_PATH
  `$OldProxyTargetsAnchorMode = `$env:SMARTXR_PROXY_TARGETS_ANCHOR_MODE
  `$OldProxyTargetsHeadZMode = `$env:SMARTXR_PROXY_TARGETS_HEAD_Z_MODE
  `$OldProxyTargetsPoseTracePath = `$env:SMARTXR_PROXY_TARGETS_POSE_TRACE_PATH
  `$OldStatusHudVisible = `$env:SMARTXR_STATUS_HUD_VISIBLE
  try {
    & $GxrExtensionSwitchLiteral -Mode disable -ProjectDir $ProjectDirLiteral
    `$env:PROXY_TARGETS_WS_URL = $WsUrlLiteral
    `$env:SMARTXR_OPTIONS_PATH = $SmartXROptionsPathLiteral
    `$env:SMARTXR_PROXY_TARGETS_POSE_TRACE_PATH = $PoseTraceFileLiteral
    if ($ProxyTargetsAnchorModeLiteral -ne '') {
      `$env:SMARTXR_PROXY_TARGETS_ANCHOR_MODE = $ProxyTargetsAnchorModeLiteral
    } else {
      Remove-Item Env:\SMARTXR_PROXY_TARGETS_ANCHOR_MODE -ErrorAction SilentlyContinue
    }
    if ($ProxyTargetsHeadZModeLiteral -ne '') {
      `$env:SMARTXR_PROXY_TARGETS_HEAD_Z_MODE = $ProxyTargetsHeadZModeLiteral
    } else {
      Remove-Item Env:\SMARTXR_PROXY_TARGETS_HEAD_Z_MODE -ErrorAction SilentlyContinue
    }
    `$env:SMARTXR_STATUS_HUD_VISIBLE = "1"
    `$OldGodotErrorActionPreference = `$ErrorActionPreference
    `$ErrorActionPreference = "Continue"
    try {
      & $GodotExeLiteral --xr-mode off --path $ProjectDirLiteral *>&1 | Tee-Object -FilePath $ReceiverLogLiteral -Append
      `$ExitCode = `$LASTEXITCODE
    } finally {
      `$ErrorActionPreference = `$OldGodotErrorActionPreference
    }
  } finally {
    if (`$null -eq `$OldProxyTargetsWsUrl) {
      Remove-Item Env:\PROXY_TARGETS_WS_URL -ErrorAction SilentlyContinue
    } else {
      `$env:PROXY_TARGETS_WS_URL = `$OldProxyTargetsWsUrl
    }
    if (`$null -eq `$OldSmartXROptionsPath) {
      Remove-Item Env:\SMARTXR_OPTIONS_PATH -ErrorAction SilentlyContinue
    } else {
      `$env:SMARTXR_OPTIONS_PATH = `$OldSmartXROptionsPath
    }
    if (`$null -eq `$OldProxyTargetsAnchorMode) {
      Remove-Item Env:\SMARTXR_PROXY_TARGETS_ANCHOR_MODE -ErrorAction SilentlyContinue
    } else {
      `$env:SMARTXR_PROXY_TARGETS_ANCHOR_MODE = `$OldProxyTargetsAnchorMode
    }
    if (`$null -eq `$OldProxyTargetsHeadZMode) {
      Remove-Item Env:\SMARTXR_PROXY_TARGETS_HEAD_Z_MODE -ErrorAction SilentlyContinue
    } else {
      `$env:SMARTXR_PROXY_TARGETS_HEAD_Z_MODE = `$OldProxyTargetsHeadZMode
    }
    if (`$null -eq `$OldProxyTargetsPoseTracePath) {
      Remove-Item Env:\SMARTXR_PROXY_TARGETS_POSE_TRACE_PATH -ErrorAction SilentlyContinue
    } else {
      `$env:SMARTXR_PROXY_TARGETS_POSE_TRACE_PATH = `$OldProxyTargetsPoseTracePath
    }
    if (`$null -eq `$OldStatusHudVisible) {
      Remove-Item Env:\SMARTXR_STATUS_HUD_VISIBLE -ErrorAction SilentlyContinue
    } else {
      `$env:SMARTXR_STATUS_HUD_VISIBLE = `$OldStatusHudVisible
    }
    & $GxrExtensionSwitchLiteral -Mode enable -ProjectDir $ProjectDirLiteral
  }
} else {
  Write-Host "[receiver] Sender ready; starting PCMR validation."
  `$ArgsList = @{
    GodotExe = $GodotExeLiteral
    ValidateProxyTargets = `$true
    ProxyTargetsWsUrl = $WsUrlLiteral
    SmartXROptionsPath = $SmartXROptionsPathLiteral
    ProxyTargetsPoseTracePath = $PoseTraceFileLiteral
    ProxyTargetsTimeoutSeconds = $ProxyTargetsTimeoutSeconds
  }
  if ($ProxyTargetsAnchorModeLiteral -ne '') {
    `$ArgsList["ProxyTargetsAnchorMode"] = $ProxyTargetsAnchorModeLiteral
  }
  if ($ProxyTargetsHeadZModeLiteral -ne '') {
    `$ArgsList["ProxyTargetsHeadZMode"] = $ProxyTargetsHeadZModeLiteral
  }
  if ($UseOverlayLiteral) {
    `$ArgsList["UseAntmanPassthroughOverlay"] = `$true
  }
  if ($KeepReceiverOpenLiteral) {
    `$ArgsList["KeepGodotOpen"] = `$true
  }
  & $PcmrRunnerLiteral @ArgsList *>&1 | Tee-Object -FilePath $ReceiverLogLiteral -Append
  `$ExitCode = `$LASTEXITCODE
}
Write-Host "[receiver] Package replay receiver exited with code `$ExitCode"
exit `$ExitCode
"@

$MonitorContent = @"
`$ErrorActionPreference = "Stop"
`$Host.UI.RawUI.WindowTitle = "SmartXR proxy_targets monitor"
Set-Location -LiteralPath $RepoRootLiteral
Write-Host "[monitor] SmartXR proxy_targets monitor"
Write-Host "[monitor] Waiting for sender_ready marker; monitor waits for sender_ready."
while (-not (Test-Path -LiteralPath $SenderReadyFileLiteral)) {
  Start-Sleep -Milliseconds 250
}
Write-Host "[monitor] Sender ready; collecting packets."
`$MonitorArgsList = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $MonitorRunnerLiteral,
  "-Url", $WsUrlLiteral,
  "-MinPackets", "$MonitorMinPackets",
  "-TimeoutSeconds", "$MonitorTimeoutSeconds",
  "-PythonExe", $PythonExeLiteral
)
`$RawMonitorFailed = `$false
& powershell.exe @MonitorArgsList *>&1 | Tee-Object -FilePath $MonitorLogLiteral -Append
`$RawMonitorExitCode = `$LASTEXITCODE
Write-Host "[monitor] Raw stream monitor exited with code `$RawMonitorExitCode"
if (`$RawMonitorExitCode -ne 0) {
  `$RawMonitorFailed = `$true
  Write-Host "[monitor] Raw stream monitor failed; continuing to end-to-end health verdict."
}
Write-Host "[monitor] Running end-to-end health verdict."
`$HealthArgs = @(
  $HealthValidatorLiteral,
  "--sender-log", $SenderLogLiteral,
  "--raw-status", $RawMonitorStatusFileLiteral,
  "--pcmr-status", $PcmrStatusFileLiteral,
  "--min-packets", "$MonitorMinPackets",
  "--timeout-seconds", "$ProxyTargetsTimeoutSeconds",
  "--depth-trace", $DepthTraceFileLiteral,
  "--output", $HealthStatusFileLiteral
)
& $PythonExeLiteral @HealthArgs *>&1 | Tee-Object -FilePath $MonitorLogLiteral -Append
`$HealthExitCode = `$LASTEXITCODE
Write-Host "[monitor] End-to-end health monitor exited with code `$HealthExitCode"
Write-Host "[monitor] Generating run-level diagnostics."
`$RunDiagnosticsArgs = @(
  $RunDiagnosticsAnalyzerLiteral,
  "--depth-trace", $DepthTraceFileLiteral,
  "--raw-status", $RawMonitorStatusFileLiteral,
  "--pcmr-status", $PcmrStatusFileLiteral,
  "--sender-log", $SenderLogLiteral,
  "--output", $RunDiagnosticsFileLiteral,
  "--top-n", "10",
  "--context-radius", "5"
)
& $PythonExeLiteral @RunDiagnosticsArgs *>&1 | Tee-Object -FilePath $MonitorLogLiteral -Append
`$RunDiagnosticsExitCode = `$LASTEXITCODE
Write-Host "[monitor] Run-level diagnostics exited with code `$RunDiagnosticsExitCode"
if (`$HealthExitCode -ne 0) {
  exit `$HealthExitCode
}
if (`$RunDiagnosticsExitCode -ne 0) {
  exit `$RunDiagnosticsExitCode
}
if (`$RawMonitorFailed) {
  exit `$RawMonitorExitCode
}
exit `$RawMonitorExitCode
"@

Set-Content -LiteralPath $SenderScript -Value $SenderContent -Encoding UTF8
Set-Content -LiteralPath $ReceiverScript -Value $ReceiverContent -Encoding UTF8
Set-Content -LiteralPath $MonitorScript -Value $MonitorContent -Encoding UTF8

Write-Host "SmartXR-PCMR stereo package proxy_targets replay validation"
Write-Host "This opens one Windows Terminal window with three tabs when wt.exe is available."
Write-Host "It falls back to three visible PowerShell windows otherwise."
Write-Host "WebSocket: $WsUrl"
Write-Host "Package:   $ResolvedPackageDir"
Write-Host "Timing:    $ReplayTiming source_hz=$SourceHz publish_hz=$Hz"
Write-Host "Filter:    min_cutoff=$PositionFilterMinCutoff beta=$PositionFilterBeta"
Write-Host "Anchor mode: $ProxyTargetsAnchorMode"
Write-Host "Head Z mode: $ProxyTargetsHeadZMode"
Write-Host "SmartXR options: $ResolvedSmartXROptionsPath"
Write-Host "Keypoint anchor: $EnableKeypointAnchor"
Write-Host "Demo only: $DemoOnly"
Write-Host "Work dir:  $WorkDir"
Write-Host "Depth override: mode=$DepthOverrideMode fixed_m=$DepthOverrideFixedM scale=$DepthOverrideScale offset_m=$DepthOverrideOffsetM noise_std_m=$DepthOverrideNoiseStdM seed=$DepthOverrideSeed"
Write-Host "Depth trace: $DepthTraceFile"
Write-Host "Godot pose trace: $PoseTraceFile"
Write-Host ""

Open-RunnerTab -WindowName $WindowName -Title "SmartXR package replay sender" -RunnerPath $SenderScript

Write-Host "Waiting for sender readiness: package proxy_targets live replay publisher listening"
if (-not (Wait-ForLogText -Path $SenderLog -Text "package proxy_targets live replay publisher listening" -TimeoutSeconds $SenderReadyTimeoutSeconds)) {
    $SenderLogTail = Get-LogTail -Path $SenderLog
    throw @"
Sender did not report ready within $SenderReadyTimeoutSeconds seconds.
Check: $SenderLog

Sender log tail:
$SenderLogTail
"@
}
Set-Content -LiteralPath $SenderReadyFile -Value "ready" -Encoding ASCII

Open-RunnerTab -WindowName $WindowName -Title "SmartXR package replay receiver" -RunnerPath $ReceiverScript
Open-RunnerTab -WindowName $WindowName -Title "SmartXR proxy_targets monitor" -RunnerPath $MonitorScript

Write-Host ""
Write-Host "Started package replay sender, receiver, and monitor."
Write-Host "Close the sender tab/window manually after replay inspection is done."
if ($KeepReceiverOpen) {
    Write-Host "Close the receiver tab/window manually after visual card inspection is done."
}
Write-Host ""
Write-Host "Logs:"
Write-Host "  Sender:   $SenderLog"
Write-Host "  Receiver: $ReceiverLog"
Write-Host "  Monitor:  $MonitorLog"
Write-Host "  Depth trace: $DepthTraceFile"
Write-Host "  Godot pose trace: $PoseTraceFile"
Write-Host "  Health:   $HealthStatusFile"
Write-Host "  Run diagnostics: $RunDiagnosticsFile"
