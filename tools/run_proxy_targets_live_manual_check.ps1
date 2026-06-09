param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$PythonExe = "python",
    [ValidateSet("packets", "parsed", "live")]
    [string]$Require = "live",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8766,
    [ValidateSet("moving", "static")]
    [string]$Mode = "moving",
    [double]$Hz = 20.0,
    [int]$LogEvery = 20,
    [double]$TimeoutSeconds = 10.0,
    [double]$ProcessTimeoutSeconds = 25.0
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\proxy_targets_live_manual_check"
$GateLog = Join-Path -Path $WorkDir -ChildPath "script_only_staged_probe.log"
$GateErr = Join-Path -Path $WorkDir -ChildPath "script_only_staged_probe.err.log"
$GateRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_godot_script_only_staged_probe.ps1"
$StageStatusFile = Join-Path -Path $RepoRoot -ChildPath ".tmp\script_only_staged_probe\apply\script_only_websocket_staged_probe_status.json"

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

Assert-PathUnderRepo -Path $WorkDir -RepoRoot $RepoRoot

if (-not (Test-Path -LiteralPath $GodotExe)) {
    throw "Godot executable not found: $GodotExe"
}
if (-not (Test-Path -LiteralPath $GateRunner)) {
    throw "Staged gate runner not found: $GateRunner"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $GateLog, $GateErr -Force -ErrorAction SilentlyContinue

$GateProcess = $null
$RawGateExitCode = $null
$ExitCode = 1

Write-Host "SmartXR proxy_targets manual live check"
Write-Host "Godot gate: script_only_staged_probe apply"
Write-Host "Work dir: $WorkDir"
Write-Host "WebSocket: ws://${HostName}:${Port}/proxy_targets"
Write-Host "Require: $Require"
Write-Host "Status file: $StageStatusFile"
Write-Host ""

try {
    $GateArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $GateRunner,
        "-GodotExe", $GodotExe,
        "-PythonExe", $PythonExe,
        "-HostName", $HostName,
        "-StartPort", [string]$Port,
        "-Stage", "apply",
        "-TimeoutSeconds", [string]$TimeoutSeconds,
        "-ProcessTimeoutSeconds", [string]$ProcessTimeoutSeconds
    )

    $GateProcess = Start-Process `
        -FilePath "powershell" `
        -ArgumentList $GateArgs `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $GateLog `
        -RedirectStandardError $GateErr `
        -PassThru

    $WaitMs = [Math]::Max(1000, [int](($ProcessTimeoutSeconds + 5.0) * 1000))
    if (-not $GateProcess.WaitForExit($WaitMs)) {
        Write-Host "Staged apply gate timed out after $($ProcessTimeoutSeconds + 5.0) seconds; killing process $($GateProcess.Id)."
        Stop-ChildProcess -Process $GateProcess
        $RawGateExitCode = 124
        $ExitCode = 124
    } else {
        $GateProcess.Refresh()
        $RawGateExitCode = $GateProcess.ExitCode
        if ($null -eq $RawGateExitCode) {
            Write-Host "Staged apply gate exited but no exit code was reported."
            $RawGateExitCode = 1
        }
        $ExitCode = $RawGateExitCode
    }

    Write-Host "Staged apply raw gate exit code: $RawGateExitCode"
    if (Test-Path -LiteralPath $StageStatusFile) {
        $StatusText = Get-Content -LiteralPath $StageStatusFile -Raw
        Write-Host "Status:"
        Write-Host $StatusText

        $Status = $StatusText | ConvertFrom-Json
        $RequirementMet = $false
        if ($Require -eq "packets") {
            $RequirementMet = ([int]$Status.packets -gt 0)
        } elseif ($Require -eq "parsed") {
            $RequirementMet = ([int]$Status.parsed -gt 0)
        } else {
            $RequirementMet = (
                ([int]$Status.live -gt 0) -and
                ([int]$Status.registered_targets -gt 0) -and
                ([int]$Status.attachments -gt 0)
            )
        }

        if ($RequirementMet) {
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

    Write-Host "Final validation exit code: $ExitCode"
} finally {
    Stop-ChildProcess -Process $GateProcess

    Write-Host ""
    Write-Host "Logs:"
    Write-Host "  Staged stdout: $GateLog"
    Write-Host "  Staged stderr: $GateErr"
    Write-Host "  Status JSON:   $StageStatusFile"
}

if ($null -eq $ExitCode) {
    $ExitCode = 1
}
exit $ExitCode
