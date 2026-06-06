param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("enable", "disable")]
    [string]$Mode,
    [string]$ProjectDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")) "godot-android")
)

$ErrorActionPreference = "Stop"

$ExtensionResource = "res://addons/gxr_sdk/gxr_sdk.gdextension"
$ExtensionFile = Join-Path $ProjectDir "addons\gxr_sdk\gxr_sdk.gdextension"
$DisabledExtensionFile = Join-Path $ProjectDir "addons\gxr_sdk\gxr_sdk.gdextension.disabled"
$GodotDir = Join-Path $ProjectDir ".godot"
$ExtensionList = Join-Path $GodotDir "extension_list.cfg"

function Write-Utf8NoBomLines {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [string[]]$Lines
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    $Content = [string]::Join([Environment]::NewLine, $Lines)
    if ($Lines.Count -gt 0) {
        $Content += [Environment]::NewLine
    }
    [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($Path), $Content, $Encoding)
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "project.godot"))) {
    throw "Godot project not found: $ProjectDir"
}

New-Item -ItemType Directory -Force -Path $GodotDir | Out-Null

$Lines = @()
if (Test-Path -LiteralPath $ExtensionList) {
    $Lines = @(Get-Content -LiteralPath $ExtensionList -Encoding UTF8)
}

$FilteredLines = @($Lines | Where-Object { $_.Trim() -ne $ExtensionResource })

if ($Mode -eq "disable") {
    if (Test-Path -LiteralPath $ExtensionFile) {
        Move-Item -LiteralPath $ExtensionFile -Destination $DisabledExtensionFile -Force
    }
    Write-Utf8NoBomLines -Path $ExtensionList -Lines $FilteredLines
    Write-Host "GXR extension disabled for Windows validation: $ExtensionResource"
} elseif ($Mode -eq "enable") {
    if (Test-Path -LiteralPath $DisabledExtensionFile) {
        Move-Item -LiteralPath $DisabledExtensionFile -Destination $ExtensionFile -Force
    }
    if (-not ($FilteredLines | Where-Object { $_.Trim() -eq $ExtensionResource })) {
        $FilteredLines += $ExtensionResource
    }
    Write-Utf8NoBomLines -Path $ExtensionList -Lines $FilteredLines
    Write-Host "GXR extension enabled for Android export: $ExtensionResource"
}
