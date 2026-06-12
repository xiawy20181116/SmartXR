param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$PythonExe = "python",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8773,
    [int]$OfflinePort = 8799,
    [double]$TimeoutSeconds = 8.0,
    [double]$ProcessTimeoutSeconds = 30.0
)

# Runtime verification for WSTransport (M3 step 3, YAN-76).
# Runs the script-only probe headless in NO-PROJECT mode like the other
# script-only probes (loading the project would boot the main scene, which
# reconnects WebSockets forever and never exits headless). A local fake
# publisher provides the live path. The "offline" port runs an accept-then-
# close TCP listener so the WebSocket handshake fails and the peer reaches
# STATE_CLOSED, exercising the retry-on-close loop: a genuinely closed port
# does NOT work here - on Windows loopback the peer sits in STATE_CONNECTING
# for seconds instead of closing.

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_ws_transport_probe.gd"
$TransportScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\ws_transport.gd"
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\fake_proxy_targets_publisher.py"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\ws_transport_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "ws_transport_probe_status.json"
$PublisherLog = Join-Path -Path $WorkDir -ChildPath "publisher.log"
$PublisherErr = Join-Path -Path $WorkDir -ChildPath "publisher.err.log"
$CloserScript = Join-Path -Path $WorkDir -ChildPath "tcp_closer.py"
$CloserLog = Join-Path -Path $WorkDir -ChildPath "tcp_closer.log"
$CloserErr = Join-Path -Path $WorkDir -ChildPath "tcp_closer.err.log"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_ws_transport_probe.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_ws_transport_probe.err.log"
$LiveWsUrl = "ws://${HostName}:${Port}/proxy_targets"
$OfflineWsUrl = "ws://${HostName}:${OfflinePort}/proxy_targets"

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

function Wait-ForLogText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Text,
        [double]$TimeoutSeconds = 5.0
    )

    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        if (Test-Path -LiteralPath $Path) {
            $Content = Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue
            if ($Content -like "*$Text*") {
                return $true
            }
        }
        Start-Sleep -Milliseconds 100
    }
    return $false
}

function Restore-EnvVar {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [AllowNull()]
        $Value
    )

    if ($null -eq $Value) {
        Remove-Item "Env:\$Name" -ErrorAction SilentlyContinue
    } else {
        Set-Item "Env:\$Name" $Value
    }
}

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $TransportScript, $Publisher)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $StatusFile, $PublisherLog, $PublisherErr, $CloserLog, $CloserErr, $GodotLog, $GodotErrLog -Force -ErrorAction SilentlyContinue

# Accept-then-close TCP listener for the offline/retry path (see header).
$CloserSource = @'
import socket
import sys

host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8799
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((host, port))
server.listen(5)
print(f"tcp closer listening on {host}:{port}", flush=True)
while True:
    conn, _ = server.accept()
    conn.close()
'@
[System.IO.File]::WriteAllText($CloserScript, $CloserSource, (New-Object System.Text.UTF8Encoding($false)))

$OldTransportScript = $env:SMARTXR_WS_TRANSPORT_SCRIPT
$OldStatusPath = $env:SMARTXR_WS_TRANSPORT_PROBE_STATUS_PATH
$OldLiveUrl = $env:SMARTXR_WS_TRANSPORT_LIVE_WS_URL
$OldOfflineUrl = $env:SMARTXR_WS_TRANSPORT_OFFLINE_WS_URL
$OldTimeout = $env:SMARTXR_WS_TRANSPORT_TIMEOUT_SEC
$PublisherProcess = $null
$CloserProcess = $null
$GodotProcess = $null
$ExitCode = 1

Write-Host "SmartXR Godot script-only WSTransport probe"
Write-Host "Work dir: $WorkDir"
Write-Host "Live WebSocket: $LiveWsUrl"
Write-Host "Offline WebSocket (accept-then-close listener): $OfflineWsUrl"
Write-Host "Status file: $StatusFile"
Write-Host ""

try {
    $PublisherArgs = @(
        $Publisher,
        "--host", $HostName,
        "--port", [string]$Port,
        "--hz", "20",
        "--log-every", "5"
    )
    $PublisherProcess = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList $PublisherArgs `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $PublisherLog `
        -RedirectStandardError $PublisherErr `
        -PassThru

    if (-not (Wait-ForLogText -Path $PublisherLog -Text "proxy_targets fake publisher listening" -TimeoutSeconds 5.0)) {
        Write-Host "Publisher did not report ready before timeout."
    }

    $CloserProcess = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @($CloserScript, $HostName, [string]$OfflinePort) `
        -WorkingDirectory $WorkDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $CloserLog `
        -RedirectStandardError $CloserErr `
        -PassThru

    if (-not (Wait-ForLogText -Path $CloserLog -Text "tcp closer listening" -TimeoutSeconds 5.0)) {
        Write-Host "TCP closer did not report ready before timeout."
    }

    $env:SMARTXR_WS_TRANSPORT_SCRIPT = ([System.IO.Path]::GetFullPath($TransportScript)).Replace("\", "/")
    $env:SMARTXR_WS_TRANSPORT_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
    $env:SMARTXR_WS_TRANSPORT_LIVE_WS_URL = $LiveWsUrl
    $env:SMARTXR_WS_TRANSPORT_OFFLINE_WS_URL = $OfflineWsUrl
    $env:SMARTXR_WS_TRANSPORT_TIMEOUT_SEC = [string]$TimeoutSeconds

    $GodotProcess = Start-Process -FilePath $GodotExe -ArgumentList @(
        "--headless",
        "--script", $ProbeScript
    ) -WorkingDirectory $RepoRoot -NoNewWindow -PassThru `
        -RedirectStandardOutput $GodotLog -RedirectStandardError $GodotErrLog
    $null = $GodotProcess.Handle  # cache handle so .ExitCode is readable after exit

    if (-not $GodotProcess.WaitForExit([int]($ProcessTimeoutSeconds * 1000))) {
        Stop-ChildProcess -Process $GodotProcess
        Write-Error "Godot WSTransport probe timed out after $ProcessTimeoutSeconds seconds"
    }
    $ExitCode = $GodotProcess.ExitCode
    if ($null -eq $ExitCode) {
        $ExitCode = 1
    }
} finally {
    Stop-ChildProcess -Process $GodotProcess
    Stop-ChildProcess -Process $PublisherProcess
    Stop-ChildProcess -Process $CloserProcess
    Restore-EnvVar -Name "SMARTXR_WS_TRANSPORT_SCRIPT" -Value $OldTransportScript
    Restore-EnvVar -Name "SMARTXR_WS_TRANSPORT_PROBE_STATUS_PATH" -Value $OldStatusPath
    Restore-EnvVar -Name "SMARTXR_WS_TRANSPORT_LIVE_WS_URL" -Value $OldLiveUrl
    Restore-EnvVar -Name "SMARTXR_WS_TRANSPORT_OFFLINE_WS_URL" -Value $OldOfflineUrl
    Restore-EnvVar -Name "SMARTXR_WS_TRANSPORT_TIMEOUT_SEC" -Value $OldTimeout
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "probe status file was not written"
    if ($ExitCode -eq 0) {
        $ExitCode = 1
    }
}

if ($ExitCode -ne 0) {
    Write-Error "WSTransport probe FAILED (exit $ExitCode)"
}
Write-Host "WSTransport probe PASSED"
