param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$PythonExe = "python",
    [string]$HostName = "127.0.0.1",
    [int]$StartPort = 8780,
    [string]$PublisherScript = "",
    [string]$PublisherInput = "",
    [switch]$ExternalPublisher,
    [ValidateSet("all", "consumer_load", "consumer_instance", "adapter_instance", "apply")]
    [string]$Stage = "all",
    [double]$TimeoutSeconds = 5.0,
    [double]$ProcessTimeoutSeconds = 12.0
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$WorkRoot = Join-Path -Path $RepoRoot -ChildPath ".tmp\script_only_staged_probe"
$DefaultPublisher = Join-Path -Path $RepoRoot -ChildPath "tools\fake_proxy_targets_publisher.py"
$Publisher = $DefaultPublisher
if (-not [string]::IsNullOrWhiteSpace($PublisherScript)) {
    if ([System.IO.Path]::IsPathRooted($PublisherScript)) {
        $Publisher = $PublisherScript
    } else {
        $Publisher = Join-Path -Path $RepoRoot -ChildPath $PublisherScript
    }
}
$PublisherInputPath = ""
if (-not [string]::IsNullOrWhiteSpace($PublisherInput)) {
    if ([System.IO.Path]::IsPathRooted($PublisherInput)) {
        $PublisherInputPath = $PublisherInput
    } else {
        $PublisherInputPath = Join-Path -Path $RepoRoot -ChildPath $PublisherInput
    }
}
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_websocket_staged_probe.gd"
$ConsumerScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\proxy_targets_consumer.gd"
$CardAdapterScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\proxy_targets_card_adapter.gd"
$AllStages = @("consumer_load", "consumer_instance", "adapter_instance", "apply")
$Stages = $AllStages
if ($Stage -ne "all") {
    $Stages = @($Stage)
}

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

Assert-PathUnderRepo -Path $WorkRoot -RepoRoot $RepoRoot

foreach ($RequiredPath in @($GodotExe, $Publisher, $ProbeScript, $ConsumerScript, $CardAdapterScript)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required file not found: $RequiredPath"
    }
}
if (-not [string]::IsNullOrWhiteSpace($PublisherInputPath) -and -not (Test-Path -LiteralPath $PublisherInputPath)) {
    throw "Required file not found: $PublisherInputPath"
}

New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null

$OldWsUrl = $env:PROXY_TARGETS_WS_URL
$OldStage = $env:PROXY_TARGETS_STAGE
$OldStatusRes = $env:PROXY_TARGETS_STAGE_STATUS_RES
$OldTimeout = $env:PROXY_TARGETS_STAGE_TIMEOUT_SEC
$OldConsumerScript = $env:PROXY_TARGETS_CONSUMER_SCRIPT
$OldCardAdapterScript = $env:PROXY_TARGETS_CARD_ADAPTER_SCRIPT
$OverallExitCode = 0

Write-Host "SmartXR Godot script-only staged WebSocket harness"
Write-Host "Work root: $WorkRoot"
Write-Host "Stages: $($Stages -join ', ')"
if ($ExternalPublisher) {
    Write-Host "Publisher script: external/already running"
} else {
    Write-Host "Publisher script: $Publisher"
    if (-not [string]::IsNullOrWhiteSpace($PublisherInputPath)) {
        Write-Host "Publisher input: $PublisherInputPath"
    }
}
Write-Host ""

try {
    for ($Index = 0; $Index -lt $Stages.Count; $Index++) {
        $Stage = $Stages[$Index]
        $Port = $StartPort + $Index
        $StageDir = Join-Path -Path $WorkRoot -ChildPath $Stage
        $PublisherLog = Join-Path -Path $StageDir -ChildPath "publisher.log"
        $PublisherErr = Join-Path -Path $StageDir -ChildPath "publisher.err.log"
        $GodotLog = Join-Path -Path $StageDir -ChildPath "godot_staged_probe.log"
        $GodotErr = Join-Path -Path $StageDir -ChildPath "godot_staged_probe.err.log"
        $StatusFile = Join-Path -Path $StageDir -ChildPath "script_only_websocket_staged_probe_status.json"
        $WsUrl = "ws://${HostName}:${Port}/proxy_targets"
        $PublisherProcess = $null
        $GodotProcess = $null
        $StageExitCode = 1

        New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
        Remove-Item -LiteralPath $PublisherLog, $PublisherErr, $GodotLog, $GodotErr, $StatusFile -Force -ErrorAction SilentlyContinue

        Write-Host "Stage: $Stage"
        Write-Host "  WebSocket: $WsUrl"

        try {
            if (-not $ExternalPublisher) {
                $PublisherArgs = @($Publisher, "--host", $HostName, "--port", [string]$Port, "--hz", "20", "--log-every", "5")
                if (-not [string]::IsNullOrWhiteSpace($PublisherInputPath)) {
                    $PublisherArgs += @("--input", $PublisherInputPath)
                }
                $PublisherProcess = Start-Process `
                    -FilePath $PythonExe `
                    -ArgumentList $PublisherArgs `
                    -WorkingDirectory $RepoRoot `
                    -WindowStyle Hidden `
                    -RedirectStandardOutput $PublisherLog `
                    -RedirectStandardError $PublisherErr `
                    -PassThru

                if (-not (Wait-ForLogText -Path $PublisherLog -Text "proxy_targets" -TimeoutSeconds 5.0)) {
                    Write-Host "  Publisher did not report ready before timeout."
                }
            } else {
                Write-Host "  Publisher: external/already running"
            }

            $env:PROXY_TARGETS_WS_URL = $WsUrl
            $env:PROXY_TARGETS_STAGE = $Stage
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
                Write-Host "  Godot staged probe timed out after $ProcessTimeoutSeconds seconds; killing process $($GodotProcess.Id)."
                Stop-ChildProcess -Process $GodotProcess
                $StageExitCode = 124
            } else {
                $GodotProcess.Refresh()
                $StageExitCode = $GodotProcess.ExitCode
                if ($null -eq $StageExitCode) {
                    $StageExitCode = 1
                }
            }

            if (Test-Path -LiteralPath $StatusFile) {
                $StatusText = Get-Content -LiteralPath $StatusFile -Raw
                Write-Host "  Status: $StatusText"
                $Status = $StatusText | ConvertFrom-Json
                if ($Stage -eq "apply") {
                    if ([int]$Status.live -gt 0 -and [int]$Status.registered_targets -gt 0 -and [int]$Status.attachments -gt 0) {
                        $StageExitCode = 0
                    }
                } elseif ([bool]$Status.setup_ok -and [int]$Status.packets -gt 0) {
                    $StageExitCode = 0
                }
            } else {
                Write-Host "  Status file was not written."
            }
        } finally {
            Stop-ChildProcess -Process $GodotProcess
            Stop-ChildProcess -Process $PublisherProcess
        }

        Write-Host "  Exit: $StageExitCode"
        Write-Host "  Logs: $StageDir"
        Write-Host ""

        if ($StageExitCode -ne 0) {
            $OverallExitCode = 1
        }
    }
} finally {
    Restore-EnvVar -Name "PROXY_TARGETS_WS_URL" -Value $OldWsUrl
    Restore-EnvVar -Name "PROXY_TARGETS_STAGE" -Value $OldStage
    Restore-EnvVar -Name "PROXY_TARGETS_STAGE_STATUS_RES" -Value $OldStatusRes
    Restore-EnvVar -Name "PROXY_TARGETS_STAGE_TIMEOUT_SEC" -Value $OldTimeout
    Restore-EnvVar -Name "PROXY_TARGETS_CONSUMER_SCRIPT" -Value $OldConsumerScript
    Restore-EnvVar -Name "PROXY_TARGETS_CARD_ADAPTER_SCRIPT" -Value $OldCardAdapterScript
}

exit $OverallExitCode
