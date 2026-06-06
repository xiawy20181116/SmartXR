param(
    [switch]$Editor,
    [switch]$ExportDebug
)

$ErrorActionPreference = "Stop"

$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ProjectDir = Join-Path $RepoRoot "godot-android"
$ExportPath = Join-Path $ProjectDir "builds\windows\SmartXR-PCMR.exe"
$GxrExtensionSwitch = Join-Path $PSScriptRoot "set_gxr_extension.ps1"

if (-not (Test-Path -LiteralPath $GodotExe)) {
    throw "Godot executable not found: $GodotExe"
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "project.godot"))) {
    throw "Godot project not found: $ProjectDir"
}

Write-Host "SmartXR-PCMR Windows validation"
Write-Host "Before running in PCMR, start SteamVR / WMR / Meta Link and make it the active OpenXR runtime."
Write-Host "Project: $ProjectDir"

& $GxrExtensionSwitch -Mode disable -ProjectDir $ProjectDir
$ExitCode = 0

try {
    if ($ExportDebug) {
        $BuildDir = Split-Path -Parent $ExportPath
        New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
        & $GodotExe --headless --path $ProjectDir --export-debug "Windows Desktop" $ExportPath
        $ExitCode = $LASTEXITCODE
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
