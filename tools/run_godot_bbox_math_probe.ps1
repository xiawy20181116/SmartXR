param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [double]$ProcessTimeoutSeconds = 60.0
)

# Runtime verification for the shared bbox->head math test vectors (M4-1,
# YAN-80): drives AndroidMovingCard.gd's bbox math against
# godot-android\fixtures\bbox_math_test_vectors.json, the same fixture
# tests\test_bbox_math_vectors.py runs through smartxr.geometry.
#
# Unlike the other script-only probes this one loads the CARD, which preloads
# nine sibling scripts via res://scripts/*.gd. So the runner stages scripts\
# into a temp working directory WITHOUT a Godot project file and launches
# Godot with that cwd, so res:// resolves there in true no-project mode (the
# compile-gate trick; cwd = godot-android\ would boot the real project and
# hang headless on the GXR/OpenXR boot).

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_bbox_math_probe.gd"
$ScriptsDir = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts"
$FixturePath = Join-Path -Path $RepoRoot -ChildPath "godot-android\fixtures\bbox_math_test_vectors.json"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\bbox_math_probe"
$StagedScriptsDir = Join-Path -Path $WorkDir -ChildPath "scripts"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "bbox_math_probe_status.json"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_bbox_math_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_bbox_math_probe.err.log"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $ScriptsDir, $FixturePath)) {
    if (-not (Test-Path $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

# Stage scripts\ fresh so res://scripts/*.gd resolves from the temp cwd.
if (Test-Path $StagedScriptsDir) {
    Remove-Item -Path $StagedScriptsDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $StagedScriptsDir | Out-Null
Copy-Item -Path (Join-Path $ScriptsDir "*.gd") -Destination $StagedScriptsDir
Remove-Item -Path $StatusFile -ErrorAction SilentlyContinue

$StagedCardScript = Join-Path -Path $StagedScriptsDir -ChildPath "AndroidMovingCard.gd"

$OldCardScript = $env:SMARTXR_BBOX_MATH_CARD_SCRIPT
$OldFixturePath = $env:SMARTXR_BBOX_MATH_FIXTURE_PATH
$OldStatusPath = $env:SMARTXR_BBOX_MATH_PROBE_STATUS_PATH
$env:SMARTXR_BBOX_MATH_CARD_SCRIPT = ([System.IO.Path]::GetFullPath($StagedCardScript)).Replace("\", "/")
$env:SMARTXR_BBOX_MATH_FIXTURE_PATH = ([System.IO.Path]::GetFullPath($FixturePath)).Replace("\", "/")
$env:SMARTXR_BBOX_MATH_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
try {
    $Process = Start-Process -FilePath $GodotExe -ArgumentList @(
        "--headless",
        "--script", $ProbeScript
    ) -WorkingDirectory $WorkDir -NoNewWindow -PassThru `
        -RedirectStandardOutput $GodotLog -RedirectStandardError $GodotErrLog
    $null = $Process.Handle  # cache handle so .ExitCode is readable after exit
    if (-not $Process.WaitForExit([int]($ProcessTimeoutSeconds * 1000))) {
        $Process.Kill()
        Write-Error "Godot probe timed out after $ProcessTimeoutSeconds seconds"
    }
    $ExitCode = $Process.ExitCode
} finally {
    if ($null -eq $OldCardScript) { Remove-Item Env:\SMARTXR_BBOX_MATH_CARD_SCRIPT -ErrorAction SilentlyContinue } else { $env:SMARTXR_BBOX_MATH_CARD_SCRIPT = $OldCardScript }
    if ($null -eq $OldFixturePath) { Remove-Item Env:\SMARTXR_BBOX_MATH_FIXTURE_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_BBOX_MATH_FIXTURE_PATH = $OldFixturePath }
    if ($null -eq $OldStatusPath) { Remove-Item Env:\SMARTXR_BBOX_MATH_PROBE_STATUS_PATH -ErrorAction SilentlyContinue } else { $env:SMARTXR_BBOX_MATH_PROBE_STATUS_PATH = $OldStatusPath }
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
}

if ($ExitCode -ne 0) {
    Write-Error "bbox math probe FAILED (exit $ExitCode)"
}
Write-Host "bbox math probe PASSED"
