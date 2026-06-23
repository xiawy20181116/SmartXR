# Android APK Export and Smoke Test

This is the repeatable local path for the SmartXR Godot Android package
`com.smartxr.godotcontrol`.

## Prerequisites

- Godot 4.6.2 executable. Set `SMARTXR_GODOT_EXE` when it is not at
  `E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe`.
- Godot 4.6.2 Android export templates installed at
  `%APPDATA%\Godot\export_templates\4.6.2.stable\android_source.zip`.
- JDK 17 with `JAVA_HOME` pointing at the JDK root.
- Android SDK with `ANDROID_HOME` or `ANDROID_SDK_ROOT` pointing at the SDK root.
- `build-tools` containing `apksigner.bat` and `platform-tools` containing
  `adb.exe`.

## Export

Run the preflight first:

```powershell
powershell -ExecutionPolicy Bypass -File tools\export_android.ps1 -PreflightOnly
```

Then export the debug APK:

```powershell
powershell -ExecutionPolicy Bypass -File tools\export_android.ps1
```

The script enables the GXR extension, restores the Godot custom-build AARs from
`android_source.zip` when missing (`godot-lib.template_debug.aar` and
`godot-lib.template_release.aar`), keeps the adaptive icon background pointed at
`@color/icon_background`, signs debug builds with the local Android debug
keystore, and runs:

```powershell
apksigner verify --verbose godot-android\builds\SmartXR-Godot-Control.apk
```

Expected APK:

```text
godot-android\builds\SmartXR-Godot-Control.apk
```

## Device Smoke Test

With the target headset connected, run:

```powershell
powershell -ExecutionPolicy Bypass -File tools\export_android.ps1 -SmokeTest
```

For a specific device:

```powershell
powershell -ExecutionPolicy Bypass -File tools\export_android.ps1 -SmokeTest -DeviceSerial 3B1F5UE8WTX7PY0H
```

The smoke path performs the same export and signature verification, then runs:

```powershell
adb install -r godot-android\builds\SmartXR-Godot-Control.apk
adb reverse tcp:8766 tcp:8766
adb reverse tcp:8767 tcp:8767
adb shell pm list packages com.smartxr.godotcontrol
```

It also force-stops and launches `com.smartxr.godotcontrol`, then prints the last
200 logcat lines for the run. If a mock host is available, start the proxy target
or control publisher on the PC before running `-SmokeTest` so the reversed
`8766` and `8767` ports exercise the live path.
