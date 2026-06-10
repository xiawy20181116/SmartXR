param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$WsUrl = "ws://127.0.0.1:8766/proxy_targets",
    [double]$TimeoutSeconds = 10.0,
    [double]$ProcessTimeoutSeconds = 15.0
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\proxy_targets_consumer_only"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_consumer_only.log"
$GodotErr = Join-Path -Path $WorkDir -ChildPath "godot_consumer_only.err.log"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "proxy_targets_consumer_only_status.json"
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_websocket_staged_probe.gd"
$ConsumerScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\proxy_targets_consumer.gd"
$CardAdapterScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\proxy_targets_card_adapter.gd"

function Assert-PathUnderRepo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $RepoFullPath = [System.IO.Path]::GetFullPath($RepoRoot)
    $TargetFullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $TargetFullPath.StartsWith($RepoFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside repo: $TargetFullPath"
    }
}

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

Assert-PathUnderRepo -Path $WorkDir -RepoRoot $RepoRoot

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $ConsumerScript, $CardAdapterScript)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required file not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $GodotLog, $GodotErr, $StatusFile -Force -ErrorAction SilentlyContinue

$OldWsUrl = $env:PROXY_TARGETS_WS_URL
$OldStage = $env:PROXY_TARGETS_STAGE
$OldStatusRes = $env:PROXY_TARGETS_STAGE_STATUS_RES
$OldTimeout = $env:PROXY_TARGETS_STAGE_TIMEOUT_SEC
$OldConsumerScript = $env:PROXY_TARGETS_CONSUMER_SCRIPT
$OldCardAdapterScript = $env:PROXY_TARGETS_CARD_ADAPTER_SCRIPT
$GodotProcess = $null
$ExitCode = 1

Write-Host "SmartXR Godot proxy_targets consumer-only staged apply"
Write-Host "Work dir: $WorkDir"
Write-Host "WebSocket: $WsUrl"
Write-Host "Status file: $StatusFile"
Write-Host "Publisher: external/already running; this script does not start one."
Write-Host ""

try {
    $env:PROXY_TARGETS_WS_URL = $WsUrl
    $env:PROXY_TARGETS_STAGE = "apply"
    $env:PROXY_TARGETS_STAGE_STATUS_RES = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
    $env:PROXY_TARGETS_STAGE_TIMEOUT_SEC = [string]$TimeoutSeconds
    $env:PROXY_TARGETS_CONSUMER_SCRIPT = ([System.IO.Path]::GetFullPath($ConsumerScript)).Replace("\", "/")
    $env:PROXY_TARGETS_CARD_ADAPTER_SCRIPT = ([System.IO.Path]::GetFullPath($CardAdapterScript)).Replace("\", "/")

    $GodotProcess = Start-Process `
        -FilePath $GodotExe `
        -ArgumentList @("--headless", "--script", $ProbeScript) `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $GodotLog `
        -RedirectStandardError $GodotErr `
        -PassThru

    $WaitMs = [Math]::Max(1000, [int]($ProcessTimeoutSeconds * 1000))
    if (-not $GodotProcess.WaitForExit($WaitMs)) {
        Write-Host "Godot consumer-only probe timed out after $ProcessTimeoutSeconds seconds; killing process $($GodotProcess.Id)."
        Stop-ChildProcess -Process $GodotProcess
        $ExitCode = 124
    } else {
        $GodotProcess.Refresh()
        $ExitCode = $GodotProcess.ExitCode
        if ($null -eq $ExitCode) {
            $ExitCode = 1
        }
    }

    if (Test-Path -LiteralPath $StatusFile) {
        $StatusText = Get-Content -LiteralPath $StatusFile -Raw
        Write-Host "Status:"
        Write-Host $StatusText
        $Status = $StatusText | ConvertFrom-Json
        if (
            [int]$Status.packets -gt 0 -and
            [int]$Status.parsed -gt 0 -and
            [int]$Status.live -gt 0 -and
            [int]$Status.registered_targets -gt 0 -and
            [int]$Status.attachments -gt 0
        ) {
            $ExitCode = 0
        } elseif ($ExitCode -eq 0) {
            $ExitCode = 1
        }
    } else {
        Write-Host "Status file was not written."
        if ($ExitCode -eq 0) {
            $ExitCode = 1
        }
    }
} finally {
    Stop-ChildProcess -Process $GodotProcess

    Restore-EnvVar -Name "PROXY_TARGETS_WS_URL" -Value $OldWsUrl
    Restore-EnvVar -Name "PROXY_TARGETS_STAGE" -Value $OldStage
    Restore-EnvVar -Name "PROXY_TARGETS_STAGE_STATUS_RES" -Value $OldStatusRes
    Restore-EnvVar -Name "PROXY_TARGETS_STAGE_TIMEOUT_SEC" -Value $OldTimeout
    Restore-EnvVar -Name "PROXY_TARGETS_CONSUMER_SCRIPT" -Value $OldConsumerScript
    Restore-EnvVar -Name "PROXY_TARGETS_CARD_ADAPTER_SCRIPT" -Value $OldCardAdapterScript

    Write-Host ""
    Write-Host "Logs:"
    Write-Host "  Godot stdout: $GodotLog"
    Write-Host "  Godot stderr: $GodotErr"
    Write-Host "  Status JSON:  $StatusFile"
}

exit $ExitCode
