param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$ProjectDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")) "godot-android")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $GodotExe)) {
    Write-Error "Godot executable not found: $GodotExe"
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "project.godot"))) {
    Write-Error "Godot project not found: $ProjectDir"
}

& (Join-Path $PSScriptRoot "set_gxr_extension.ps1") -Mode disable -ProjectDir $ProjectDir

$OldSimMode = $env:SMARTXR_SIM_MODE
$env:SMARTXR_SIM_MODE = "1"
try {
    Start-Process -FilePath $GodotExe -ArgumentList @(
        "--path", $ProjectDir
    ) -WorkingDirectory $ProjectDir -Wait
} finally {
    if ($null -eq $OldSimMode) {
        Remove-Item Env:\SMARTXR_SIM_MODE -ErrorAction SilentlyContinue
    } else {
        $env:SMARTXR_SIM_MODE = $OldSimMode
    }
    & (Join-Path $PSScriptRoot "set_gxr_extension.ps1") -Mode enable -ProjectDir $ProjectDir
}
