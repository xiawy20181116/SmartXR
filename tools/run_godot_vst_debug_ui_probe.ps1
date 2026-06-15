param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for the VSTDebugUI subsystem. Runs the script-only
# probe headless in no-project mode.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_vst_debug_ui_probe.gd"
$VSTDebugUIScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\vst_debug_ui.gd"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\vst_debug_ui_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "vst_debug_ui_probe_status.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_vst_debug_ui_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_vst_debug_ui_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $VSTDebugUIScript)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -Path $StatusFile -ErrorAction SilentlyContinue

$OldScript = $env:SMARTXR_VST_DEBUG_UI_SCRIPT
$OldStatusPath = $env:SMARTXR_VST_DEBUG_UI_PROBE_STATUS_PATH
$env:SMARTXR_VST_DEBUG_UI_SCRIPT = ([System.IO.Path]::GetFullPath($VSTDebugUIScript)).Replace("\", "/")
$env:SMARTXR_VST_DEBUG_UI_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
try {
    $Process = Start-Process -FilePath $GodotExe -ArgumentList @(
        "--headless",
        "--script", $ProbeScript
    ) -WorkingDirectory $RepoRoot -NoNewWindow -PassThru `
        -RedirectStandardOutput $GodotLog -RedirectStandardError $GodotErrLog
    $null = $Process.Handle

    if (-not $Process.WaitForExit([int]($ProcessTimeoutSeconds * 1000))) {
        $Process.Kill()
        Write-Error "Godot probe timed out after $ProcessTimeoutSeconds seconds"
    }
    $ExitCode = $Process.ExitCode
} finally {
    if ($null -eq $OldScript) { Remove-Item Env:\SMARTXR_VST_DEBUG_UI_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_VST_DEBUG_UI_SCRIPT = $OldScript }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_VST_DEBUG_UI_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_VST_DEBUG_UI_PROBE_STATUS_PATH = $OldStatusPath }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "vst debug ui probe FAILED (exit $ExitCode)"
}
Write-Host "vst debug ui probe PASSED"
