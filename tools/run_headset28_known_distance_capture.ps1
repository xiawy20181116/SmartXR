param(
    [Parameter(Mandatory=$true)]
    [ValidateScript({ $_ -gt 0.0 })]
    [double]$KnownDistanceM,
    [string]$AntmanRoot = "E:\xia\Antman_smart",
    [string]$OutRoot = ".tmp\headset28_known_distance_captures",
    [string]$RunId = "",
    [string]$TargetId = "known-target-1",
    [string]$Operator = "",
    [string]$Notes = "",
    [string]$ShmName = "Antman.VST.AI.v1",
    [string]$ShmNamespace = "",
    [int]$WaitTimeoutMs = 1000,
    [double]$WaitForProducerSeconds = 10.0,
    [int]$RecordedWidth = 880,
    [int]$RecordedHeight = 660,
    [double]$DurationSeconds = 10.0,
    [int]$MaxReadAttempts = 0,
    [int]$MaxSkewFrames = 1,
    [double]$SleepSeconds = 0.005,
    [switch]$RequirePair,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$Recorder = Join-Path -Path $RepoRoot -ChildPath "tools\record_antman_vst_stereo_package.py"
$SessionHelper = Join-Path -Path $RepoRoot -ChildPath "tools\prepare_headset28_known_distance_capture.py"

function Resolve-OutputRoot {
    param([string]$PathValue)
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path -Path $RepoRoot -ChildPath $PathValue))
}

if ($RunId -eq "") {
    $RunId = "headset28_known_distance_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
}

if ($MaxReadAttempts -le 0) {
    $SleepForCalc = [Math]::Max($SleepSeconds, 0.001)
    $MaxReadAttempts = [int][Math]::Ceiling($DurationSeconds / $SleepForCalc)
}

if ($PythonExe -eq "") {
    $PythonCandidates = @(
        (Join-Path -Path $AntmanRoot -ChildPath "human_detect\.venv\Scripts\python.exe"),
        (Join-Path -Path $AntmanRoot -ChildPath "demo\.uv-venv\Scripts\python.exe"),
        (Join-Path -Path $AntmanRoot -ChildPath ".venv\Scripts\python.exe")
    )
    foreach ($Candidate in $PythonCandidates) {
        if (Test-Path -LiteralPath $Candidate) {
            $PythonExe = $Candidate
            break
        }
    }
    if ($PythonExe -eq "") {
        $PythonExe = "python"
    }
}

$OutRootPath = Resolve-OutputRoot $OutRoot
$RunDir = Join-Path -Path $OutRootPath -ChildPath $RunId
$StereoPackageDir = Join-Path -Path $RunDir -ChildPath "stereo_package"
$RecorderStdoutPath = Join-Path -Path $RunDir -ChildPath "recorder_stdout.txt"
$RecorderStatusJsonPath = Join-Path -Path $RunDir -ChildPath "recorder_status.json"

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

Write-Host "SmartXR headset #28 known-distance capture"
Write-Host "Antman root:      $AntmanRoot"
Write-Host "Run dir:          $RunDir"
Write-Host "Stereo package:   $StereoPackageDir"
Write-Host "Known distance m: $KnownDistanceM"
Write-Host "Target id:        $TargetId"
Write-Host "Python:           $PythonExe"
Write-Host "Source:           Antman.VST.AI.v1 Left/Right SHM"
Write-Host "Need headset: connect/start #28 VST producer before expecting frames."

$recorderArgs = @(
    $Recorder,
    "--antman-root", $AntmanRoot,
    "--out-dir", $StereoPackageDir,
    "--shm-name", $ShmName,
    "--wait-timeout-ms", "$WaitTimeoutMs",
    "--wait-for-producer-seconds", "$WaitForProducerSeconds",
    "--recorded-width", "$RecordedWidth",
    "--recorded-height", "$RecordedHeight",
    "--max-read-attempts", "$MaxReadAttempts",
    "--max-skew-frames", "$MaxSkewFrames",
    "--sleep-seconds", "$SleepSeconds"
)

if ($ShmNamespace -ne "") {
    $recorderArgs += @("--shm-namespace", $ShmNamespace)
}
if ($RequirePair) {
    $recorderArgs += @("--require-pair")
}

Write-Host ""
Write-Host "Running stereo package recorder..."
$RecorderOutput = & $PythonExe @recorderArgs 2>&1
$RecorderExitCode = $LASTEXITCODE
$RecorderOutput | ForEach-Object { Write-Host $_ }
$RecorderOutput | Set-Content -LiteralPath $RecorderStdoutPath -Encoding UTF8

$RecorderJsonLine = $RecorderOutput | Where-Object { "$_" -match '^\s*\{' } | Select-Object -Last 1
if ($null -ne $RecorderJsonLine) {
    "$RecorderJsonLine" | Set-Content -LiteralPath $RecorderStatusJsonPath -Encoding UTF8
}

$commandJson = ConvertTo-Json @(
    $PSCommandPath,
    "-KnownDistanceM",
    "$KnownDistanceM",
    "-OutRoot",
    "$OutRoot",
    "-RunId",
    "$RunId"
) -Compress

$sessionArgs = @(
    $SessionHelper,
    "--run-dir", $RunDir,
    "--stereo-package-dir", $StereoPackageDir,
    "--known-distance-m", "$KnownDistanceM",
    "--target-id", $TargetId,
    "--recorded-width", "$RecordedWidth",
    "--recorded-height", "$RecordedHeight",
    "--recorder-exit-code", "$RecorderExitCode",
    "--run-id", $RunId,
    "--command-json", $commandJson
)

if (Test-Path -LiteralPath $RecorderStatusJsonPath) {
    $sessionArgs += @("--recorder-status-json", $RecorderStatusJsonPath)
}
if ($Operator -ne "") {
    $sessionArgs += @("--operator", $Operator)
}
if ($Notes -ne "") {
    $sessionArgs += @("--notes", $Notes)
}

Write-Host ""
Write-Host "Writing known-distance capture manifest..."
$SessionOutput = & $PythonExe @sessionArgs 2>&1
$SessionExitCode = $LASTEXITCODE
$SessionOutput | ForEach-Object { Write-Host $_ }

Write-Host ""
Write-Host "Outputs:"
Write-Host "  Run manifest:    $(Join-Path -Path $RunDir -ChildPath 'capture_run.json')"
Write-Host "  Status JSON:     $(Join-Path -Path $RunDir -ChildPath 'capture_status.json')"
Write-Host "  GT anchors:      $(Join-Path -Path $RunDir -ChildPath 'known_distance_gt.jsonl')"
Write-Host "  Recorder stdout: $RecorderStdoutPath"

exit $SessionExitCode
