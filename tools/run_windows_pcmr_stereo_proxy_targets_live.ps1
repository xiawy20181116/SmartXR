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
    [double]$ProxyTargetsTimeoutSeconds = 60.0,
    [int]$MonitorMinPackets = 10,
    [double]$MonitorTimeoutSeconds = 20.0,
    [int]$MonitorStartDelaySeconds = 2,
    [switch]$UseAntmanPassthroughOverlay,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\antman_vst_stereo_proxy_targets_live_publisher.py"
$PcmrRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_windows_pcmr.ps1"
$MonitorRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_proxy_targets_live_monitor.ps1"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\windows_pcmr_stereo_proxy_targets_live"
$SenderScript = Join-Path -Path $WorkDir -ChildPath "sender.ps1"
$ReceiverScript = Join-Path -Path $WorkDir -ChildPath "receiver.ps1"
$MonitorScript = Join-Path -Path $WorkDir -ChildPath "monitor.ps1"
$SenderLog = Join-Path -Path $WorkDir -ChildPath "sender.log"
$ReceiverLog = Join-Path -Path $WorkDir -ChildPath "receiver.log"
$MonitorLog = Join-Path -Path $WorkDir -ChildPath "monitor.log"
$WsUrl = "ws://${HostName}:${Port}/proxy_targets"

function ConvertTo-PowerShellLiteral {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Start-VisiblePowerShellWindow {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath
    )

    Start-Process `
        -FilePath "powershell" `
        -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Normal | Out-Null
    Write-Host "Opened $Title window: $ScriptPath"
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

foreach ($RequiredPath in @($Publisher, $PcmrRunner, $MonitorRunner)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required file not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $SenderLog, $ReceiverLog, $MonitorLog -Force -ErrorAction SilentlyContinue

$RepoRootLiteral = ConvertTo-PowerShellLiteral $RepoRoot
$PythonExeLiteral = ConvertTo-PowerShellLiteral $PythonExe
$PublisherLiteral = ConvertTo-PowerShellLiteral $Publisher
$PcmrRunnerLiteral = ConvertTo-PowerShellLiteral $PcmrRunner
$MonitorRunnerLiteral = ConvertTo-PowerShellLiteral $MonitorRunner
$AntmanRootLiteral = ConvertTo-PowerShellLiteral $AntmanRoot
$GodotExeLiteral = ConvertTo-PowerShellLiteral $GodotExe
$WsUrlLiteral = ConvertTo-PowerShellLiteral $WsUrl
$SenderLogLiteral = ConvertTo-PowerShellLiteral $SenderLog
$ReceiverLogLiteral = ConvertTo-PowerShellLiteral $ReceiverLog
$MonitorLogLiteral = ConvertTo-PowerShellLiteral $MonitorLog
$UseOverlayLiteral = if ($UseAntmanPassthroughOverlay) { "`$true" } else { "`$false" }

$SenderContent = @"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $RepoRootLiteral
Write-Host "SmartXR stereo sender"
Write-Host "WebSocket: $WsUrl"
Write-Host "Expected depth_source=bbox_top_center_fallback depth_confidence=low"
& $PythonExeLiteral $PublisherLiteral `
  --antman-root $AntmanRootLiteral `
  --host $HostName `
  --port $Port `
  --hz $Hz `
  --min-confidence $MinConfidence `
  --recorded-width $RecordedWidth `
  --recorded-height $RecordedHeight `
  --log-every $LogEvery 2>&1 | Tee-Object -FilePath $SenderLogLiteral
`$ExitCode = `$LASTEXITCODE
Write-Host "Stereo sender exited with code `$ExitCode"
exit `$ExitCode
"@

$ReceiverContent = @"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $RepoRootLiteral
Write-Host "SmartXR PCMR receiver"
Write-Host "Using proxy_targets: $WsUrl"
Write-Host "Keep the sender window open; receiver needs the sender to stay open."
`$ArgsList = @(
  "-GodotExe", $GodotExeLiteral,
  "-ValidateProxyTargets",
  "-ProxyTargetsWsUrl", $WsUrlLiteral,
  "-ProxyTargetsTimeoutSeconds", "$ProxyTargetsTimeoutSeconds"
)
if ($UseOverlayLiteral) {
  `$ArgsList += "-UseAntmanPassthroughOverlay"
}
& $PcmrRunnerLiteral @ArgsList 2>&1 | Tee-Object -FilePath $ReceiverLogLiteral
`$ExitCode = `$LASTEXITCODE
Write-Host "PCMR receiver exited with code `$ExitCode"
exit `$ExitCode
"@

$MonitorContent = @"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $RepoRootLiteral
Write-Host "SmartXR proxy_targets monitor"
Write-Host "Waiting $MonitorStartDelaySeconds seconds for sender/receiver startup..."
Start-Sleep -Seconds $MonitorStartDelaySeconds
& $MonitorRunnerLiteral `
  -Url $WsUrlLiteral `
  -MinPackets $MonitorMinPackets `
  -TimeoutSeconds $MonitorTimeoutSeconds `
  -PythonExe $PythonExeLiteral 2>&1 | Tee-Object -FilePath $MonitorLogLiteral
`$ExitCode = `$LASTEXITCODE
Write-Host "Monitor exited with code `$ExitCode"
exit `$ExitCode
"@

Set-Content -LiteralPath $SenderScript -Value $SenderContent -Encoding UTF8
Set-Content -LiteralPath $ReceiverScript -Value $ReceiverContent -Encoding UTF8
Set-Content -LiteralPath $MonitorScript -Value $MonitorContent -Encoding UTF8

Write-Host "SmartXR-PCMR stereo proxy_targets live manual validation"
Write-Host "This opens three visible PowerShell windows:"
Write-Host "  1. SmartXR stereo sender"
Write-Host "  2. SmartXR PCMR receiver"
Write-Host "  3. SmartXR proxy_targets monitor"
Write-Host "WebSocket: $WsUrl"
Write-Host "Work dir:  $WorkDir"
Write-Host ""
Write-Host "Close the sender window manually after real-device inspection is done."

Start-VisiblePowerShellWindow -Title "SmartXR stereo sender" -ScriptPath $SenderScript
Start-Sleep -Seconds 1
Start-VisiblePowerShellWindow -Title "SmartXR PCMR receiver" -ScriptPath $ReceiverScript
Start-VisiblePowerShellWindow -Title "SmartXR proxy_targets monitor" -ScriptPath $MonitorScript

Write-Host ""
Write-Host "Logs:"
Write-Host "  Sender:   $SenderLog"
Write-Host "  Receiver: $ReceiverLog"
Write-Host "  Monitor:  $MonitorLog"
Write-Host "  PCMR status copy: .tmp\windows_pcmr_proxy_targets\proxy_targets_live_status.json"
