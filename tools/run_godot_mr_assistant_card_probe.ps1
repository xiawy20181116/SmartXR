param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for the Godot MR assistant-card state/view loop.
# Runs in no-project mode so it does not require the full headset project.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "apps\godot_mr\tests\script_only_assistant_card_probe.gd"
$StateScript = Join-Path -Path $RepoRoot -ChildPath "apps\godot_mr\scripts\assistant_card_state.gd"
$ViewScript = Join-Path -Path $RepoRoot -ChildPath "apps\godot_mr\scripts\assistant_card_view.gd"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\assistant_card_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "assistant_card_probe_status.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_assistant_card_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_assistant_card_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $StateScript, $ViewScript)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -Path $StatusFile -ErrorAction SilentlyContinue

$OldStateScript = $env:SMARTXR_ASSISTANT_CARD_STATE_SCRIPT
$OldViewScript = $env:SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT
$OldStatusPath = $env:SMARTXR_ASSISTANT_CARD_PROBE_STATUS_PATH
$env:SMARTXR_ASSISTANT_CARD_STATE_SCRIPT = ([System.IO.Path]::GetFullPath($StateScript)).Replace("\", "/")
$env:SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT = ([System.IO.Path]::GetFullPath($ViewScript)).Replace("\", "/")
$env:SMARTXR_ASSISTANT_CARD_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
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
    if ($null -eq $OldStateScript) { Remove-Item Env:\SMARTXR_ASSISTANT_CARD_STATE_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_ASSISTANT_CARD_STATE_SCRIPT = $OldStateScript }
    if ($null -eq $OldViewScript) { Remove-Item Env:\SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT = $OldViewScript }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_ASSISTANT_CARD_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_ASSISTANT_CARD_PROBE_STATUS_PATH = $OldStatusPath }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "assistant card probe FAILED (exit $ExitCode)"
}
Write-Host "assistant card probe PASSED"
