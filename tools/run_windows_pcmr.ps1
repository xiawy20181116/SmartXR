param(
    [switch]$Editor,
    [switch]$ExportDebug,
    [switch]$ValidateProxyTargets,
    [switch]$KeepGodotOpen,
    [switch]$UseAntmanPassthroughOverlay,
    [string]$ProxyTargetsWsUrl = "ws://127.0.0.1:8766/proxy_targets",
    [double]$ProxyTargetsTimeoutSeconds = 15.0,
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
$ProjectDir = Join-Path $RepoRoot "godot-android"
$ExportPath = Join-Path $ProjectDir "builds\windows\SmartXR-PCMR.exe"
$GxrExtensionSwitch = Join-Path $PSScriptRoot "set_gxr_extension.ps1"
$StatusValidator = Join-Path $RepoRoot "tools\validate_proxy_targets_live_status.py"
$StatusFile = Join-Path $env:APPDATA "Godot\app_userdata\demo_run\proxy_targets_live_status.json"
$PassthroughOverlayStatusFile = Join-Path $env:APPDATA "Godot\app_userdata\demo_run\passthrough_overlay_status.json"
$WorkDir = Join-Path $RepoRoot ".tmp\windows_pcmr_proxy_targets"
$GodotLog = Join-Path $WorkDir "godot_pcmr.log"
$GodotErr = Join-Path $WorkDir "godot_pcmr.err.log"
$WorkDirStatusFile = Join-Path $WorkDir "proxy_targets_live_status.json"

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

if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "project.godot"))) {
    throw "Godot project not found: $ProjectDir"
}

if ($ValidateProxyTargets -and -not (Test-Path -LiteralPath $StatusValidator)) {
    throw "proxy_targets status validator not found: $StatusValidator"
}

Write-Host "SmartXR-PCMR Windows validation"
Write-Host "Before running in PCMR, start SteamVR / WMR / Meta Link and make it the active OpenXR runtime."
Write-Host "Project: $ProjectDir"
Write-Host "ProxyTargets WS: $ProxyTargetsWsUrl"
if ($ValidateProxyTargets) {
    Write-Host "SmartXR-PCMR proxy_targets live validation"
    Write-Host "Status file: $StatusFile"
    Write-Host "Timeout: $ProxyTargetsTimeoutSeconds seconds"
    Write-Host "Publisher: external/already running; this script does not start one."
    if ($KeepGodotOpen) {
        Write-Host "Keep running: Godot stays open after attached validation succeeds."
    }
}
if ($UseAntmanPassthroughOverlay) {
    Write-Host "SmartXR-PCMR Antman passthrough overlay"
    Write-Host "Passthrough overlay status file: $PassthroughOverlayStatusFile"
}

& $GxrExtensionSwitch -Mode disable -ProjectDir $ProjectDir
$ExitCode = 0
$OldProxyTargetsWsUrl = $env:PROXY_TARGETS_WS_URL
$OldPassthroughOverlay = $env:SMARTXR_USE_PASSTHROUGH_OVERLAY
$OldStatusHudVisible = $env:SMARTXR_STATUS_HUD_VISIBLE
$GodotProcess = $null

try {
    $env:PROXY_TARGETS_WS_URL = $ProxyTargetsWsUrl
    if ($ValidateProxyTargets -and [string]::IsNullOrWhiteSpace($env:SMARTXR_STATUS_HUD_VISIBLE)) {
        $env:SMARTXR_STATUS_HUD_VISIBLE = "0"
    }
    if ($UseAntmanPassthroughOverlay) {
        $env:SMARTXR_USE_PASSTHROUGH_OVERLAY = "1"
        Remove-Item -LiteralPath $PassthroughOverlayStatusFile -Force -ErrorAction SilentlyContinue
    } else {
        Remove-Item "Env:\SMARTXR_USE_PASSTHROUGH_OVERLAY" -ErrorAction SilentlyContinue
    }

    if ($ExportDebug) {
        $BuildDir = Split-Path -Parent $ExportPath
        New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
        & $GodotExe --headless --path $ProjectDir --export-debug "Windows Desktop" $ExportPath
        $ExitCode = $LASTEXITCODE
    } elseif ($Editor) {
        & $GodotExe --editor --path $ProjectDir
        $ExitCode = $LASTEXITCODE
    } elseif ($ValidateProxyTargets) {
        New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
        Remove-Item -LiteralPath $GodotLog, $GodotErr, $StatusFile, $WorkDirStatusFile -Force -ErrorAction SilentlyContinue

        $GodotProcess = Start-Process `
            -FilePath $GodotExe `
            -ArgumentList @("--path", $ProjectDir) `
            -WorkingDirectory $RepoRoot `
            -RedirectStandardOutput $GodotLog `
            -RedirectStandardError $GodotErr `
            -PassThru

        python $StatusValidator `
            --status-file $StatusFile `
            --require attached `
            --timeout $ProxyTargetsTimeoutSeconds
        $ExitCode = $LASTEXITCODE
        if (Test-Path -LiteralPath $StatusFile) {
            Copy-Item -LiteralPath $StatusFile -Destination $WorkDirStatusFile -Force
        }
    } else {
        & $GodotExe --path $ProjectDir
        $ExitCode = $LASTEXITCODE
    }
} finally {
    if (-not $KeepGodotOpen) {
        Stop-ChildProcess -Process $GodotProcess
    }
    Restore-EnvVar -Name "PROXY_TARGETS_WS_URL" -Value $OldProxyTargetsWsUrl
    Restore-EnvVar -Name "SMARTXR_USE_PASSTHROUGH_OVERLAY" -Value $OldPassthroughOverlay
    Restore-EnvVar -Name "SMARTXR_STATUS_HUD_VISIBLE" -Value $OldStatusHudVisible
    & $GxrExtensionSwitch -Mode enable -ProjectDir $ProjectDir

    if ($ValidateProxyTargets -or $UseAntmanPassthroughOverlay) {
        Write-Host ""
        Write-Host "Logs:"
        Write-Host "  Godot stdout: $GodotLog"
        Write-Host "  Godot stderr: $GodotErr"
        if ($ValidateProxyTargets) {
            Write-Host "  Status JSON:  $StatusFile"
            Write-Host "  Status JSON copy: $WorkDirStatusFile"
        }
        if ($UseAntmanPassthroughOverlay) {
            Write-Host "  Passthrough overlay JSON: $PassthroughOverlayStatusFile"
        }
    }
}

exit $ExitCode
