param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$PythonExe = "python",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8767,
    [ValidateSet("moving", "static")]
    [string]$Mode = "moving",
    [double]$Hz = 20.0,
    [int]$LogEvery = 20,
    [double]$ProxyTargetsTimeoutSeconds = 30.0,
    [switch]$UseAntmanPassthroughOverlay
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\windows_pcmr_proxy_targets_live"
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\fake_proxy_targets_publisher.py"
$PcmrRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_windows_pcmr.ps1"
$PublisherLog = Join-Path -Path $WorkDir -ChildPath "fake_proxy_targets_publisher.log"
$PublisherErr = Join-Path -Path $WorkDir -ChildPath "fake_proxy_targets_publisher.err.log"
$ProxyTargetsWsUrl = "ws://${HostName}:${Port}/proxy_targets"

function Stop-ChildProcess {
    param($Process)

    if ($null -ne $Process -and -not $Process.HasExited) {
        try {
            $Process.Kill()
            $Process.WaitForExit(3000) | Out-Null
        } catch {
            Write-Warning "Failed to stop process $($Process.Id): $_"
        }
    }
}

if (-not (Test-Path -LiteralPath $Publisher)) {
    throw "fake proxy_targets publisher not found: $Publisher"
}
if (-not (Test-Path -LiteralPath $PcmrRunner)) {
    throw "PCMR runner not found: $PcmrRunner"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $PublisherLog, $PublisherErr -Force -ErrorAction SilentlyContinue

$PublisherProcess = $null
$ExitCode = 1

Write-Host "SmartXR-PCMR proxy_targets live validation with managed fake publisher"
Write-Host "Publisher: $ProxyTargetsWsUrl"
Write-Host "Work dir: $WorkDir"

try {
    $PublisherArgs = @(
        $Publisher,
        "--host", $HostName,
        "--port", [string]$Port,
        "--mode", $Mode,
        "--hz", [string]$Hz,
        "--log-every", [string]$LogEvery
    )

    $PublisherProcess = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList $PublisherArgs `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $PublisherLog `
        -RedirectStandardError $PublisherErr `
        -PassThru

    Start-Sleep -Milliseconds 750
    if ($PublisherProcess.HasExited) {
        throw "fake proxy_targets publisher exited early with code $($PublisherProcess.ExitCode)"
    }

    $PcmrArgs = @(
        "-ExecutionPolicy", "Bypass",
        "-File", $PcmrRunner,
        "-GodotExe", $GodotExe,
        "-ValidateProxyTargets",
        "-ProxyTargetsWsUrl", $ProxyTargetsWsUrl,
        "-ProxyTargetsTimeoutSeconds", [string]$ProxyTargetsTimeoutSeconds
    )
    if ($UseAntmanPassthroughOverlay) {
        $PcmrArgs += "-UseAntmanPassthroughOverlay"
    }

    & powershell @PcmrArgs
    $ExitCode = $LASTEXITCODE
} finally {
    Stop-ChildProcess -Process $PublisherProcess

    Write-Host ""
    Write-Host "Logs:"
    Write-Host "  Publisher stdout: $PublisherLog"
    Write-Host "  Publisher stderr: $PublisherErr"
}

exit $ExitCode
