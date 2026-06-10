param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [string]$PythonExe = "python",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8771,
    [double]$TimeoutSeconds = 5.0,
    [double]$ProcessTimeoutSeconds = 12.0
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\script_only_tcp_probe"
$PublisherLog = Join-Path -Path $WorkDir -ChildPath "publisher.log"
$PublisherErr = Join-Path -Path $WorkDir -ChildPath "publisher.err.log"
$GodotLog = Join-Path -Path $WorkDir -ChildPath "godot_tcp_probe.log"
$GodotErr = Join-Path -Path $WorkDir -ChildPath "godot_tcp_probe.err.log"
$StatusFile = Join-Path -Path $WorkDir -ChildPath "script_only_tcp_probe_status.json"
$Publisher = Join-Path -Path $RepoRoot -ChildPath "tools\fake_proxy_targets_publisher.py"
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_tcp_probe.gd"

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

Assert-PathUnderRepo -Path $WorkDir -RepoRoot $RepoRoot

if (-not (Test-Path -LiteralPath $GodotExe)) {
    throw "Godot executable not found: $GodotExe"
}
if (-not (Test-Path -LiteralPath $Publisher)) {
    throw "Fake publisher not found: $Publisher"
}
if (-not (Test-Path -LiteralPath $ProbeScript)) {
    throw "Godot TCP probe script not found: $ProbeScript"
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
Remove-Item -LiteralPath $PublisherLog, $PublisherErr, $GodotLog, $GodotErr, $StatusFile -Force -ErrorAction SilentlyContinue

$OldHost = $env:PROXY_TARGETS_TCP_HOST
$OldPort = $env:PROXY_TARGETS_TCP_PORT
$OldStatusRes = $env:PROXY_TARGETS_TCP_STATUS_RES
$OldTimeout = $env:PROXY_TARGETS_TCP_TIMEOUT_SEC
$PublisherProcess = $null
$GodotProcess = $null
$ExitCode = 1

Write-Host "SmartXR Godot script-only TCP probe"
Write-Host "Work dir: $WorkDir"
Write-Host "TCP target: ${HostName}:${Port}"
Write-Host "Status file: $StatusFile"
Write-Host ""

try {
    $PublisherArgs = @(
        $Publisher,
        "--host", $HostName,
        "--port", [string]$Port,
        "--hz", "1",
        "--log-every", "0"
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

    $env:PROXY_TARGETS_TCP_HOST = $HostName
    $env:PROXY_TARGETS_TCP_PORT = [string]$Port
    $env:PROXY_TARGETS_TCP_STATUS_RES = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")
    $env:PROXY_TARGETS_TCP_TIMEOUT_SEC = [string]$TimeoutSeconds

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
        Write-Host "Godot TCP probe timed out after $ProcessTimeoutSeconds seconds; killing process $($GodotProcess.Id)."
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
        if ([int]$Status.tcp_status -eq 2 -and [int]$Status.connect_error -eq 0) {
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
    Stop-ChildProcess -Process $PublisherProcess

    if ($null -eq $OldHost) {
        Remove-Item Env:\PROXY_TARGETS_TCP_HOST -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_TCP_HOST = $OldHost
    }

    if ($null -eq $OldPort) {
        Remove-Item Env:\PROXY_TARGETS_TCP_PORT -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_TCP_PORT = $OldPort
    }

    if ($null -eq $OldStatusRes) {
        Remove-Item Env:\PROXY_TARGETS_TCP_STATUS_RES -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_TCP_STATUS_RES = $OldStatusRes
    }

    if ($null -eq $OldTimeout) {
        Remove-Item Env:\PROXY_TARGETS_TCP_TIMEOUT_SEC -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_TCP_TIMEOUT_SEC = $OldTimeout
    }

    Write-Host ""
    Write-Host "Logs:"
    Write-Host "  Publisher stdout: $PublisherLog"
    Write-Host "  Publisher stderr: $PublisherErr"
    Write-Host "  Godot stdout:     $GodotLog"
    Write-Host "  Godot stderr:     $GodotErr"
    Write-Host "  Status JSON:      $StatusFile"
}

exit $ExitCode
