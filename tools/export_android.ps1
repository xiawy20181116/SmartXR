param(
    [switch]$Release,
    [switch]$PreflightOnly,
    [switch]$SmokeTest,
    [string]$DeviceSerial = $env:ANDROID_SERIAL,
    [string]$GodotExe = $env:SMARTXR_GODOT_EXE,
    [string]$AndroidSdk = $env:ANDROID_HOME,
    [string]$JavaHome = $env:JAVA_HOME
)

$ErrorActionPreference = "Stop"

$GodotVersion = "4.6.2"
$GodotTemplateVersion = "4.6.2.stable"
$DefaultGodotExe = "E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ProjectDir = Join-Path $RepoRoot "godot-android"
$ExportPath = Join-Path $ProjectDir "builds\SmartXR-Godot-Control.apk"
$GxrExtensionSwitch = Join-Path $PSScriptRoot "set_gxr_extension.ps1"
$PackageName = "com.smartxr.godotcontrol"
$GradleUserHome = Join-Path $RepoRoot ".gradle-user-home"

function Resolve-ConfiguredPath {
    param(
        [string]$Value,
        [string]$Fallback
    )

    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return Expand-ConfiguredEnvPath -Value $Value
    }
    return Expand-ConfiguredEnvPath -Value $Fallback
}

function Expand-ConfiguredEnvPath {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Value
    }
    $Expanded = [Environment]::ExpandEnvironmentVariables($Value)
    $Match = [regex]::Match($Expanded, '^\$env:([A-Za-z_][A-Za-z0-9_]*)(.*)$')
    if ($Match.Success) {
        $EnvName = $Match.Groups[1].Value
        $Remainder = $Match.Groups[2].Value.TrimStart("\", "/")
        $EnvValue = [Environment]::GetEnvironmentVariable($EnvName)
        if ([string]::IsNullOrWhiteSpace($EnvValue)) {
            throw "Environment variable referenced by path is not set: $EnvName"
        }
        if ([string]::IsNullOrWhiteSpace($Remainder)) {
            return $EnvValue
        }
        return Join-Path $EnvValue $Remainder
    }
    return $Expanded
}

function Assert-File {
    param(
        [string]$Path,
        [string]$Message
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Message`: $Path"
    }
}

function Assert-Directory {
    param(
        [string]$Path,
        [string]$Message
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Message`: $Path"
    }
}

function Resolve-AndroidSdk {
    param([string]$ConfiguredSdk)

    if (-not [string]::IsNullOrWhiteSpace($ConfiguredSdk)) {
        return Expand-ConfiguredEnvPath -Value $ConfiguredSdk
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ANDROID_SDK_ROOT)) {
        return Expand-ConfiguredEnvPath -Value $env:ANDROID_SDK_ROOT
    }
    throw "Set ANDROID_HOME or ANDROID_SDK_ROOT to the Android SDK root."
}

function Find-LatestAndroidTool {
    param(
        [string]$SdkRoot,
        [string]$RelativeRoot,
        [string]$ToolName
    )

    $ToolRoot = Join-Path $SdkRoot $RelativeRoot
    Assert-Directory $ToolRoot "Android SDK tool directory not found"
    $Matches = Get-ChildItem -LiteralPath $ToolRoot -Recurse -Filter $ToolName -File |
        Sort-Object FullName -Descending
    if (-not $Matches) {
        throw "Android SDK tool not found under $ToolRoot`: $ToolName"
    }
    return $Matches[0].FullName
}

function Assert-Jdk17 {
    param([string]$ConfiguredJavaHome)

    Assert-Directory $ConfiguredJavaHome "JAVA_HOME must point to a JDK 17 install"
    $JavaExe = Join-Path $ConfiguredJavaHome "bin\java.exe"
    Assert-File $JavaExe "java.exe not found under JAVA_HOME"
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $VersionOutput = & $JavaExe -version 2>&1 | Out-String
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($VersionOutput -notmatch 'version "17\.') {
        throw "JAVA_HOME must be JDK 17. Actual java -version output: $VersionOutput"
    }
}

function Ensure-GodotTemplateAar {
    param(
        [string]$TemplateZip,
        [string]$EntryFileName,
        [string]$Destination
    )

    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        return
    }
    Assert-File $TemplateZip "Godot $GodotVersion Android export template android_source.zip not found"

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip = [System.IO.Compression.ZipFile]::OpenRead($TemplateZip)
    try {
        $Entry = $Zip.Entries |
            Where-Object { $_.FullName -like "*$EntryFileName" } |
            Select-Object -First 1
        if ($null -eq $Entry) {
            throw "$EntryFileName not found inside $TemplateZip"
        }
        $DestinationDir = Split-Path -Parent $Destination
        New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $Destination, $true)
    } finally {
        $Zip.Dispose()
    }
}

function Ensure-GodotAars {
    param([string]$ProjectDir)

    $TemplateZip = Join-Path $env:APPDATA "Godot\export_templates\$GodotTemplateVersion\android_source.zip"
    Ensure-GodotTemplateAar `
        -TemplateZip $TemplateZip `
        -EntryFileName "godot-lib.template_debug.aar" `
        -Destination (Join-Path $ProjectDir "android\build\libs\debug\godot-lib.template_debug.aar")
    Ensure-GodotTemplateAar `
        -TemplateZip $TemplateZip `
        -EntryFileName "godot-lib.template_release.aar" `
        -Destination (Join-Path $ProjectDir "android\build\libs\release\godot-lib.template_release.aar")
    Ensure-GodotTemplateAar `
        -TemplateZip $TemplateZip `
        -EntryFileName "res/values/themes.xml" `
        -Destination (Join-Path $ProjectDir "android\build\res\values\themes.xml")
}

function Ensure-AdaptiveIconBackground {
    param([string]$ProjectDir)

    $IconXml = Join-Path $ProjectDir "android\build\res\mipmap-anydpi-v26\icon.xml"
    $ColorsXml = Join-Path $ProjectDir "android\build\res\values\colors.xml"
    $ThemesXml = Join-Path $ProjectDir "android\build\res\values\themes.xml"
    Assert-File $IconXml "Android adaptive icon resource not found"
    Assert-File $ColorsXml "Android colors resource not found"

    foreach ($ResourceXml in @($IconXml, $ThemesXml)) {
        if (-not (Test-Path -LiteralPath $ResourceXml -PathType Leaf)) {
            continue
        }
        $Source = Get-Content -LiteralPath $ResourceXml -Raw
        if ($Source -match "@mipmap/icon_background") {
            $Source = $Source -replace "@mipmap/icon_background", "@color/icon_background"
            [System.IO.File]::WriteAllText($ResourceXml, $Source, [System.Text.UTF8Encoding]::new($false))
        }
    }
    $IconSource = Get-Content -LiteralPath $IconXml -Raw
    if ($IconSource -notmatch "@color/icon_background") {
        throw "Adaptive icon background must use existing @color/icon_background."
    }
}

function Ensure-DebugKeystore {
    param([string]$JavaHome)

    $Keytool = Join-Path $JavaHome "bin\keytool.exe"
    Assert-File $Keytool "keytool.exe not found under JAVA_HOME"
    $Keystore = Join-Path $env:USERPROFILE ".android\debug.keystore"
    if (Test-Path -LiteralPath $Keystore -PathType Leaf) {
        return $Keystore
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Keystore) | Out-Null
    & $Keytool -genkeypair -v `
        -keystore $Keystore `
        -storepass android `
        -alias androiddebugkey `
        -keypass android `
        -keyalg RSA `
        -keysize 2048 `
        -validity 10000 `
        -dname "CN=Android Debug,O=Android,C=US"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create Android debug keystore at $Keystore"
    }
    return $Keystore
}

function Sign-And-VerifyDebugApk {
    param(
        [string]$ApkPath,
        [string]$ApkSigner,
        [string]$DebugKeystore
    )

    Assert-File $ApkPath "APK export did not produce the expected file"
    & $ApkSigner sign `
        --ks $DebugKeystore `
        --ks-key-alias androiddebugkey `
        --ks-pass pass:android `
        --key-pass pass:android `
        $ApkPath
    if ($LASTEXITCODE -ne 0) {
        throw "apksigner failed to sign debug APK: $ApkPath"
    }
    & $ApkSigner verify --verbose $ApkPath
    if ($LASTEXITCODE -ne 0) {
        throw "apksigner verify --verbose failed: $ApkPath"
    }
}

function Verify-ApkSignature {
    param(
        [string]$ApkPath,
        [string]$ApkSigner
    )

    Assert-File $ApkPath "APK export did not produce the expected file"
    & $ApkSigner verify --verbose $ApkPath
    if ($LASTEXITCODE -ne 0) {
        throw "apksigner verify --verbose failed: $ApkPath"
    }
}

function Invoke-AdbInstall {
    param(
        [string]$Adb,
        [array]$AdbArgs,
        [string]$ApkPath,
        [string]$PackageName
    )

    $ExistingPackage = & $Adb @AdbArgs shell pm list packages $PackageName
    if ($ExistingPackage -match [regex]::Escape($PackageName)) {
        # Concrete recovery equivalent: adb uninstall com.smartxr.godotcontrol
        & $Adb @AdbArgs uninstall $PackageName
    }

    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # Concrete smoke equivalent: adb install -r godot-android\builds\SmartXR-Godot-Control.apk
        $InstallOutput = & $Adb @AdbArgs install --no-incremental -r $ApkPath 2>&1 | Out-String
        $InstallExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    Write-Host $InstallOutput
    if ($InstallExitCode -eq 0) {
        return
    }

    if ($InstallOutput -match "INSTALL_FAILED_UPDATE_INCOMPATIBLE") {
        # Concrete recovery equivalent: adb uninstall com.smartxr.godotcontrol
        & $Adb @AdbArgs uninstall $PackageName
        if ($LASTEXITCODE -ne 0) {
            throw "adb uninstall failed for stale package $PackageName"
        }
        & $Adb @AdbArgs install --no-incremental -r $ApkPath
        if ($LASTEXITCODE -eq 0) {
            return
        }
    }

    throw "adb install -r failed for $ApkPath"
}

function Invoke-DeviceSmokeTest {
    param(
        [string]$Adb,
        [string]$ApkPath,
        [string]$PackageName,
        [string]$DeviceSerial
    )

    $AdbArgs = @()
    if (-not [string]::IsNullOrWhiteSpace($DeviceSerial)) {
        $AdbArgs += @("-s", $DeviceSerial)
    }

    Invoke-AdbInstall -Adb $Adb -AdbArgs $AdbArgs -ApkPath $ApkPath -PackageName $PackageName
    & $Adb @AdbArgs reverse tcp:8766 tcp:8766
    if ($LASTEXITCODE -ne 0) {
        throw "adb reverse tcp:8766 tcp:8766 failed"
    }
    & $Adb @AdbArgs reverse tcp:8767 tcp:8767
    if ($LASTEXITCODE -ne 0) {
        throw "adb reverse tcp:8767 tcp:8767 failed"
    }
    # Concrete smoke equivalent: adb shell pm list packages com.smartxr.godotcontrol
    & $Adb @AdbArgs shell pm list packages $PackageName
    if ($LASTEXITCODE -ne 0) {
        throw "adb shell pm list packages $PackageName failed"
    }
    & $Adb @AdbArgs shell am force-stop $PackageName
    & $Adb @AdbArgs shell monkey -p $PackageName 1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to launch $PackageName with adb monkey"
    }
    & $Adb @AdbArgs logcat -d -t 200
}

$GodotExe = Resolve-ConfiguredPath -Value $GodotExe -Fallback $DefaultGodotExe
$AndroidSdk = Resolve-AndroidSdk -ConfiguredSdk $AndroidSdk
$JavaHome = Expand-ConfiguredEnvPath -Value $JavaHome

Assert-File $GodotExe "Godot executable not found. Set SMARTXR_GODOT_EXE or pass -GodotExe"
Assert-File (Join-Path $ProjectDir "project.godot") "Godot project not found"
Assert-File $GxrExtensionSwitch "GXR extension switch script not found"
Assert-Jdk17 -ConfiguredJavaHome $JavaHome
Assert-Directory $AndroidSdk "Android SDK root not found"
Assert-File (Join-Path $ProjectDir "android\build\gradlew.bat") "Godot custom Android Gradle wrapper not found"
Ensure-GodotAars -ProjectDir $ProjectDir
Ensure-AdaptiveIconBackground -ProjectDir $ProjectDir
New-Item -ItemType Directory -Force -Path $GradleUserHome | Out-Null
$env:GRADLE_USER_HOME = $GradleUserHome

$ApkSigner = Find-LatestAndroidTool -SdkRoot $AndroidSdk -RelativeRoot "build-tools" -ToolName "apksigner.bat"
$Adb = Find-LatestAndroidTool -SdkRoot $AndroidSdk -RelativeRoot "platform-tools" -ToolName "adb.exe"
$DebugKeystore = Ensure-DebugKeystore -JavaHome $JavaHome

if ($PreflightOnly) {
    Write-Host "Android export preflight passed for Godot $GodotVersion."
    exit 0
}

& $GxrExtensionSwitch -Mode enable -ProjectDir $ProjectDir

$BuildDir = Split-Path -Parent $ExportPath
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

if ($Release) {
    & $GodotExe --headless --path $ProjectDir --export-release "Android" $ExportPath
} else {
    & $GodotExe --headless --path $ProjectDir --export-debug "Android" $ExportPath
}
if ($LASTEXITCODE -ne 0) {
    throw "Godot Android export failed with exit code $LASTEXITCODE"
}
Ensure-AdaptiveIconBackground -ProjectDir $ProjectDir

if ($Release) {
    Verify-ApkSignature -ApkPath $ExportPath -ApkSigner $ApkSigner
} else {
    Sign-And-VerifyDebugApk -ApkPath $ExportPath -ApkSigner $ApkSigner -DebugKeystore $DebugKeystore
}

if ($SmokeTest) {
    Invoke-DeviceSmokeTest `
        -Adb $Adb `
        -ApkPath $ExportPath `
        -PackageName $PackageName `
        -DeviceSerial $DeviceSerial
}

Write-Host "Android APK ready: $ExportPath"
