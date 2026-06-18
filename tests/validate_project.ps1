$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $RepoRoot
try {
    python -m unittest `
        tests/test_bbox_math_vectors.py `
        tests/test_box_builder_2_5d.py `
        tests/test_live_stereo_recorder.py `
        tests/test_nv12_reader.py `
        tests/test_stereo_depth.py `
        tests/test_stereo_package.py `
        tests/test_tracker.py `
        tests/test_tracking_raw_producer.py `
        tests/test_tracking_raw_live_chain.py `
        tests/test_mr_integration.py `
        tests/test_mr_integration_bridge.py `
        tests/test_godot_android_mesh_card.py `
        tests/test_godot_card_attachment.py `
        tests/test_godot_smartxr_options.py `
        tests/test_godot_status_hud.py `
        tests/test_godot_target_source.py `
        tests/test_godot_target_registry.py `
        tests/test_godot_ws_transport.py `
        tests/test_godot_xr_bootstrap.py `
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
