param(
    [string]$AntmanRoot = "E:\xia\Antman_smart",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8766,
    [double]$Hz = 20.0,
    [double]$MinConfidence = 0.5,
    [string]$CardId = "CardAnchor",
    [int]$LogEvery = 20,
    [int]$MaxEmptyReads = 120,
    [string]$ShmName = "Antman.VST.AI.v1",
    [string]$ShmEye = "Right",
    [string]$ShmNamespace = "",
    [int]$WaitTimeoutMs = 1000,
    [double]$WaitForProducerSeconds = 10.0,
    [string]$Model = "yolov8n.pt",
    [string]$Backend = "ultralytics",
    [int]$Imgsz = 320,
    [double]$HorizontalFovDeg = 0.0,
    [double]$VerticalFovDeg = 0.0,
    [double]$PrincipalPointX = -1.0,
    [double]$PrincipalPointY = -1.0,
    [double]$FocalLengthX = 0.0,
    [double]$FocalLengthY = 0.0,
    [string]$Device = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\antman_vst_proxy_targets_live_publisher.py"

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

Write-Host "SmartXR Antman VST proxy_targets live publisher"
Write-Host "Antman root: $AntmanRoot"
Write-Host "WebSocket:   ws://${HostName}:${Port}/proxy_targets"
Write-Host "Python:      $PythonExe"
Write-Host "Source:      VST SHM + HumanTrackor"
Write-Host "VST eye:     $ShmEye"
if ($HorizontalFovDeg -gt 0.0 -or $VerticalFovDeg -gt 0.0 -or $PrincipalPointX -ge 0.0 -or $PrincipalPointY -ge 0.0 -or $FocalLengthX -gt 0.0 -or $FocalLengthY -gt 0.0) {
    Write-Host "Calibration: hfov=$HorizontalFovDeg vfov=$VerticalFovDeg pp=($PrincipalPointX,$PrincipalPointY) focal=($FocalLengthX,$FocalLengthY)"
}
Write-Host "Need headset: connect/start the headset VST producer before expecting frames."
Write-Host "Seq appears after a WebSocket client connects and a target frame passes confidence gate."

$publisherArgs = @(
    $Publisher,
    "--antman-root", $AntmanRoot,
    "--host", $HostName,
    "--port", "$Port",
    "--hz", "$Hz",
    "--min-confidence", "$MinConfidence",
    "--card-id", $CardId,
    "--log-every", "$LogEvery",
    "--max-empty-reads", "$MaxEmptyReads",
    "--shm-name", $ShmName,
    "--shm-eye", $ShmEye,
    "--wait-timeout-ms", "$WaitTimeoutMs",
    "--wait-for-producer-seconds", "$WaitForProducerSeconds",
    "--model", $Model,
    "--backend", $Backend,
    "--imgsz", "$Imgsz"
)

if ($ShmNamespace -ne "") {
    $publisherArgs += @("--shm-namespace", $ShmNamespace)
}
if ($Device -ne "") {
    $publisherArgs += @("--device", $Device)
}
if ($HorizontalFovDeg -gt 0.0) {
    $publisherArgs += @("--horizontal-fov-deg", "$HorizontalFovDeg")
}
if ($VerticalFovDeg -gt 0.0) {
    $publisherArgs += @("--vertical-fov-deg", "$VerticalFovDeg")
}
if ($PrincipalPointX -ge 0.0) {
    $publisherArgs += @("--principal-point-x", "$PrincipalPointX")
}
if ($PrincipalPointY -ge 0.0) {
    $publisherArgs += @("--principal-point-y", "$PrincipalPointY")
}
if ($FocalLengthX -gt 0.0) {
    $publisherArgs += @("--focal-length-x", "$FocalLengthX")
}
if ($FocalLengthY -gt 0.0) {
    $publisherArgs += @("--focal-length-y", "$FocalLengthY")
}

& $PythonExe @publisherArgs
$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) {
    Write-Host ""
    Write-Host "WebSocket listener was not started."
    Write-Host "VST SHM source is unavailable or failed during startup; start/connect the headset VST producer and rerun."
    Write-Host "Expected ready line only appears after source startup succeeds:"
    Write-Host "  proxy_targets live publisher listening on ws://${HostName}:${Port}/proxy_targets"
}
exit $ExitCode
