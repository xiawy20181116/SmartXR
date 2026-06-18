param(
    [string]$AntmanRoot = "E:\xia\Antman_smart",
    [string]$OutDir = ".tmp\antman_vst_stereo_package",
    [string]$ShmName = "Antman.VST.AI.v1",
    [string]$ShmNamespace = "",
    [int]$WaitTimeoutMs = 1000,
    [double]$WaitForProducerSeconds = 10.0,
    [int]$RecordedWidth = 880,
    [int]$RecordedHeight = 660,
    [int]$MaxReadAttempts = 240,
    [int]$MaxSkewFrames = 1,
    [double]$SleepSeconds = 0.005,
    [switch]$RequirePair,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$Recorder = Join-Path -Path $RepoRoot -ChildPath "tools\record_antman_vst_stereo_package.py"

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

Write-Host "SmartXR Antman VST stereo package recorder"
Write-Host "Antman root: $AntmanRoot"
Write-Host "Output:      $OutDir"
Write-Host "Python:      $PythonExe"
Write-Host "Source:      Antman.VST.AI.v1 Left/Right SHM"
Write-Host "Need headset: connect/start the headset VST producer before expecting frames."

$recorderArgs = @(
    $Recorder,
    "--antman-root", $AntmanRoot,
    "--out-dir", $OutDir,
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

& $PythonExe @recorderArgs
$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) {
    Write-Host ""
    Write-Host "Stereo package capture failed."
    Write-Host "VST SHM source is unavailable, no L/R frames were captured, no pair was produced, or package validation failed."
    Write-Host "Expected output layout after success:"
    Write-Host "  stereo.json"
    Write-Host "  left\metadata.json + left\nv12_packets\packet_*.bin"
    Write-Host "  right\metadata.json + right\nv12_packets\packet_*.bin"
}
exit $ExitCode
