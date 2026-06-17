param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for the tracked-target card View seam
# (tracked_target_card_view.gd, composing card_view.gd +
# passthrough_overlay_presenter.gd). Runs in no-project mode.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_tracked_target_card_view_probe.gd"
$FacadeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\tracked_target_card_view.gd"
$CardViewScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\card_view.gd"
$PresenterScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\passthrough_overlay_presenter.gd"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\tracked_target_card_view_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "tracked_target_card_view_probe_status.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_tracked_target_card_view_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_tracked_target_card_view_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $FacadeScript, $CardViewScript, $PresenterScript)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -Path $StatusFile -ErrorAction SilentlyContinue

$OldFacadeScript = $env:SMARTXR_CARD_VIEW_FACADE_SCRIPT
$OldCardViewScript = $env:SMARTXR_CARD_VIEW_SCRIPT
$OldPresenterScript = $env:SMARTXR_PASSTHROUGH_PRESENTER_SCRIPT
$OldStatusPath = $env:SMARTXR_CARD_VIEW_FACADE_PROBE_STATUS_PATH
$env:SMARTXR_CARD_VIEW_FACADE_SCRIPT = ([System.IO.Path]::GetFullPath($FacadeScript)).Replace("\", "/")
$env:SMARTXR_CARD_VIEW_SCRIPT = ([System.IO.Path]::GetFullPath($CardViewScript)).Replace("\", "/")
$env:SMARTXR_PASSTHROUGH_PRESENTER_SCRIPT = ([System.IO.Path]::GetFullPath($PresenterScript)).Replace("\", "/")
$env:SMARTXR_CARD_VIEW_FACADE_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
try {
    $Process = Start-Process -FilePath $GodotExe -ArgumentList @(
        "--headless",
        "--script", $ProbeScript
    ) -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $GodotLog -RedirectStandardError $GodotErrLog
    $null = $Process.Handle

    if (-not $Process.WaitForExit([int]($ProcessTimeoutSeconds * 1000))) {
        $Process.Kill()
        Write-Error "Godot probe timed out after $ProcessTimeoutSeconds seconds"
    }
    $ExitCode = $Process.ExitCode
} finally {
    if ($null -eq $OldFacadeScript) { Remove-Item Env:\SMARTXR_CARD_VIEW_FACADE_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_CARD_VIEW_FACADE_SCRIPT = $OldFacadeScript }
    if ($null -eq $OldCardViewScript) { Remove-Item Env:\SMARTXR_CARD_VIEW_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_CARD_VIEW_SCRIPT = $OldCardViewScript }
    if ($null -eq $OldPresenterScript) { Remove-Item Env:\SMARTXR_PASSTHROUGH_PRESENTER_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_PASSTHROUGH_PRESENTER_SCRIPT = $OldPresenterScript }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_CARD_VIEW_FACADE_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_CARD_VIEW_FACADE_PROBE_STATUS_PATH = $OldStatusPath }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "tracked-target card view probe FAILED (exit $ExitCode)"
}
Write-Host "tracked-target card view probe PASSED"
