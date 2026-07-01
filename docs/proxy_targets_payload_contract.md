# proxy_targets payload contract

## VST / external publisher boundary

Godot consumes only canonical `proxy_targets` messages. A real VST or external source should replace the publisher and emit this message shape; it should not require changes in `ProxyTargetsConsumer.gd` or `ProxyTargetsCardAdapter.gd`.

Required top-level fields:

- `type`: `proxy_targets`
- `schema_version`: `1`
- `sequence`: integer publisher sequence
- `targets`: non-empty target array
- `cards`: non-empty card binding array

Required target fields:

- `target_id`: stable string ID
- `source`: for example `vst`, `external`, or `fake_vst`
- `state`: `tracked`, `predicted`, `stale`, or `lost`
- `confidence`: number from `0.0` to `1.0`
- `timestamp_ms`: source timestamp in milliseconds
- `transform.position`: `[x, y, z]` in Godot/XR reference-space meters
- `transform.rotation_xyzw`: quaternion `[x, y, z, w]`
- `transform.scale`: `[x, y, z]`

Optional target diagnostics:

- `target_size_m`: publisher-derived physical target size in meters, for example `{ "width": 0.72, "height": 1.80 }`. This is derived geometry, not raw bbox data.
- `source_coordinate`: compact publisher-side calibration metadata for real-device alignment checks. For VST bbox sources this records `coordinate_space`, `publisher_convention`, `camera_axes`, `head_axes`, `anchor`, `depth_source`, `uses_right_eye_to_head`, `source_frame`, `camera_point_m`, `head_position_m`, and optionally the same `target_size_m`. The `source_frame.anchor_depth` field is diagnostic depth in meters; it intentionally avoids raw field names that the canonical schema rejects.

Required card fields:

- `card_id`: card wrapper ID, such as `CardAnchor`
- `target_id`: ID of a target in the same message
- `offset_rule`: optional object; if omitted, adapter defaults apply

Default card placement:

- `mode=depth_scaled_right_half_width`
- `depth_scale=1.3`: card position is placed 30% farther than the target in the horizontal viewer-to-target depth plane.
- `depth_offset_m=0.0`: after scaling, this adds meters along the horizontal viewer-to-target depth ray; positive moves farther, negative moves closer.
- `right_width_fraction=0.5`: card is shifted right by half of `target_size_m.width` along the viewer's horizontal right axis.

Angle-based placement is available with `mode=depth_scaled_right_angle`.
It keeps the same `depth_scale` and `depth_offset_m`, then computes horizontal
right offset as `tan(right_angle_deg) * final_depth`. This is useful when the
card should occupy a stable visual angle beside the person instead of following
the estimated bbox width.

In `dynamic` comparison mode, fresh targets update the Godot world transform;
stale/held packets reuse the previous world transform, viewer reference
transform, and target size so an old head-space sample is not reprojected with
the current headset pose. In `world_latched` mode, Godot latches the first
fresh target's world transform and keeps using it until target loss or manual
reset.

Godot consumer/adapter must not read bbox or detection fields. Raw VST/external fields such as `bbox`, `boxes`, `detection`, `detections`, `image`, or `depth_m` belong on the publisher side and must be converted before reaching `proxy_targets`.

VST bbox publisher convention:

- Raw VST camera axes are treated as `+X right`, `+Y down`, `+Z forward`.
- The publisher projects bbox center through the configured camera FOV, defaulting to `70.0` horizontal and `43.0` vertical degrees.
- The default conversion to Godot/head convention is `[x, -y, -z]`, so forward targets have negative Godot Z.
- If a 4x4 `right_eye_to_head_matrix` is supplied under the source camera metadata, the publisher applies it instead of the default axis flip.
- The anchor point is the target center at the source-provided depth or the configured default depth.

## Shared math test vectors

The bbox→head conventions above are pinned by one checked-in fixture,
`godot-android/fixtures/bbox_math_test_vectors.json` (`schema_version: 1`),
with named cases for the FOV pinhole projection, the `[x, -y, -z]` default
flip, the row-major 4x4 `right_eye_to_head` path (plus the GDScript-only
fewer-than-16-elements fallback to the default flip), and the full
bbox→yaw/pitch/depth/angular-size→position chain. Two consumers run the same
numbers:

- Python: `tests/test_bbox_math_vectors.py` drives `smartxr.geometry`
  (`project_bbox_center_to_camera_point` / `vst_camera_point_to_head`);
  tolerance `1e-9`.
- GDScript: `tools/run_godot_bbox_math_probe.ps1` runs
  `godot-android/tests/script_only_bbox_math_probe.gd` headless against the
  duplicated math in `AndroidMovingCard.gd` (`_anchor_from_bbox`,
  `_convert_vst_camera_point_to_head_convention`,
  `_transform_right_vst_point_to_head`,
  `_target_position_from_bbox_anchor`); tolerance `1e-4` (Vector3 is
  float32).

Regenerate or extend with `tools/generate_bbox_math_test_vectors.py`. The
yaw/pitch/angular decomposition exists only on the GDScript side; it lives in
the same fixture so target-source refactors (M4) cannot drift it silently.

Current gate:

```powershell
python tools\validate_proxy_targets_payload_schema.py --input godot-android\fixtures\proxy_targets_sample.json --input godot-android\fixtures\vst_proxy_targets_sample.json
```

If a real source can emit this canonical payload, the integration should only need to replace the publisher.
