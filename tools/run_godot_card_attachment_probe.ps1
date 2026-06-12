param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for the card attachment subsystem (M3 step 4, YAN-77).
# Runs the script-only probe headless in NO-PROJECT mode, like the other
# script-only probes: loading the project (--path) would boot the full main
# scene, which reconnects WebSockets forever and never exits headless.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_card_attachment_probe.gd"
$AttachmentScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\card_attachment.gd"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\card_attachment_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "card_attachment_probe_status.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_card_attachment_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_card_attachment_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $AttachmentScript)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -Path $StatusFile -ErrorAction SilentlyContinue

$OldAttachmentScript = $env:SMARTXR_CARD_ATTACHMENT_SCRIPT
$OldStatusPath = $env:SMARTXR_CARD_ATTACHMENT_PROBE_STATUS_PATH
$env:SMARTXR_CARD_ATTACHMENT_SCRIPT = ([System.IO.Path]::GetFullPath($AttachmentScript)).Replace("\", "/")
$env:SMARTXR_CARD_ATTACHMENT_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
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
    if ($null -eq $OldAttachmentScript) { Remove-Item Env:\SMARTXR_CARD_ATTACHMENT_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_CARD_ATTACHMENT_SCRIPT = $OldAttachmentScript }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_CARD_ATTACHMENT_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_CARD_ATTACHMENT_PROBE_STATUS_PATH = $OldStatusPath }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "card attachment probe FAILED (exit $ExitCode)"
}
Write-Host "card attachment probe PASSED"
