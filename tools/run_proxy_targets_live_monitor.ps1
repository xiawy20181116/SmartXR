param(
    [string]$Url = "ws://127.0.0.1:8766/proxy_targets",
    [int]$MinPackets = 5,
    [double]$TimeoutSeconds = 10.0,
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$Monitor = Join-Path -Path $RepoRoot -ChildPath "tools\monitor_proxy_targets_live_stream.py"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\proxy_targets_live_monitor"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "proxy_targets_live_monitor_status.json"

if (-not (Test-Path -LiteralPath $Monitor)) {
    throw "Monitor script not found: $Monitor"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $StatusFile -Force -ErrorAction SilentlyContinue

Write-Host "SmartXR proxy_targets live stream monitor"
Write-Host "WebSocket:   $Url"
Write-Host "Min packets: $MinPackets"
Write-Host "Timeout:     $TimeoutSeconds seconds"
Write-Host "Status file: $StatusFile"
Write-Host "OpenXR:      not required"
Write-Host ""

& $PythonExe $Monitor `
    --url $Url `
    --min-packets "$MinPackets" `
    --timeout-seconds "$TimeoutSeconds" `
    --output $StatusFile

$ExitCode = $LASTEXITCODE
Write-Host ""
Write-Host "Monitor exit code: $ExitCode"
Write-Host "Status JSON: $StatusFile"
exit $ExitCode
