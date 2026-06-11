param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for SmartXROptions (M1, YAN-73).
# Runs the script-only probe headless in NO-PROJECT mode, like the other
# script-only probes: loading the project (--path) would boot the full main
# scene, which reconnects WebSockets forever and never exits headless.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_smartxr_options_probe.gd"
$OptionsScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\smartxr_options.gd"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\smartxr_options_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "smartxr_options_probe_status.json"
$ConfigFile = Join-Path -Path $WorkDir -ChildPath "smartxr_options_probe_config.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_smartxr_options_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_smartxr_options_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $OptionsScript)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -Path $StatusFile, $ConfigFile -ErrorAction SilentlyContinue

$OldOptionsScript = $env:SMARTXR_OPTIONS_SCRIPT
$OldStatusPath = $env:SMARTXR_OPTIONS_PROBE_STATUS_PATH
$OldConfigPath = $env:SMARTXR_OPTIONS_PROBE_CONFIG_PATH
$env:SMARTXR_OPTIONS_SCRIPT = ([System.IO.Path]::GetFullPath($OptionsScript)).Replace("\", "/")
$env:SMARTXR_OPTIONS_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
$env:SMARTXR_OPTIONS_PROBE_CONFIG_PATH = ([System.IO.Path]::GetFullPath($ConfigFile)).Replace("\", "/")
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
    if ($null -eq $OldOptionsScript) { Remove-Item Env:\SMARTXR_OPTIONS_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_OPTIONS_SCRIPT = $OldOptionsScript }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_OPTIONS_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_OPTIONS_PROBE_STATUS_PATH = $OldStatusPath }
    if ($null -eq $OldConfigPath) { Remove-Item Env:\SMARTXR_OPTIONS_PROBE_CONFIG_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_OPTIONS_PROBE_CONFIG_PATH = $OldConfigPath }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "smartxr options probe FAILED (exit $ExitCode)"
}
Write-Host "smartxr options probe PASSED"
