param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$WorkDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\proxy_targets_consumer_probe"
$StatusFile = Join-Path -Path $WorkDir -ChildPath ("proxy_targets_consumer_probe_status_{0}.json" -f [System.Guid]::NewGuid().ToString("N"))
$ProbeScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\tests\script_only_proxy_targets_consumer_probe.gd"
$ConsumerScript = Join-Path -Path $RepoRoot -ChildPath "godot-android\scripts\proxy_targets_consumer.gd"

foreach ($RequiredPath in @($GodotExe, $ProbeScript, $ConsumerScript)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required file not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

$OldConsumerScript = $env:PROXY_TARGETS_CONSUMER_SCRIPT
$OldStatusPath = $env:PROXY_TARGETS_CONSUMER_PROBE_STATUS_PATH

try {
    $env:PROXY_TARGETS_CONSUMER_SCRIPT = ([System.IO.Path]::GetFullPath($ConsumerScript)).Replace("\", "/")
    $env:PROXY_TARGETS_CONSUMER_PROBE_STATUS_PATH = ([System.IO.Path]::GetFullPath($StatusFile)).Replace("\", "/")

    & $GodotExe --headless --script $ProbeScript
    $ExitCode = $LASTEXITCODE

    $Deadline = (Get-Date).AddSeconds(5)
    while (-not (Test-Path -LiteralPath $StatusFile) -and (Get-Date) -lt $Deadline) {
        Start-Sleep -Milliseconds 100
    }

    if (Test-Path -LiteralPath $StatusFile) {
        $StatusJson = Get-Content -LiteralPath $StatusFile -Raw
        Write-Host $StatusJson
        $Status = $StatusJson | ConvertFrom-Json
        if ($null -ne $Status.exit_code) {
            $ExitCode = [int]$Status.exit_code
        }
    } else {
        Write-Host "Status file was not written: $StatusFile"
        if ($ExitCode -eq 0) {
            $ExitCode = 1
        }
    }
} finally {
    if ($null -eq $OldConsumerScript) {
        Remove-Item Env:\PROXY_TARGETS_CONSUMER_SCRIPT -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_CONSUMER_SCRIPT = $OldConsumerScript
    }
    if ($null -eq $OldStatusPath) {
        Remove-Item Env:\PROXY_TARGETS_CONSUMER_PROBE_STATUS_PATH -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_CONSUMER_PROBE_STATUS_PATH = $OldStatusPath
    }
}

exit $ExitCode
