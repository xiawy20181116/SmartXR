# XRBootstrap subsystem (Godot)

`godot-android/scripts/xr_bootstrap.gd` (`XRBootstrap`) owns OpenXR startup and
camera/origin construction for the card scene.

The card calls the bootstrap, then copies the results into its existing
status fields. This keeps XR initialization isolated without changing the
status snapshot contract.

## Boundary

XRBootstrap owns:

- Looking up the OpenXR interface.
- Initializing OpenXR when available.
- Configuring the viewport for XR and transparent background.
- Requesting alpha-blend environment mode when the interface supports it.
- Disabling vsync for XR runtime use.
- Creating `XROrigin3D` + `XRCamera3D` for active XR.
- Creating `FallbackCamera` for non-XR desktop/script runs.

`AndroidMovingCard.gd` still owns:

- Copying bootstrap results into `_xr_*`, `_camera`, and passthrough-overlay
  fields.
- The fallback look-at target math.
- Status snapshot assembly.
- Any higher-level decision about whether the scene should continue running.

## Public surface

| API | Caller | Meaning |
|---|---|---|
| `set_interface_provider(callable)` | Tests / probes | Injects an OpenXR interface provider. |
| `set_fallback_look_at_provider(callable)` | Card setup / probes | Supplies the desktop fallback camera look-at target. |
| `try_init_xr(viewport)` | Card `_ready` path | Attempts OpenXR lookup, initialization, viewport setup, blend request, and vsync change. |
| `setup_camera(parent)` | Card `_ready` path | Creates XR origin/camera when active, or a fallback camera otherwise. |
| `interface_found()` | Card result copy | True when an OpenXR interface was found. |
| `initialize_ok()` | Card result copy | True when interface initialization succeeded. |
| `xr_active()` | Card result copy | True when the XR runtime path is active. |
| `init_error()` | Card result copy | Error string for status output. |
| `requested_blend_mode()` | Card result copy | Requested environment blend mode. |
| `blend_request_ok()` | Card result copy | True when the alpha-blend request succeeded or was accepted. |
| `xr_origin()` | Card result copy | Created `XROrigin3D`, or null outside active XR. |
| `camera()` | Card result copy | Created `Camera3D`. |

## Runtime behavior

`try_init_xr(viewport)` first obtains an interface. By default it asks
`XRServer.find_interface("OpenXR")`; probes can inject a fake provider. If the
interface is missing or initialization fails, XR remains inactive and
`setup_camera(parent)` creates a desktop fallback camera.

When initialization succeeds, the bootstrap enables XR on the viewport,
requests transparent background, requests alpha blend when supported, disables
vsync, and records all results for the card to copy into its status fields.

`setup_camera(parent)` then creates either:

| Runtime state | Nodes |
|---|---|
| XR active | `XROrigin3D` with child `XRCamera3D`. |
| XR inactive | `FallbackCamera` looking at the injected fallback target. |

## Runtime verification

```powershell
powershell -File tools\run_godot_xr_bootstrap_probe.ps1
```

The probe runs `godot-android/tests/script_only_xr_bootstrap_probe.gd` in
no-project mode. It verifies missing-interface behavior, initialize-false
behavior, fallback camera construction, XR origin/camera construction, result
getters, and the supported blend-request branches.

Python coverage:

```powershell
python -m unittest tests.test_godot_xr_bootstrap
```

## Extending XRBootstrap

1. Keep XR interface calls duck-typed so probes can inject fakes.
2. Keep card-specific anchor math outside this script; use the fallback
   look-at provider.
3. Copy new bootstrap results back into the card explicitly so the status
   snapshot remains easy to audit.
4. Keep probe-visible code free of self-references to `XRBootstrap` return
   types, because no-project mode does not register global classes.
