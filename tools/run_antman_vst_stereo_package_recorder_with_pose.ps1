param(
    [string]$OutDir = ".tmp\antman_vst_stereo_package_with_pose",
    [double]$DurationSeconds = 10.0,
    [string]$SmartXROptionsPath = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = [string](Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath ".."))
$PcmrRunner = Join-Path -Path $RepoRoot -ChildPath "tools\run_windows_pcmr.ps1"
$Recorder = Join-Path -Path $RepoRoot -ChildPath "tools\record_antman_vst_stereo_package.py"
$Merger = Join-Path -Path $RepoRoot -ChildPath "tools\merge_stereo_pose_trace.py"

function Resolve-RunnerPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path -Path $RepoRoot -ChildPath $Path))
}

function ConvertTo-PowerShellLiteral {
    param(
        [AllowNull()]
        [string]$Value
    )

    if ($null -eq $Value) {
        return "''"
    }
    return "'" + $Value.Replace("'", "''") + "'"
}

$ResolvedOutDir = Resolve-RunnerPath -Path $OutDir
$ResolvedSmartXROptionsPath = ""
if (-not [string]::IsNullOrWhiteSpace($SmartXROptionsPath)) {
    $ResolvedSmartXROptionsPath = Resolve-RunnerPath -Path $SmartXROptionsPath
}
$PoseTracePath = Join-Path -Path $ResolvedOutDir -ChildPath "xr_pose_trace.jsonl"
$FramePoseAssocPath = Join-Path -Path $ResolvedOutDir -ChildPath "frame_pose_assoc.jsonl"
$PcmrStopFile = Join-Path -Path $ResolvedOutDir -ChildPath ".pcmr_pose_stop"
$PcmrRunSeconds = [Math]::Max(0.5, $DurationSeconds + 2.0)
$PcmrRunSecondsText = [string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0}", $PcmrRunSeconds)

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

function Request-PcmrStop {
    param(
        $Process,
        [Parameter(Mandatory = $true)]
        [string]$StopFile
    )

    if ($null -eq $Process) {
        return
    }

    New-Item -ItemType File -Force -Path $StopFile | Out-Null
    if (-not $Process.HasExited) {
        $Process.WaitForExit(10000) | Out-Null
    }
    if (-not $Process.HasExited) {
        Stop-ChildProcess -Process $Process
    }
}

if (-not (Test-Path -LiteralPath $PcmrRunner)) {
    throw "PCMR runner not found: $PcmrRunner"
}
if (-not (Test-Path -LiteralPath $Recorder)) {
    throw "Stereo recorder not found: $Recorder"
}
if (-not (Test-Path -LiteralPath $Merger)) {
    throw "Pose merge tool not found: $Merger"
}

New-Item -ItemType Directory -Force -Path $ResolvedOutDir | Out-Null
Remove-Item -LiteralPath $PoseTracePath, $FramePoseAssocPath, $PcmrStopFile -Force -ErrorAction SilentlyContinue

Write-Host "SmartXR Antman VST stereo package recorder with pose"
Write-Host "Output:      $ResolvedOutDir"
Write-Host "Duration:    $DurationSeconds seconds"
Write-Host "Pose trace:  $PoseTracePath"
Write-Host "Assoc JSONL: $FramePoseAssocPath"
Write-Host "Options:     $ResolvedSmartXROptionsPath"

$OldSmartXrPoseTracePath = $env:SMARTXR_XR_POSE_TRACE_PATH
$PcmrProcess = $null

try {
    $env:SMARTXR_XR_POSE_TRACE_PATH = $PoseTracePath

    $PcmrCommand = "& " + (ConvertTo-PowerShellLiteral $PcmrRunner)
    $PcmrCommand += " -RunForSeconds " + $PcmrRunSecondsText
    $PcmrCommand += " -StopWhenFileExists " + (ConvertTo-PowerShellLiteral $PcmrStopFile)
    if (-not [string]::IsNullOrWhiteSpace($ResolvedSmartXROptionsPath)) {
        $PcmrCommand += " -SmartXROptionsPath " + (ConvertTo-PowerShellLiteral $ResolvedSmartXROptionsPath)
    }
    $EncodedPcmrCommand = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($PcmrCommand))
    $PcmrNativeArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-EncodedCommand", $EncodedPcmrCommand
    )

    $PcmrProcess = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $PcmrNativeArgs `
        -WorkingDirectory $RepoRoot `
        -PassThru

    python $Recorder `
        --out-dir $ResolvedOutDir `
        --duration-seconds "$DurationSeconds"
    $RecordExitCode = $LASTEXITCODE
    if ($RecordExitCode -ne 0) {
        exit $RecordExitCode
    }

    Request-PcmrStop -Process $PcmrProcess -StopFile $PcmrStopFile
    $PcmrExitCode = $PcmrProcess.ExitCode
    $PcmrProcess = $null
    if ($PcmrExitCode -ne 0) {
        exit $PcmrExitCode
    }

    python $Merger `
        --package-dir $ResolvedOutDir `
        --pose-trace $PoseTracePath `
        --output $FramePoseAssocPath
    exit $LASTEXITCODE
} finally {
    Request-PcmrStop -Process $PcmrProcess -StopFile $PcmrStopFile
    Restore-EnvVar -Name "SMARTXR_XR_POSE_TRACE_PATH" -Value $OldSmartXrPoseTracePath
}
