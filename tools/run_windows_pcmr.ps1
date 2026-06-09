param(
    [switch]$Editor,
    [switch]$ExportDebug,
    [switch]$ValidateProxyTargets,
    [string]$ProxyTargetsWsUrl = "ws://127.0.0.1:8766/proxy_targets",
    [int]$ProxyTargetsTimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"

$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ProjectDir = Join-Path $RepoRoot "godot-android"
$ExportPath = Join-Path $ProjectDir "builds\windows\SmartXR-PCMR.exe"
$GxrExtensionSwitch = Join-Path $PSScriptRoot "set_gxr_extension.ps1"
$ProxyTargetsStatusValidator = Join-Path $PSScriptRoot "validate_proxy_targets_live_status.py"
$ProxyTargetsStatusFile = Join-Path $env:APPDATA "Godot\app_userdata\demo_run\proxy_targets_live_status.json"

if (-not (Test-Path -LiteralPath $GodotExe)) {
    throw "Godot executable not found: $GodotExe"
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "project.godot"))) {
    throw "Godot project not found: $ProjectDir"
}

Write-Host "SmartXR-PCMR Windows validation"
Write-Host "Before running in PCMR, start SteamVR / WMR / Meta Link and make it the active OpenXR runtime."
Write-Host "Project: $ProjectDir"
if ($ValidateProxyTargets) {
    Write-Host "SmartXR-PCMR proxy_targets live validation"
    Write-Host "ProxyTargets WS: $ProxyTargetsWsUrl"
    Write-Host "Status file: $ProxyTargetsStatusFile"
    Write-Host "Timeout: $ProxyTargetsTimeoutSeconds seconds"
    Write-Host "Publisher: external/already running; this script does not start one."
}

& $GxrExtensionSwitch -Mode disable -ProjectDir $ProjectDir
$ExitCode = 0

try {
    if ($ExportDebug) {
        $BuildDir = Split-Path -Parent $ExportPath
        New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
        & $GodotExe --headless --path $ProjectDir --export-debug "Windows Desktop" $ExportPath
        $ExitCode = $LASTEXITCODE
    } elseif ($ValidateProxyTargets) {
        if (Test-Path -LiteralPath $ProxyTargetsStatusFile) {
            Remove-Item -LiteralPath $ProxyTargetsStatusFile -Force
        }
        $PreviousProxyTargetsWsUrl = $env:PROXY_TARGETS_WS_URL
        $env:PROXY_TARGETS_WS_URL = $ProxyTargetsWsUrl
        $Process = $null
        try {
            $Process = Start-Process -FilePath $GodotExe -ArgumentList @("--path", $ProjectDir) -PassThru -WindowStyle Hidden
            python $ProxyTargetsStatusValidator `
                --status-file $ProxyTargetsStatusFile `
                --timeout-seconds $ProxyTargetsTimeoutSeconds `
                --require live `
                --require-card-apply
            $ExitCode = $LASTEXITCODE
        } finally {
            if ($null -ne $Process -and -not $Process.HasExited) {
                Stop-Process -Id $Process.Id -Force
            }
            $env:PROXY_TARGETS_WS_URL = $PreviousProxyTargetsWsUrl
        }
    } elseif ($Editor) {
        & $GodotExe --editor --path $ProjectDir
        $ExitCode = $LASTEXITCODE
    } else {
        & $GodotExe --path $ProjectDir
        $ExitCode = $LASTEXITCODE
    }
} finally {
    & $GxrExtensionSwitch -Mode enable -ProjectDir $ProjectDir
}

exit $ExitCode
