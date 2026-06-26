param(
    [string]$AntmanRoot = "E:\xia\Antman_smart",
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8766,
    [double]$Hz = 20.0,
    [double]$MinConfidence = 0.5,
    [int]$RecordedWidth = 880,
    [int]$RecordedHeight = 660,
    [int]$LogEvery = 20,
    [double]$SenderReadyTimeoutSeconds = 45.0,
    [double]$ProxyTargetsTimeoutSeconds = 60.0,
    [int]$MonitorMinPackets = 10,
    [double]$MonitorTimeoutSeconds = 20.0,
    [switch]$UseAntmanPassthroughOverlay,
    [switch]$KeepReceiverOpen,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\antman_vst_stereo_proxy_targets_live_publisher.py"
$PcmrRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_windows_pcmr.ps1"
$MonitorRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_proxy_targets_live_monitor.ps1"
$HealthValidator = Join-Path -Path $RepoRoot -ChildPath "tools\validate_proxy_targets_end_to_end_health.py"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\windows_pcmr_stereo_proxy_targets_live"
$SenderScript = Join-Path -Path $WorkDir -ChildPath "sender.ps1"
$ReceiverScript = Join-Path -Path $WorkDir -ChildPath "receiver.ps1"
$MonitorScript = Join-Path -Path $WorkDir -ChildPath "monitor.ps1"
$SenderLog = Join-Path -Path $WorkDir -ChildPath "sender.log"
$ReceiverLog = Join-Path -Path $WorkDir -ChildPath "receiver.log"
$MonitorLog = Join-Path -Path $WorkDir -ChildPath "monitor.log"
$HealthStatusFile = Join-Path -Path $WorkDir -ChildPath "end_to_end_health_status.json"
$RawMonitorStatusFile = Join-Path -Path $RepoRoot -ChildPath ".tmp\proxy_targets_live_monitor\proxy_targets_live_monitor_status.json"
$PcmrStatusFile = Join-Path -Path $env:APPDATA -ChildPath "Godot\app_userdata\demo_run\proxy_targets_live_status.json"
$SenderReadyFile = Join-Path -Path $WorkDir -ChildPath "sender_ready.txt"
$WsUrl = "ws://${HostName}:${Port}/proxy_targets"
$WindowName = "smartxr-stereo-live-" + (Get-Date -Format "yyyyMMdd-HHmmss")

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

foreach ($RequiredPath in @($Publisher, $PcmrRunner, $MonitorRunner, $HealthValidator)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required file not found: $RequiredPath"
    }
}

if ($PythonExe -ne "python" -and -not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $SenderLog, $ReceiverLog, $MonitorLog, $HealthStatusFile, $SenderReadyFile -Force -ErrorAction SilentlyContinue

$RepoRootLiteral = ConvertTo-PowerShellLiteral $RepoRoot
$PythonExeLiteral = ConvertTo-PowerShellLiteral $PythonExe
$PublisherLiteral = ConvertTo-PowerShellLiteral $Publisher
$PcmrRunnerLiteral = ConvertTo-PowerShellLiteral $PcmrRunner
$MonitorRunnerLiteral = ConvertTo-PowerShellLiteral $MonitorRunner
$HealthValidatorLiteral = ConvertTo-PowerShellLiteral $HealthValidator
$AntmanRootLiteral = ConvertTo-PowerShellLiteral $AntmanRoot
$GodotExeLiteral = ConvertTo-PowerShellLiteral $GodotExe
$WsUrlLiteral = ConvertTo-PowerShellLiteral $WsUrl
$SenderLogLiteral = ConvertTo-PowerShellLiteral $SenderLog
$ReceiverLogLiteral = ConvertTo-PowerShellLiteral $ReceiverLog
$MonitorLogLiteral = ConvertTo-PowerShellLiteral $MonitorLog
$HealthStatusFileLiteral = ConvertTo-PowerShellLiteral $HealthStatusFile
$RawMonitorStatusFileLiteral = ConvertTo-PowerShellLiteral $RawMonitorStatusFile
$PcmrStatusFileLiteral = ConvertTo-PowerShellLiteral $PcmrStatusFile
$SenderReadyFileLiteral = ConvertTo-PowerShellLiteral $SenderReadyFile
$UseOverlayLiteral = if ($UseAntmanPassthroughOverlay) { "`$true" } else { "`$false" }
$KeepReceiverOpenLiteral = if ($KeepReceiverOpen) { "`$true" } else { "`$false" }

$SenderContent = @"
`$ErrorActionPreference = "Stop"
`$Host.UI.RawUI.WindowTitle = "SmartXR stereo sender"
Set-Location -LiteralPath $RepoRootLiteral
Write-Host "[sender] SmartXR stereo sender"
Write-Host "[sender] WebSocket: $WsUrl"
Write-Host "[sender] Expected depth_source=bbox_top_center_fallback depth_confidence=low"
Write-Host "[sender] A later healthy run should print sent stereo seq=..."
`$PublisherArgs = @(
  $PublisherLiteral,
  "--antman-root", $AntmanRootLiteral,
  "--host", "$HostName",
  "--port", "$Port",
  "--hz", "$Hz",
  "--min-confidence", "$MinConfidence",
  "--recorded-width", "$RecordedWidth",
  "--recorded-height", "$RecordedHeight",
  "--log-every", "$LogEvery"
)
& $PythonExeLiteral @PublisherArgs 2>&1 | Tee-Object -FilePath $SenderLogLiteral -Append
`$ExitCode = `$LASTEXITCODE
Write-Host "[sender] Stereo sender exited with code `$ExitCode"
exit `$ExitCode
"@

$ReceiverContent = @"
`$ErrorActionPreference = "Stop"
`$Host.UI.RawUI.WindowTitle = "SmartXR PCMR receiver"
Set-Location -LiteralPath $RepoRootLiteral
Write-Host "[receiver] SmartXR PCMR receiver"
Write-Host "[receiver] Using proxy_targets: $WsUrl"
Write-Host "[receiver] Waiting for sender_ready marker; receiver waits for sender_ready."
while (-not (Test-Path -LiteralPath $SenderReadyFileLiteral)) {
  Start-Sleep -Milliseconds 250
}
Write-Host "[receiver] Sender ready; starting PCMR validation."
`$ArgsList = @{
  GodotExe = $GodotExeLiteral
  ValidateProxyTargets = `$true
  ProxyTargetsWsUrl = $WsUrlLiteral
  ProxyTargetsTimeoutSeconds = $ProxyTargetsTimeoutSeconds
}
if ($UseOverlayLiteral) {
  `$ArgsList["UseAntmanPassthroughOverlay"] = `$true
}
if ($KeepReceiverOpenLiteral) {
  `$ArgsList["KeepGodotOpen"] = `$true
}
& $PcmrRunnerLiteral @ArgsList *>&1 | Tee-Object -FilePath $ReceiverLogLiteral -Append
`$ExitCode = `$LASTEXITCODE
Write-Host "[receiver] PCMR receiver exited with code `$ExitCode"
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
`$MonitorArgs = @{
  Url = $WsUrlLiteral
  MinPackets = $MonitorMinPackets
  TimeoutSeconds = $MonitorTimeoutSeconds
  PythonExe = $PythonExeLiteral
}
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
Write-Host "[monitor] Running end-to-end health verdict: STREAM_OK / GODOT_NOT_CONNECTED / SAMPLE_FALLBACK_ACTIVE / CARD_BOUND_TO_LIVE_TARGET / LOW_CONFIDENCE_DEPTH_ONLY"
Write-Host "[monitor] Raw client diagnostics include: client_label / close_reason / packets_before_close"
Write-Host "[monitor] Godot/card pose summary includes: proxy_world_position / card_resolved_position / card_minus_proxy_world"
`$HealthArgs = @(
  $HealthValidatorLiteral,
  "--sender-log", $SenderLogLiteral,
  "--raw-status", $RawMonitorStatusFileLiteral,
  "--pcmr-status", $PcmrStatusFileLiteral,
  "--min-packets", "$MonitorMinPackets",
  "--timeout-seconds", "$ProxyTargetsTimeoutSeconds",
  "--output", $HealthStatusFileLiteral
)
& $PythonExeLiteral @HealthArgs *>&1 | Tee-Object -FilePath $MonitorLogLiteral -Append
`$HealthExitCode = `$LASTEXITCODE
Write-Host "[monitor] End-to-end health monitor exited with code `$HealthExitCode"
if (`$HealthExitCode -ne 0) {
  exit `$HealthExitCode
}
if (`$RawMonitorFailed) {
  exit `$RawMonitorExitCode
}
exit `$RawMonitorExitCode
"@

Set-Content -LiteralPath $SenderScript -Value $SenderContent -Encoding UTF8
Set-Content -LiteralPath $ReceiverScript -Value $ReceiverContent -Encoding UTF8
Set-Content -LiteralPath $MonitorScript -Value $MonitorContent -Encoding UTF8

Write-Host "SmartXR-PCMR stereo proxy_targets live manual validation"
Write-Host "This opens one Windows Terminal window with three tabs when wt.exe is available."
Write-Host "It falls back to three visible PowerShell windows otherwise."
Write-Host "WebSocket: $WsUrl"
Write-Host "Work dir:  $WorkDir"
Write-Host "Keep receiver Godot open: $KeepReceiverOpen"
Write-Host ""

Open-RunnerTab -WindowName $WindowName -Title "SmartXR stereo sender" -RunnerPath $SenderScript

Write-Host "Waiting for sender readiness: proxy_targets live publisher listening"
if (-not (Wait-ForLogText -Path $SenderLog -Text "proxy_targets live publisher listening" -TimeoutSeconds $SenderReadyTimeoutSeconds)) {
    $SenderLogTail = Get-LogTail -Path $SenderLog
    throw @"
Sender did not report ready within $SenderReadyTimeoutSeconds seconds.
Check: $SenderLog

Sender log tail:
$SenderLogTail
"@
}
Set-Content -LiteralPath $SenderReadyFile -Value "ready" -Encoding ASCII

Open-RunnerTab -WindowName $WindowName -Title "SmartXR PCMR receiver" -RunnerPath $ReceiverScript
Open-RunnerTab -WindowName $WindowName -Title "SmartXR proxy_targets monitor" -RunnerPath $MonitorScript

Write-Host ""
Write-Host "Started sender, receiver, and monitor."
Write-Host "Close the sender tab/window manually after real-device inspection is done."
if ($KeepReceiverOpen) {
    Write-Host "Close the receiver tab/window manually after visual card inspection is done."
}
Write-Host ""
Write-Host "Logs:"
Write-Host "  Sender:   $SenderLog"
Write-Host "  Receiver: $ReceiverLog"
Write-Host "  Monitor:  $MonitorLog"
Write-Host "  Health:   $HealthStatusFile"
Write-Host "  PCMR status copy: .tmp\windows_pcmr_proxy_targets\proxy_targets_live_status.json"
