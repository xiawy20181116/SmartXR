param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for the VST target source subsystem (M4 step 2,
# YAN-84). Runs the script-only probe headless in NO-PROJECT mode.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_target_source_probe.gd"
$TargetSourceScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\target_source.gd"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\target_source_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "target_source_probe_status.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_target_source_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_target_source_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $TargetSourceScript)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -Path $StatusFile -ErrorAction SilentlyContinue

$OldTargetSourceScript = $env:SMARTXR_TARGET_SOURCE_SCRIPT
$OldStatusPath = $env:SMARTXR_TARGET_SOURCE_PROBE_STATUS_PATH
$env:SMARTXR_TARGET_SOURCE_SCRIPT = ([System.IO.Path]::GetFullPath($TargetSourceScript)).Replace("\", "/")
$env:SMARTXR_TARGET_SOURCE_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
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
    if ($null -eq $OldTargetSourceScript) { Remove-Item Env:\SMARTXR_TARGET_SOURCE_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_TARGET_SOURCE_SCRIPT = $OldTargetSourceScript }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_TARGET_SOURCE_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_TARGET_SOURCE_PROBE_STATUS_PATH = $OldStatusPath }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "target source probe FAILED (exit $ExitCode)"
}
Write-Host "target source probe PASSED"
