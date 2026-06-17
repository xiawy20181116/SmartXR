param(
    [string]$PythonExe = "python",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8770,
    [double]$Hz = 60.0,
    [int]$MinPackets = 60,
    [double]$TimeoutSeconds = 15.0,
    [string]$Source = ""
)

# Dependency-free closed loop for the live C1 (tracking_raw) chain, no device:
# start the recorded-detections replay publisher, then run the consumer harness
# and assert the C1 stream is healthy. The full NV12 -> ncnn chain is
# tools\run_tracking_raw_live_publisher.py (optional numpy/opencv/ncnn).

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\tracking_raw_live_harness"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "tracking_raw_live_status.json"
$PublisherLog = Join-Path -Path $WorkDir -ChildPath "publisher.log"
if ($Source -eq "") {
    $Source = Join-Path -Path $RepoRoot -ChildPath "godot-android\fixtures\tracking_raw_replay_detections.jsonl"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $StatusFile -Force -ErrorAction SilentlyContinue

$Url = "ws://${HostName}:${Port}/tracking_raw"
Write-Host "SmartXR tracking_raw (C1) live harness"
Write-Host "Publisher source: $Source"
Write-Host "WebSocket:        $Url"
Write-Host "Min packets:      $MinPackets"
Write-Host ""

function Stop-ChildProcess {
    param($Process)
    if ($null -ne $Process -and -not $Process.HasExited) {
        try { $Process.Kill(); $Process.WaitForExit(3000) | Out-Null }
        catch { Write-Warning "Failed to stop publisher $($Process.Id): $_" }
    }
}

$Publisher = $null
try {
    $publisherArgs = @(
        "-m", "smartxr.cli.tracking_raw_publisher",
        "--host", $HostName, "--port", "$Port", "--hz", "$Hz",
        "--source", $Source, "--log-every", "0"
    )
    $Publisher = Start-Process -FilePath $PythonExe -ArgumentList $publisherArgs `
        -WorkingDirectory $RepoRoot -PassThru -NoNewWindow `
        -RedirectStandardOutput $PublisherLog -RedirectStandardError "$PublisherLog.err"
    Start-Sleep -Milliseconds 800

    & $PythonExe -m smartxr.cli.tracking_raw_monitor `
        --url $Url --min-packets "$MinPackets" --timeout-seconds "$TimeoutSeconds" --output $StatusFile
    $ExitCode = $LASTEXITCODE
} finally {
    Stop-ChildProcess -Process $Publisher
}

Write-Host ""
Write-Host "Harness exit code: $ExitCode"
Write-Host "Status JSON: $StatusFile"
exit $ExitCode
