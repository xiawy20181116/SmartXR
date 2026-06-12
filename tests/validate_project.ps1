$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $RepoRoot
try {
    python -m unittest `
        tests/test_godot_android_mesh_card.py `
        tests/test_godot_card_attachment.py `
        tests/test_godot_smartxr_options.py `
        tests/test_godot_status_hud.py `
        tests/test_godot_target_registry.py `
        tests/test_godot_ws_transport.py `
        tests/test_run_windows_pcmr.py `
        tests/test_vst_ncnn_port.py `
        tests/test_ws_control.py
    $UnitTestExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($UnitTestExitCode -ne 0) {
    exit $UnitTestExitCode
}
