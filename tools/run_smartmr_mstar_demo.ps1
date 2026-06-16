param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$PythonExe = "python",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8775,
    [double]$TimeoutSeconds = 8.0,
    [double]$ProcessTimeoutSeconds = 30.0
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_assistant_updates_probe.gd"
$ReceiverScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\assistant\assistant_updates_receiver.gd"
$StateScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\assistant\assistant_card_state.gd"
$ViewScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\assistant\assistant_card_view.gd"
$TransportScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\ws_transport.gd"
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\smartmr_mstar_demo_publisher.py"
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\smartmr_mstar_demo"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "smartmr_mstar_demo_status.json"
$PublisherLog = Join-Path -Path $WorkDir -ChildPath "publisher.log"
$PublisherErr = Join-Path -Path $WorkDir -ChildPath "publisher.err.log"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_smartmr_mstar_demo.log"
$GodotErrLog = Join-Path -Path $WorkDir -ChildPath "godot_smartmr_mstar_demo.err.log"
$LiveWsUrl = "ws://${HostName}:${Port}/assistant_updates"

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

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $ReceiverScript, $StateScript, $ViewScript, $TransportScript, $Publisher)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        Write-Error "required path not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $StatusFile, $PublisherLog, $PublisherErr, $GodotLog, $GodotErrLog -Force -ErrorAction SilentlyContinue

$OldReceiverScript = $env:SMARTXR_ASSISTANT_UPDATES_RECEIVER_SCRIPT
$OldStateScript = $env:SMARTXR_ASSISTANT_CARD_STATE_SCRIPT
$OldViewScript = $env:SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT
$OldTransportScript = $env:SMARTXR_WS_TRANSPORT_SCRIPT
$OldStatusPath = $env:SMARTXR_ASSISTANT_UPDATES_PROBE_STATUS_PATH
$OldLiveUrl = $env:SMARTXR_ASSISTANT_UPDATES_LIVE_WS_URL
$OldTimeout = $env:SMARTXR_ASSISTANT_UPDATES_TIMEOUT_SEC
$OldExpectedResponse = $env:SMARTXR_ASSISTANT_UPDATES_EXPECTED_RESPONSE_TEXT
$OldExpectedStatus = $env:SMARTXR_ASSISTANT_UPDATES_EXPECTED_STATUS_LINE
$PublisherProcess = $null
$GodotProcess = $null
$ExitCode = 1

Write-Host "SmartMR M-star demo probe"
Write-Host "Work dir: $WorkDir"
Write-Host "Live WebSocket: $LiveWsUrl"
Write-Host "Status file: $StatusFile"
Write-Host ""

try {
    $PublisherProcess = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @($Publisher, "--host", $HostName, "--port", [string]$Port, "--hz", "20", "--log-every", "5") `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $PublisherLog `
        -RedirectStandardError $PublisherErr `
        -PassThru

    if (-not (Wait-ForLogText -Path $PublisherLog -Text "assistant_updates M-star demo publisher listening" -TimeoutSeconds 5.0)) {
        Write-Host "Publisher did not report ready before timeout."
    }

    $env:SMARTXR_ASSISTANT_UPDATES_RECEIVER_SCRIPT = ([System.IO.Path]::GetFullPath($ReceiverScript)).Replace("\", "/")
    $env:SMARTXR_ASSISTANT_CARD_STATE_SCRIPT = ([System.IO.Path]::GetFullPath($StateScript)).Replace("\", "/")
    $env:SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT = ([System.IO.Path]::GetFullPath($ViewScript)).Replace("\", "/")
    $env:SMARTXR_WS_TRANSPORT_SCRIPT = ([System.IO.Path]::GetFullPath($TransportScript)).Replace("\", "/")
    $env:SMARTXR_ASSISTANT_UPDATES_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
    $env:SMARTXR_ASSISTANT_UPDATES_LIVE_WS_URL = $LiveWsUrl
    $env:SMARTXR_ASSISTANT_UPDATES_TIMEOUT_SEC = [string]$TimeoutSeconds
    $env:SMARTXR_ASSISTANT_UPDATES_EXPECTED_RESPONSE_TEXT = "Ada Lovelace is working on XR-42: Prepare MR assistant demo."
    $env:SMARTXR_ASSISTANT_UPDATES_EXPECTED_STATUS_LINE = "Ada Lovelace | XR-42 | In Progress"

    $GodotProcess = Start-Process -FilePath $GodotExe -ArgumentList @(
        "--headless",
        "--script", $ProbeScript
    ) -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $GodotLog -RedirectStandardError $GodotErrLog
    $null = $GodotProcess.Handle

    if (-not $GodotProcess.WaitForExit([int]($ProcessTimeoutSeconds * 1000))) {
        Stop-ChildProcess -Process $GodotProcess
        Write-Error "SmartMR M-star demo timed out after $ProcessTimeoutSeconds seconds"
    }
    $ExitCode = $GodotProcess.ExitCode
    if ($null -eq $ExitCode) {
        $ExitCode = 1
    }
} finally {
    Stop-ChildProcess -Process $GodotProcess
    Stop-ChildProcess -Process $PublisherProcess
    Restore-EnvVar -Name "SMARTXR_ASSISTANT_UPDATES_RECEIVER_SCRIPT" -Value $OldReceiverScript
    Restore-EnvVar -Name "SMARTXR_ASSISTANT_CARD_STATE_SCRIPT" -Value $OldStateScript
    Restore-EnvVar -Name "SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT" -Value $OldViewScript
    Restore-EnvVar -Name "SMARTXR_WS_TRANSPORT_SCRIPT" -Value $OldTransportScript
    Restore-EnvVar -Name "SMARTXR_ASSISTANT_UPDATES_PROBE_STATUS_PATH" -Value $OldStatusPath
    Restore-EnvVar -Name "SMARTXR_ASSISTANT_UPDATES_LIVE_WS_URL" -Value $OldLiveUrl
    Restore-EnvVar -Name "SMARTXR_ASSISTANT_UPDATES_TIMEOUT_SEC" -Value $OldTimeout
    Restore-EnvVar -Name "SMARTXR_ASSISTANT_UPDATES_EXPECTED_RESPONSE_TEXT" -Value $OldExpectedResponse
    Restore-EnvVar -Name "SMARTXR_ASSISTANT_UPDATES_EXPECTED_STATUS_LINE" -Value $OldExpectedStatus
}

Get-Content -Path $GodotLog -ErrorAction SilentlyContinue | Write-Host
if (Test-Path $StatusFile) {
    Write-Host "status: $StatusFile"
    Get-Content -Path $StatusFile | Write-Host
} else {
    Write-Warning "demo status file was not written"
    if ($ExitCode -eq 0) {
        $ExitCode = 1
    }
}

if ($ExitCode -ne 0) {
    Write-Error "SmartMR M-star demo FAILED (exit $ExitCode)"
}
Write-Host "SmartMR M-star demo PASSED"
