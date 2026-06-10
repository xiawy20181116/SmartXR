param(
    [string]$AntmanRoot = "E:\xia\Antman_smart",
    [string]$OutDir = ".tmp\antman_vst_target_sample_capture",
    [double]$DurationSeconds = 30.0,
    [double]$MinConfidence = 0.5,
    [switch]$RequireTarget,
    [string]$ShmName = "Antman.VST.AI.v1",
    [string]$ShmNamespace = "",
    [int]$WaitTimeoutMs = 1000,
    [double]$WaitForProducerSeconds = 10.0,
    [string]$Model = "yolov8n.pt",
    [string]$Backend = "ultralytics",
    [int]$Imgsz = 320,
    [string]$Device = "",
    [int]$StopAfterFirstTargetFrames = 10,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$WorkDir = [System.IO.Path]::GetFullPath((Join-Path -Path $RepoRoot -ChildPath $OutDir))
$JsonlPath = Join-Path -Path $WorkDir -ChildPath "vst_target_frames.jsonl"
$Dumper = Join-Path -Path $RepoRoot -ChildPath "tools\dump_antman_vst_humantrackor_jsonl.py"
$Capture = Join-Path -Path $RepoRoot -ChildPath "tools\capture_vst_target_sample_session.py"

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

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

Write-Host "SmartXR Antman VST target sample capture"
Write-Host "Antman root: $AntmanRoot"
Write-Host "Work dir:    $WorkDir"
Write-Host "JSONL:       $JsonlPath"
Write-Host "Duration:    $DurationSeconds seconds"
Write-Host "Python:      $PythonExe"
Write-Host "Need headset: only if VST SHM has no frames or target sample is required from live VST."

$dumperArgs = @(
    $Dumper,
    "--antman-root", $AntmanRoot,
    "--duration-seconds", "$DurationSeconds",
    "--out", $JsonlPath,
    "--min-confidence", "$MinConfidence",
    "--stop-after-first-target-frames", "$StopAfterFirstTargetFrames",
    "--shm-name", $ShmName,
    "--wait-timeout-ms", "$WaitTimeoutMs",
    "--wait-for-producer-seconds", "$WaitForProducerSeconds",
    "--model", $Model,
    "--backend", $Backend,
    "--imgsz", "$Imgsz"
)

if ($ShmNamespace -ne "") {
    $dumperArgs += @("--shm-namespace", $ShmNamespace)
}
if ($Device -ne "") {
    $dumperArgs += @("--device", $Device)
}
if ($RequireTarget) {
    $dumperArgs += "--require-target"
}

Write-Host ""
Write-Host "Running Antman VST dumper..."
& $PythonExe @dumperArgs
$dumperExit = $LASTEXITCODE
Write-Host "Dumper exit code: $dumperExit"

if ($dumperExit -eq 1) {
    Write-Host "Need headset: no VST SHM frames were observed. Connect/start the headset VST producer and rerun."
    exit 1
}
if ($dumperExit -eq 2) {
    Write-Host "Need visible target: VST frames were observed, but no target passed confidence threshold."
    exit 2
}
if ($dumperExit -eq 3) {
    Write-Host "Dependency unavailable: Antman VST dumper could not import a required Python module."
    Write-Host "Use -PythonExe to point at the Antman_smart venv, or install the missing dependency in the selected Python."
    exit 3
}
if ($dumperExit -ne 0) {
    exit $dumperExit
}

Write-Host ""
Write-Host "Building target_sample_session..."
$captureArgs = @(
    $Capture,
    "--input-jsonl", $JsonlPath,
    "--out-dir", $WorkDir,
    "--min-confidence", "$MinConfidence"
)
if ($RequireTarget) {
    $captureArgs += "--require-target"
}

& $PythonExe @captureArgs
$captureExit = $LASTEXITCODE
Write-Host "Capture session exit code: $captureExit"

Write-Host ""
Write-Host "Outputs:"
Write-Host "  JSONL:        $JsonlPath"
Write-Host "  Status JSON:  $(Join-Path -Path $WorkDir -ChildPath 'vst_capture_status.json')"
Write-Host "  First target: $(Join-Path -Path $WorkDir -ChildPath 'vst_first_target_sample.json')"

exit $captureExit
