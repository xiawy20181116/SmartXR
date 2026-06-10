param(
    [switch]$Release
)

$ErrorActionPreference = "Stop"

$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ProjectDir = Join-Path $RepoRoot "godot-android"
$ExportPath = Join-Path $ProjectDir "builds\SmartXR-Godot-Control.apk"
$GxrExtensionSwitch = Join-Path $PSScriptRoot "set_gxr_extension.ps1"

if (-not (Test-Path -LiteralPath $GodotExe)) {
    throw "Godot executable not found: $GodotExe"
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "project.godot"))) {
    throw "Godot project not found: $ProjectDir"
}

& $GxrExtensionSwitch -Mode enable -ProjectDir $ProjectDir

$BuildDir = Split-Path -Parent $ExportPath
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

if ($Release) {
    & $GodotExe --headless --path $ProjectDir --export-release "Android" $ExportPath
} else {
    & $GodotExe --headless --path $ProjectDir --export-debug "Android" $ExportPath
}

exit $LASTEXITCODE
