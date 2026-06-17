param(
    [string]$PythonExe = "python",
    [string]$HostName = "127.0.0.1",
    [int]$C1Port = 8770,
    [int]$ProxyPort = 8766,
    [double]$Hz = 60.0,
    [int]$MinPackets = 60,
    [double]$TimeoutSeconds = 15.0,
    [string]$Source = ""
)

# Dependency-free closed loop for the full module-3 PC chain, no device:
#   C1 replay publisher -> module-3 bridge (C1->C2 align) -> proxy_targets monitor
# and assert the proxy_targets stream the Godot card would consume is healthy.
# The full NV12 -> ncnn front end is tools\run_tracking_raw_live_publisher.py.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\mr_integration_bridge_harness"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "proxy_targets_status.json"
$C1Log = Join-Path -Path $WorkDir -ChildPath "c1_publisher.log"
$BridgeLog = Join-Path -Path $WorkDir -ChildPath "bridge.log"
if ($Source -eq "") {
    $Source = Join-Path -Path $RepoRoot -ChildPath "godot-android\fixtures\tracking_raw_replay_detections.jsonl"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $StatusFile -Force -ErrorAction SilentlyContinue

$C1Url = "ws://${HostName}:${C1Port}/tracking_raw"
$ProxyUrl = "ws://${HostName}:${ProxyPort}/proxy_targets"
Write-Host "SmartXR module-3 bridge harness"
Write-Host "C1 source:        $C1Url ($Source)"
Write-Host "proxy_targets:    $ProxyUrl"
Write-Host "Min packets:      $MinPackets"
Write-Host ""

function Stop-ChildProcess {
    param($Process)
    if ($null -ne $Process -and -not $Process.HasExited) {
        try { $Process.Kill(); $Process.WaitForExit(3000) | Out-Null }
        catch { Write-Warning "Failed to stop process $($Process.Id): $_" }
    }
}

$Publisher = $null
$Bridge = $null
try {
    $publisherArgs = @(
        "-m", "smartxr.cli.tracking_raw_publisher",
        "--host", $HostName, "--port", "$C1Port", "--hz", "$Hz",
        "--source", $Source, "--log-every", "0"
    )
    $Publisher = Start-Process -FilePath $PythonExe -ArgumentList $publisherArgs `
        -WorkingDirectory $RepoRoot -PassThru -NoNewWindow `
        -RedirectStandardOutput $C1Log -RedirectStandardError "$C1Log.err"
    Start-Sleep -Milliseconds 800

    $bridgeArgs = @(
        "-m", "smartxr.cli.mr_integration_bridge",
        "--host", $HostName, "--port", "$ProxyPort",
        "--c1-url", $C1Url, "--log-every", "0"
    )
    $Bridge = Start-Process -FilePath $PythonExe -ArgumentList $bridgeArgs `
        -WorkingDirectory $RepoRoot -PassThru -NoNewWindow `
        -RedirectStandardOutput $BridgeLog -RedirectStandardError "$BridgeLog.err"
    Start-Sleep -Milliseconds 800

    & $PythonExe tools\monitor_proxy_targets_live_stream.py `
        --url $ProxyUrl --min-packets "$MinPackets" --timeout-seconds "$TimeoutSeconds" --output $StatusFile
    $ExitCode = $LASTEXITCODE
} finally {
    Stop-ChildProcess -Process $Bridge
    Stop-ChildProcess -Process $Publisher
}

Write-Host ""
Write-Host "Harness exit code: $ExitCode"
Write-Host "Status JSON: $StatusFile"
exit $ExitCode
