param(
    [string]$AntmanRoot = "E:\xia\Antman_smart",
    [string]$OutDir = ".tmp\antman_vst_capture_session",
    [double]$DurationSeconds = 30.0,
    [int]$MaxFrames = 0,
    [string]$ShmName = "Antman.VST.AI.v1",
    [string]$ShmEye = "Right",
    [string]$ShmNamespace = "",
    [int]$WaitTimeoutMs = 1000,
    [double]$WaitForProducerSeconds = 10.0,
    [string]$SourceVersion = "Antman.VST.AI.v1",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$WorkDir = [System.IO.Path]::GetFullPath((Join-Path -Path $RepoRoot -ChildPath $OutDir))
$Recorder = Join-Path -Path $RepoRoot -ChildPath "tools\record_antman_vst_capture.py"

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

Write-Host "SmartXR Antman VST NV12 capture recorder"
Write-Host "Antman root: $AntmanRoot"
Write-Host "Output dir:  $WorkDir"
Write-Host "Duration:    $DurationSeconds seconds"
Write-Host "Python:      $PythonExe"
Write-Host "VST eye:     $ShmEye"
Write-Host "Need headset: connect/start the headset VST producer before expecting frames."

$recorderArgs = @(
    $Recorder,
    "--antman-root", $AntmanRoot,
    "--out-dir", $WorkDir,
    "--duration-seconds", "$DurationSeconds",
    "--shm-name", $ShmName,
    "--shm-eye", $ShmEye,
    "--wait-timeout-ms", "$WaitTimeoutMs",
    "--wait-for-producer-seconds", "$WaitForProducerSeconds",
    "--source-version", $SourceVersion
)

if ($MaxFrames -gt 0) {
    $recorderArgs += @("--max-frames", "$MaxFrames")
}
if ($ShmNamespace -ne "") {
    $recorderArgs += @("--shm-namespace", $ShmNamespace)
}

& $PythonExe @recorderArgs
$ExitCode = $LASTEXITCODE
if ($ExitCode -eq 1) {
    Write-Host "Need headset: no VST SHM frames were observed. Connect/start the headset VST producer and rerun."
}
if ($ExitCode -eq 3) {
    Write-Host "Dependency unavailable: recorder could not import a required Antman Python module."
    Write-Host "Use -PythonExe to point at the Antman_smart venv, or install the missing dependency in the selected Python."
}
if ($ExitCode -eq 4) {
    Write-Host "Unsupported frame contract: SHM frames were not exposed as native NV12 bytes with width/height/stride."
    Write-Host "Do not use this output as replay input until the live producer contract is confirmed."
}

Write-Host ""
Write-Host "Outputs:"
Write-Host "  Session:  $WorkDir"
Write-Host "  Metadata: $(Join-Path -Path $WorkDir -ChildPath 'metadata.json')"
Write-Host "  Timeline: $(Join-Path -Path $WorkDir -ChildPath 'timeline.json')"

exit $ExitCode
