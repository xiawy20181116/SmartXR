param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for the XR bootstrap subsystem (M3 step 5, YAN-79).
# Runs the script-only probe headless in NO-PROJECT mode, like the other
# script-only probes: loading the project (--path) would boot the full main
# scene, which reconnects WebSockets forever and never exits headless.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_xr_bootstrap_probe.gd"
$BootstrapScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\xr_bootstrap.gd"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\xr_bootstrap_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "xr_bootstrap_probe_status.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_xr_bootstrap_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_xr_bootstrap_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $BootstrapScript)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -Path $StatusFile -ErrorAction SilentlyContinue

$OldBootstrapScript = $env:SMARTXR_XR_BOOTSTRAP_SCRIPT
$OldStatusPath = $env:SMARTXR_XR_BOOTSTRAP_PROBE_STATUS_PATH
$env:SMARTXR_XR_BOOTSTRAP_SCRIPT = ([System.IO.Path]::GetFullPath($BootstrapScript)).Replace("\", "/")
$env:SMARTXR_XR_BOOTSTRAP_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
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
    if ($null -eq $OldBootstrapScript) { Remove-Item Env:\SMARTXR_XR_BOOTSTRAP_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_XR_BOOTSTRAP_SCRIPT = $OldBootstrapScript }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_XR_BOOTSTRAP_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_XR_BOOTSTRAP_PROBE_STATUS_PATH = $OldStatusPath }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "xr bootstrap probe FAILED (exit $ExitCode)"
}
Write-Host "xr bootstrap probe PASSED"
