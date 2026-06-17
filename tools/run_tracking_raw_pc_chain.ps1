param(
    [Parameter(Mandatory = $true)][string]$CaptureRoot,
    [string]$Session = "capture_20260415T065340Z",
    [int]$Start = 350,
    [int]$Count = 200,
    [double]$Conf = 0.25,
    [string]$DetectPython = "",
    [string]$MonitorPython = "python",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8770,
    [double]$Hz = 20.0,
    [int]$MinPackets = 60,
    [double]$TimeoutSeconds = 40.0
)

# Full PC chain, no device: NV12 session -> PC-offload ncnn yolov8n -> C1
# producer -> live WebSocket, asserted by the consumer harness. The publisher
# needs the optional detection deps (numpy/opencv/ncnn); point -DetectPython at
# the .venv-detect interpreter. The monitor is dependency-free.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
if ($DetectPython -eq "") {
    $DetectPython = Join-Path -Path $RepoRoot -ChildPath ".venv-detect\Scripts\python.exe"
}
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\run_tracking_raw_live_publisher.py"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\tracking_raw_pc_chain"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "tracking_raw_pc_chain_status.json"
$PublisherLog = Join-Path -Path $WorkDir -ChildPath "publisher.log"

if (-not (Test-Path -LiteralPath $DetectPython)) {
    throw "Detection interpreter not found: $DetectPython (create .venv-detect: uv venv --python 3.12 .venv-detect; uv pip install --python .venv-detect ncnn numpy opencv-python-headless)"
}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $StatusFile -Force -ErrorAction SilentlyContinue

$Url = "ws://${HostName}:${Port}/tracking_raw"
Write-Host "SmartXR tracking_raw (C1) full PC chain"
Write-Host "Capture:   $CaptureRoot ($Session [$Start..$($Start + $Count)])"
Write-Host "WebSocket: $Url"
Write-Host ""

function Stop-ChildProcess {
    param($Process)
    if ($null -ne $Process -and -not $Process.HasExited) {
        try { $Process.Kill(); $Process.WaitForExit(3000) | Out-Null }
        catch { Write-Warning "Failed to stop publisher $($Process.Id): $_" }
    }
}

$Proc = $null
try {
    $publisherArgs = @(
        $Publisher,
        "--capture-root", $CaptureRoot, "--session", $Session,
        "--start", "$Start", "--count", "$Count", "--conf", "$Conf",
        "--host", $HostName, "--port", "$Port", "--hz", "$Hz", "--log-every", "20"
    )
    $Proc = Start-Process -FilePath $DetectPython -ArgumentList $publisherArgs `
        -WorkingDirectory $RepoRoot -PassThru -NoNewWindow `
        -RedirectStandardOutput $PublisherLog -RedirectStandardError "$PublisherLog.err"
    Start-Sleep -Seconds 2

    & $MonitorPython -m smartxr.cli.tracking_raw_monitor `
        --url $Url --min-packets "$MinPackets" --timeout-seconds "$TimeoutSeconds" --output $StatusFile
    $ExitCode = $LASTEXITCODE
} finally {
    Stop-ChildProcess -Process $Proc
}

Write-Host ""
Write-Host "PC chain exit code: $ExitCode"
Write-Host "Status JSON: $StatusFile"
Write-Host "Publisher log: $PublisherLog"
exit $ExitCode
