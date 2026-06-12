from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "godot-android" / "scripts" / "xr_bootstrap.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_xr_bootstrap_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_xr_bootstrap_probe.ps1"


class GodotXRBootstrapTests(unittest.TestCase):
    def test_xr_bootstrap_owns_init_path_and_camera_setup(self):
        source = BOOTSTRAP.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name XRBootstrap", source)
        # No self-reference to the class_name: the script must stay loadable
        # in no-project (script-only) mode, like the other extracted
        # subsystem scripts.
        self.assertNotIn("XRBootstrap.new()", source)
        self.assertNotIn(": XRBootstrap", source)
        # The XR startup path moved here from the card, byte-for-byte: the
        # exact error strings, the "XR init:" prints, the viewport flips, the
        # blend-request has_method branch, and the vsync disable.
        self.assertIn("func try_init_xr(viewport: Viewport) -> void:", source)
        self.assertIn('_init_error = "OpenXR interface not found"', source)
        self.assertIn('_init_error = "OpenXR initialize returned false"', source)
        self.assertIn('print("XR init: " + _init_error)', source)
        self.assertIn("viewport.use_xr = true", source)
        self.assertIn("viewport.transparent_bg = true", source)
        self.assertIn('_requested_blend_mode = "alpha_blend"', source)
        self.assertIn('if xr.has_method("set_environment_blend_mode"):', source)
        self.assertIn(
            '_blend_request_ok = bool(xr.call("set_environment_blend_mode", XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND))',
            source,
        )
        self.assertIn("xr.environment_blend_mode = XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND", source)
        self.assertIn("DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)", source)
        self.assertIn(
            'print("XR init: active use_xr=%s transparent=%s blend=alpha" % [str(viewport.use_xr), str(viewport.transparent_bg)])',
            source,
        )
        # The camera/origin construction moved here from the card.
        self.assertIn("func setup_camera(parent: Node3D) -> void:", source)
        self.assertIn("XROrigin3D.new()", source)
        self.assertIn('origin.name = "XROrigin"', source)
        self.assertIn("XRCamera3D.new()", source)
        self.assertIn('camera.name = "XRCamera"', source)
        self.assertIn('camera.name = "FallbackCamera"', source)
        self.assertIn("camera.far = 50.0", source)
        self.assertIn("camera.look_at(_fallback_look_at_target(), Vector3.UP)", source)
        self.assertIn("camera.make_current()", source)
        # Injection seams for probeability: the interface provider replaces
        # the default XRServer lookup, the look_at target routes back into the
        # card's 3DoF anchor math (ADR-4), and the interface is duck-typed.
        self.assertIn("func set_interface_provider(provider: Callable) -> void:", source)
        self.assertIn("func set_fallback_look_at_provider(provider: Callable) -> void:", source)
        self.assertIn('XRServer.find_interface("OpenXR")', source)
        self.assertIn("var xr = _find_interface()", source)
        self.assertNotIn("var xr := ", source)
        # Read-only getters feeding the card's state copies.
        self.assertIn("func interface_found() -> bool:", source)
        self.assertIn("func initialize_ok() -> bool:", source)
        self.assertIn("func xr_active() -> bool:", source)
        self.assertIn("func init_error() -> String:", source)
        self.assertIn("func requested_blend_mode() -> String:", source)
        self.assertIn("func blend_request_ok() -> bool:", source)
        self.assertIn("func xr_origin() -> XROrigin3D:", source)
        self.assertIn("func camera() -> Camera3D:", source)
        # Defaults mirror the card's pre-init state.
        self.assertIn('var _init_error := "not attempted"', source)
        self.assertIn('var _requested_blend_mode := "alpha_blend"', source)
        # The subsystem is dependency-free: no preloads, no env reads, no
        # tree walks of its own.
        self.assertNotIn("preload(", source)
        self.assertNotIn("OS.get_environment", source)
        self.assertNotIn("get_tree()", source)

    def test_moving_card_delegates_to_extracted_xr_bootstrap(self):
        card = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const XRBootstrapScript := preload("res://scripts/xr_bootstrap.gd")', card)
        self.assertIn("var _xr_bootstrap = XRBootstrapScript.new()", card)
        # Wiring: the fallback camera's look_at target stays card-side
        # (ADR-4); the interface lookup keeps the subsystem default.
        self.assertIn("func _setup_xr_bootstrap() -> void:", card)
        self.assertIn("_xr_bootstrap.set_fallback_look_at_provider(_anchor_position_from_yaw_pitch_depth)", card)
        self.assertIn("_setup_xr_bootstrap()", card)
        # Delegation: the card calls the subsystem and copies the resolved
        # state back so every status-snapshot key keeps identical values.
        self.assertIn("_xr_bootstrap.try_init_xr(get_viewport())", card)
        self.assertIn("_xr_interface_found = _xr_bootstrap.interface_found()", card)
        self.assertIn("_xr_initialize_ok = _xr_bootstrap.initialize_ok()", card)
        self.assertIn("_xr_active = _xr_bootstrap.xr_active()", card)
        self.assertIn("_xr_init_error = _xr_bootstrap.init_error()", card)
        self.assertIn(
            "_passthrough_overlay_requested_blend_mode = _xr_bootstrap.requested_blend_mode()", card
        )
        self.assertIn("_passthrough_overlay_blend_ok = _xr_bootstrap.blend_request_ok()", card)
        self.assertIn("_xr_bootstrap.setup_camera(self)", card)
        self.assertIn("_xr_origin = _xr_bootstrap.xr_origin()", card)
        self.assertIn("_camera = _xr_bootstrap.camera()", card)
        # The init order in _ready is unchanged: wire, init XR, then cameras.
        self.assertLess(card.index("_setup_xr_bootstrap()"), card.index("_try_init_xr()"))
        self.assertLess(card.index("_try_init_xr()"), card.index("_setup_camera()"))
        # The moved bodies are gone from the card; the resolved state vars
        # stay (ADR-4).
        self.assertIn("var _xr_active := false", card)
        self.assertIn("var _xr_origin: XROrigin3D = null", card)
        self.assertNotIn('XRServer.find_interface("OpenXR")', card)
        self.assertNotIn("XROrigin3D.new()", card)
        self.assertNotIn("XRCamera3D.new()", card)
        self.assertNotIn('"FallbackCamera"', card)
        self.assertNotIn("make_current", card)
        self.assertNotIn("DisplayServer.VSYNC_DISABLED", card)
        self.assertNotIn('"OpenXR interface not found"', card)
        self.assertNotIn('"OpenXR initialize returned false"', card)
        self.assertNotIn("XR_ENV_BLEND_MODE_ALPHA_BLEND", card)

    def test_runtime_probe_and_runner_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        # No-project mode: the script under test is injected via env vars, and
        # quit() must happen in _process, not _initialize.
        self.assertIn('OS.get_environment("SMARTXR_XR_BOOTSTRAP_SCRIPT")', probe)
        self.assertIn("SMARTXR_XR_BOOTSTRAP_PROBE_STATUS_PATH", probe)
        self.assertIn("func _process(_delta: float) -> bool:", probe)
        # The contract surface the issue asks for: the not-found and
        # initialize-false fallbacks with exact error strings, the fallback
        # camera construction, the XR-active origin+camera construction with
        # a fake interface, and the blend-request bookkeeping branches.
        self.assertIn("not_found_error_string", probe)
        self.assertIn("init_false_error_string", probe)
        self.assertIn("fallback_camera_name_far", probe)
        self.assertIn("fallback_camera_looks_at_target", probe)
        self.assertIn("fallback_camera_default_look_at_forward", probe)
        self.assertIn("active_flips_viewport", probe)
        self.assertIn("active_blend_mode_argument", probe)
        self.assertIn("active_origin_constructed", probe)
        self.assertIn("active_camera_constructed", probe)
        self.assertIn("blend_false_bookkeeping", probe)
        self.assertIn("property_branch_sets_mode", probe)
        self.assertIn("class FakeXRInterface:", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_XR_BOOTSTRAP_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
