param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for StatusHud (M3 step 1, YAN-74).
# Runs the script-only probe headless in NO-PROJECT mode, like the other
# script-only probes: loading the project (--path) would boot the full main
# scene, which reconnects WebSockets forever and never exits headless.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_status_hud_probe.gd"
$HudScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\status_hud.gd"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\status_hud_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "status_hud_probe_status.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_status_hud_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_status_hud_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $HudScript)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -Path $StatusFile -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path -Path $WorkDir -ChildPath "proxy_targets_live_status.json") -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path -Path $WorkDir -ChildPath "passthrough_overlay_status.json") -ErrorAction SilentlyContinue

$OldHudScript = $env:SMARTXR_STATUS_HUD_SCRIPT
$OldStatusPath = $env:SMARTXR_STATUS_HUD_PROBE_STATUS_PATH
$OldWorkDir = $env:SMARTXR_STATUS_HUD_PROBE_WORK_DIR
$env:SMARTXR_STATUS_HUD_SCRIPT = ([System.IO.Path]::GetFullPath($HudScript)).Replace("\", "/")
$env:SMARTXR_STATUS_HUD_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
$env:SMARTXR_STATUS_HUD_PROBE_WORK_DIR = ([System.IO.Path]::GetFullPath($WorkDir)).Replace("\", "/")
try {
    $Process = Start-Process -FilePath $GodotExe -ArgumentList @(
        "--headless",
        "--script", $ProbeScript
    ) -WorkingDirectory $RepoRoot -NoNewWindow -PassThru `
        -RedirectStandardOutput $GodotLog -RedirectStandardError $GodotErrLog
    $null = $Process.Handle  # cache handle so .ExitCode is readable after exit

    if (-not $Process.WaitForExit([int]($ProcessTimeoutSeconds * 1000))) {
        $Process.Kill()
        Write-Error "Godot probe timed out after $ProcessTimeoutSeconds seconds"
    }
    $ExitCode = $Process.ExitCode
} finally {
    if ($null -eq $OldHudScript) { Remove-Item Env:\SMARTXR_STATUS_HUD_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_STATUS_HUD_SCRIPT = $OldHudScript }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_STATUS_HUD_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_STATUS_HUD_PROBE_STATUS_PATH = $OldStatusPath }
    if ($null -eq $OldWorkDir) { Remove-Item Env:\SMARTXR_STATUS_HUD_PROBE_WORK_DIR -ErrorAction SilentlyContinue } else { $env:SMARTXR_STATUS_HUD_PROBE_WORK_DIR = $OldWorkDir }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "status hud probe FAILED (exit $ExitCode)"
}
Write-Host "status hud probe PASSED"
