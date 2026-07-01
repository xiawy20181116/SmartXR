param(
    [string]$AntmanRoot = "E:\xia\Antman_smart",
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8766,
    [double]$Hz = 20.0,
    [double]$MinConfidence = 0.5,
    [int]$RecordedWidth = 880,
    [int]$RecordedHeight = 660,
    [int]$LogEvery = 20,
    [int]$MaxEmptyReads = 120,
    [double]$ProbeTimeoutSeconds = 60.0,
    [double]$ProbeProcessTimeoutSeconds = 90.0,
    [int]$MonitorMinPackets = 0,
    [double]$MonitorTimeoutSeconds = 20.0,
    [switch]$EnableKeypointAnchor,
    [string]$PoseModel = "yolov8n-pose.pt",
    [int]$PoseImgsz = 640,
    [double]$PoseConf = 0.25,
    [double]$MinKeypointScore = 0.5,
    [double]$KeypointMaxHz = 12.0,
    [double]$KeypointReuseMaxAgeMs = 150.0,
    [string]$PoseDevice = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\antman_vst_stereo_proxy_targets_live_publisher.py"
$ProbeRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_godot_script_only_staged_probe.ps1"
$MonitorRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_proxy_targets_live_monitor.ps1"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\antman_vst_stereo_proxy_targets_live"
$PublisherLog = Join-Path -Path $WorkDir -ChildPath "stereo_proxy_targets_publisher.log"
$PublisherErr = Join-Path -Path $WorkDir -ChildPath "stereo_proxy_targets_publisher.err.log"
$DepthTraceFile = Join-Path -Path $WorkDir -ChildPath "depth_estimation_trace.jsonl"
$WsUrl = "ws://${HostName}:${Port}/proxy_targets"

function Stop-ChildProcess {
    param($Process)

    if ($null -ne $Process -and -not $Process.HasExited) {
        try {
            $Process.Kill()
            $Process.WaitForExit(3000) | Out-Null
        } catch {
            Write-Warning "Failed to stop process $($Process.Id): $_"
        }
    }
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

foreach ($RequiredPath in @($Publisher, $ProbeRunner, $MonitorRunner)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required file not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $PublisherLog, $PublisherErr, $DepthTraceFile -Force -ErrorAction SilentlyContinue

$PublisherProcess = $null
$ExitCode = 1

Write-Host "SmartXR Antman VST stereo proxy_targets live validation"
Write-Host "Source:      Left/Right VST SHM + HumanTrackor bbox stereo"
Write-Host "WebSocket:   $WsUrl"
Write-Host "Python:      $PythonExe"
Write-Host "Work dir:    $WorkDir"
Write-Host "Depth trace: $DepthTraceFile"
Write-Host "Keypoints:   $EnableKeypointAnchor"
Write-Host "Keypoint runtime: keypoint_max_hz=$KeypointMaxHz reuse_max_age_ms=$KeypointReuseMaxAgeMs"

try {
    $PublisherArgs = @(
        $Publisher,
        "--antman-root", $AntmanRoot,
        "--host", $HostName,
        "--port", [string]$Port,
        "--hz", [string]$Hz,
        "--min-confidence", [string]$MinConfidence,
        "--recorded-width", [string]$RecordedWidth,
        "--recorded-height", [string]$RecordedHeight,
        "--log-every", [string]$LogEvery,
        "--max-empty-reads", [string]$MaxEmptyReads,
        "--depth-trace", [string]$DepthTraceFile
    )
    if ($EnableKeypointAnchor) {
        $PublisherArgs += @(
            "--enable-keypoint-anchor",
            "--pose-model", $PoseModel,
            "--pose-imgsz", [string]$PoseImgsz,
            "--pose-conf", [string]$PoseConf,
            "--min-keypoint-score", [string]$MinKeypointScore,
            "--keypoint-max-hz", [string]$KeypointMaxHz,
            "--keypoint-reuse-max-age-ms", [string]$KeypointReuseMaxAgeMs
        )
        if ($PoseDevice -ne "") {
            $PublisherArgs += @("--pose-device", $PoseDevice)
        }
    }

    $PublisherProcess = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList $PublisherArgs `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $PublisherLog `
        -RedirectStandardError $PublisherErr `
        -PassThru

    Start-Sleep -Milliseconds 1000
    if ($PublisherProcess.HasExited) {
        throw "stereo proxy_targets publisher exited early with code $($PublisherProcess.ExitCode)"
    }

    & $ProbeRunner `
        -GodotExe $GodotExe `
        -PythonExe $PythonExe `
        -HostName $HostName `
        -StartPort $Port `
        -ExternalPublisher `
        -Stage apply `
        -TimeoutSeconds $ProbeTimeoutSeconds `
        -ProcessTimeoutSeconds $ProbeProcessTimeoutSeconds
    $ExitCode = $LASTEXITCODE

    if ($MonitorMinPackets -gt 0) {
        & $MonitorRunner `
            -Url $WsUrl `
            -MinPackets $MonitorMinPackets `
            -TimeoutSeconds $MonitorTimeoutSeconds `
            -PythonExe $PythonExe
        if ($LASTEXITCODE -ne 0 -and $ExitCode -eq 0) {
            $ExitCode = $LASTEXITCODE
        }
    }
} finally {
    Stop-ChildProcess -Process $PublisherProcess

    Write-Host ""
    Write-Host "Logs:"
    Write-Host "  Publisher stdout: $PublisherLog"
    Write-Host "  Publisher stderr: $PublisherErr"
    Write-Host "  Depth trace:      $DepthTraceFile"
    Write-Host "  Staged status:    .tmp\script_only_staged_probe\apply\script_only_websocket_staged_probe_status.json"
}

exit $ExitCode
