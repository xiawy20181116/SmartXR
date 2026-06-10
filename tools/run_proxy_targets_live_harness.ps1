param(
    [string]$GodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe",
    [ValidateSet("packets", "parsed", "live")]
    [string]$Require = "live",
    [string]$WsUrl = "ws://127.0.0.1:8766/proxy_targets",
    [double]$TimeoutSeconds = 10.0,
    [switch]$PrepareOnly,
    [switch]$ScriptOnly
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath
$SourceProjectDir = Join-Path -Path $RepoRoot -ChildPath "godot-android"
$TempProjectDir = Join-Path -Path $RepoRoot -ChildPath ".tmp\proxy_targets_live_harness_project"
$HarnessScript = "res://tests/proxy_targets_live_harness.gd"
$ScriptPath = Join-Path -Path $SourceProjectDir -ChildPath "tests\proxy_targets_live_harness.gd"
$ConsumerScriptPath = Join-Path -Path $SourceProjectDir -ChildPath "scripts\proxy_targets_consumer.gd"
$CardAdapterScriptPath = Join-Path -Path $SourceProjectDir -ChildPath "scripts\proxy_targets_card_adapter.gd"

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

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($Path), $Content, $Encoding)
}

function Write-HarnessProjectFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $ProjectFile = Join-Path $ProjectDir "project.godot"
    $ProjectContent = @'
; Engine configuration file.
config_version=5

[application]
config/name="proxy_targets_live_harness"
run/main_scene=""

[rendering]
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
'@
    Write-Utf8NoBom -Path $ProjectFile -Content $ProjectContent
}

function Copy-HarnessFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $SourcePath = Join-Path $SourceProjectDir $RelativePath
    $DestinationPath = Join-Path $TempProjectDir $RelativePath
    if (-not (Test-Path -LiteralPath $SourcePath)) {
        throw "Required harness file not found: $SourcePath"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $DestinationPath) | Out-Null
    Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
}

function Ensure-GodotUserLogsDir {
    $AppData = $env:APPDATA
    if ([string]::IsNullOrWhiteSpace($AppData)) {
        return
    }

    $LogsDir = Join-Path -Path $AppData -ChildPath "Godot\app_userdata\proxy_targets_live_harness\logs"
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
}

function Build-HarnessProject {
    Assert-PathUnderRepo -Path $TempProjectDir -RepoRoot $RepoRoot

    if (Test-Path -LiteralPath $TempProjectDir) {
        Remove-Item -LiteralPath $TempProjectDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $TempProjectDir | Out-Null

    Write-HarnessProjectFile -ProjectDir $TempProjectDir
    Copy-HarnessFile -RelativePath "scripts\proxy_targets_consumer.gd"
    Copy-HarnessFile -RelativePath "scripts\proxy_targets_card_adapter.gd"
    Copy-HarnessFile -RelativePath "tests\proxy_targets_live_harness.gd"

    return $TempProjectDir
}

if (-not (Test-Path -LiteralPath $GodotExe)) {
    throw "Godot executable not found: $GodotExe"
}

if (-not (Test-Path -LiteralPath (Join-Path $SourceProjectDir "project.godot"))) {
    throw "Godot source project not found: $SourceProjectDir"
}

$OldWsUrl = $env:PROXY_TARGETS_WS_URL
$OldRequire = $env:PROXY_TARGETS_REQUIRE
$OldTimeout = $env:PROXY_TARGETS_TIMEOUT_SEC
$OldConsumerScript = $env:PROXY_TARGETS_CONSUMER_SCRIPT
$OldCardAdapterScript = $env:PROXY_TARGETS_CARD_ADAPTER_SCRIPT
$ExitCode = 0

$ProjectDir = Build-HarnessProject
Ensure-GodotUserLogsDir

Write-Host "SmartXR proxy_targets non-XR live harness"
Write-Host "Source project: $SourceProjectDir"
Write-Host "Stripped project: $ProjectDir"
Write-Host "Script-only: $ScriptOnly"
Write-Host "WebSocket: $WsUrl"
Write-Host "Require: $Require"

if ($PrepareOnly) {
    exit 0
}

try {
    $env:PROXY_TARGETS_WS_URL = $WsUrl
    $env:PROXY_TARGETS_REQUIRE = $Require
    $env:PROXY_TARGETS_TIMEOUT_SEC = [string]$TimeoutSeconds
    $env:PROXY_TARGETS_CONSUMER_SCRIPT = ([System.IO.Path]::GetFullPath($ConsumerScriptPath)).Replace("\", "/")
    $env:PROXY_TARGETS_CARD_ADAPTER_SCRIPT = ([System.IO.Path]::GetFullPath($CardAdapterScriptPath)).Replace("\", "/")

    if ($ScriptOnly) {
        & $GodotExe --headless --script $ScriptPath
    } else {
        & $GodotExe --headless --path $ProjectDir --script $HarnessScript
    }
    $ExitCode = $LASTEXITCODE
} finally {
    if ($null -eq $OldWsUrl) {
        Remove-Item Env:\PROXY_TARGETS_WS_URL -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_WS_URL = $OldWsUrl
    }

    if ($null -eq $OldRequire) {
        Remove-Item Env:\PROXY_TARGETS_REQUIRE -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_REQUIRE = $OldRequire
    }

    if ($null -eq $OldTimeout) {
        Remove-Item Env:\PROXY_TARGETS_TIMEOUT_SEC -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_TIMEOUT_SEC = $OldTimeout
    }

    if ($null -eq $OldConsumerScript) {
        Remove-Item Env:\PROXY_TARGETS_CONSUMER_SCRIPT -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_CONSUMER_SCRIPT = $OldConsumerScript
    }

    if ($null -eq $OldCardAdapterScript) {
        Remove-Item Env:\PROXY_TARGETS_CARD_ADAPTER_SCRIPT -ErrorAction SilentlyContinue
    } else {
        $env:PROXY_TARGETS_CARD_ADAPTER_SCRIPT = $OldCardAdapterScript
    }
}

exit $ExitCode
