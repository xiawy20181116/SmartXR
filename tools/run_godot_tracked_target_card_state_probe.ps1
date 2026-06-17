param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for the tracked-target card State seam
# (tracked_target_card_state.gd). Runs in no-project mode so it does not require
# the full headset project.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_tracked_target_card_state_probe.gd"
$StateScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\tracked_target_card_state.gd"
$FragmentScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\proxy_targets_status_fragment.gd"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\tracked_target_card_state_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "tracked_target_card_state_probe_status.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_tracked_target_card_state_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_tracked_target_card_state_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $StateScript, $FragmentScript)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -Path $StatusFile -ErrorAction SilentlyContinue

$OldStateScript = $env:SMARTXR_CARD_STATE_SCRIPT
$OldFragmentScript = $env:SMARTXR_STATUS_FRAGMENT_SCRIPT
$OldStatusPath = $env:SMARTXR_CARD_STATE_PROBE_STATUS_PATH
$env:SMARTXR_CARD_STATE_SCRIPT = ([System.IO.Path]::GetFullPath($StateScript)).Replace("\", "/")
$env:SMARTXR_STATUS_FRAGMENT_SCRIPT = ([System.IO.Path]::GetFullPath($FragmentScript)).Replace("\", "/")
$env:SMARTXR_CARD_STATE_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
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
    if ($null -eq $OldStateScript) { Remove-Item Env:\SMARTXR_CARD_STATE_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_CARD_STATE_SCRIPT = $OldStateScript }
    if ($null -eq $OldFragmentScript) { Remove-Item Env:\SMARTXR_STATUS_FRAGMENT_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_STATUS_FRAGMENT_SCRIPT = $OldFragmentScript }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_CARD_STATE_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_CARD_STATE_PROBE_STATUS_PATH = $OldStatusPath }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "tracked-target card state probe FAILED (exit $ExitCode)"
}
Write-Host "tracked-target card state probe PASSED"
