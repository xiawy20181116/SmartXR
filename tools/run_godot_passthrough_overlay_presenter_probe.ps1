param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for the passthrough overlay presenter subsystem. Runs
# the script-only probe headless in no-project mode.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_passthrough_overlay_presenter_probe.gd"
$PresenterScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\passthrough_overlay_presenter.gd"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\passthrough_overlay_presenter_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "passthrough_overlay_presenter_probe_status.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_passthrough_overlay_presenter_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_passthrough_overlay_presenter_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $PresenterScript)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -Path $StatusFile -ErrorAction SilentlyContinue

$OldScript = $env:SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_SCRIPT
$OldStatusPath = $env:SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_PROBE_STATUS_PATH
$env:SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_SCRIPT = ([System.IO.Path]::GetFullPath($PresenterScript)).Replace("\", "/")
$env:SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
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
    if ($null -eq $OldScript) { Remove-Item Env:\SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_SCRIPT = $OldScript }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_PROBE_STATUS_PATH = $OldStatusPath }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "passthrough overlay presenter probe FAILED (exit $ExitCode)"
}
Write-Host "passthrough overlay presenter probe PASSED"
