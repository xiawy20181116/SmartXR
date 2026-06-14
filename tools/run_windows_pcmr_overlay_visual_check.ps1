param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$PythonExe = "python",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8767,
    [ValidateSet("moving", "static")]
    [string]$Mode = "moving",
    [double]$Hz = 20.0,
    [int]$LogEvery = 20
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProjectDir = Join-Path -Path $RepoRoot -ChildPath "godot-android"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\windows_pcmr_overlay_visual_check"
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\fake_proxy_targets_publisher.py"
$GxrExtensionSwitch = Join-Path -Path $RepoRoot -ChildPath "tools\set_gxr_extension.ps1"
$PublisherLog = Join-Path -Path $WorkDir -ChildPath "fake_proxy_targets_publisher.log"
$PublisherErr = Join-Path -Path $WorkDir -ChildPath "fake_proxy_targets_publisher.err.log"
$PassthroughOverlayStatusFile = Join-Path -Path $env:APPDATA -ChildPath "Godot\app_userdata\demo_run\passthrough_overlay_status.json"
$ProxyTargetsStatusFile = Join-Path -Path $env:APPDATA -ChildPath "Godot\app_userdata\demo_run\proxy_targets_live_status.json"
$ProxyTargetsWsUrl = "ws://${HostName}:${Port}/proxy_targets"

function Restore-EnvVar {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [AllowNull()]
        $Value
    )

    if ($null -eq $Value) {
        Remove-Item "Env:\$Name" -ErrorAction SilentlyContinue
    } else {
        Set-Item "Env:\$Name" $Value
    }
}

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

if (-not (Test-Path -LiteralPath $GodotExe)) {
    throw "Godot executable not found: $GodotExe"
}
if (-not (Test-Path -LiteralPath (Join-Path -Path $ProjectDir -ChildPath "project.godot"))) {
    throw "Godot project not found: $ProjectDir"
}
if (-not (Test-Path -LiteralPath $Publisher)) {
    throw "fake proxy_targets publisher not found: $Publisher"
}
if (-not (Test-Path -LiteralPath $GxrExtensionSwitch)) {
    throw "GXR extension switch not found: $GxrExtensionSwitch"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $PublisherLog, $PublisherErr, $PassthroughOverlayStatusFile, $ProxyTargetsStatusFile -Force -ErrorAction SilentlyContinue

$OldProxyTargetsWsUrl = $env:PROXY_TARGETS_WS_URL
$OldPassthroughOverlay = $env:SMARTXR_USE_PASSTHROUGH_OVERLAY
$PublisherProcess = $null
$ExitCode = 1

Write-Host "SmartXR-PCMR overlay visual check"
Write-Host "Project: $ProjectDir"
Write-Host "Publisher: $ProxyTargetsWsUrl"
Write-Host "Work dir: $WorkDir"
Write-Host "This script keeps Godot open until you close the Godot window or press Ctrl+C."
Write-Host "Expected headset view: translucent green PASSTHROUGH OVERLAY panel in front of you."

try {
    & $GxrExtensionSwitch -Mode disable -ProjectDir $ProjectDir

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

    $env:PROXY_TARGETS_WS_URL = $ProxyTargetsWsUrl
    $env:SMARTXR_USE_PASSTHROUGH_OVERLAY = "1"

    & $GodotExe --path $ProjectDir
    $ExitCode = $LASTEXITCODE
} finally {
    Stop-ChildProcess -Process $PublisherProcess
    Restore-EnvVar -Name "PROXY_TARGETS_WS_URL" -Value $OldProxyTargetsWsUrl
    Restore-EnvVar -Name "SMARTXR_USE_PASSTHROUGH_OVERLAY" -Value $OldPassthroughOverlay
    & $GxrExtensionSwitch -Mode enable -ProjectDir $ProjectDir

    Write-Host ""
    Write-Host "Logs:"
    Write-Host "  Publisher stdout: $PublisherLog"
    Write-Host "  Publisher stderr: $PublisherErr"
    Write-Host "  Passthrough overlay JSON: $PassthroughOverlayStatusFile"
    Write-Host "  Proxy targets JSON: $ProxyTargetsStatusFile"
}

exit $ExitCode
