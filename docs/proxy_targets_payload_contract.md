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

- `source_coordinate`: compact publisher-side calibration metadata for real-device alignment checks. For VST bbox sources this records `coordinate_space`, `publisher_convention`, `camera_axes`, `head_axes`, `anchor`, `depth_source`, `uses_right_eye_to_head`, `source_frame`, `camera_point_m`, and `head_position_m`. The `source_frame.anchor_depth` field is diagnostic depth in meters; it intentionally avoids raw field names that the canonical schema rejects.

Required card fields:

- `card_id`: card wrapper ID, such as `CardAnchor`
- `target_id`: ID of a target in the same message
- `offset_rule`: optional object; if omitted, adapter defaults apply

Godot consumer/adapter must not read bbox or detection fields. Raw VST/external fields such as `bbox`, `boxes`, `detection`, `detections`, `image`, or `depth_m` belong on the publisher side and must be converted before reaching `proxy_targets`.

VST bbox publisher convention:

- Raw VST camera axes are treated as `+X right`, `+Y down`, `+Z forward`.
- The publisher projects bbox center through the configured camera FOV, defaulting to `70.0` horizontal and `43.0` vertical degrees.
- The default conversion to Godot/head convention is `[x, -y, -z]`, so forward targets have negative Godot Z.
- If a 4x4 `right_eye_to_head_matrix` is supplied under the source camera metadata, the publisher applies it instead of the default axis flip.
- The anchor point is the target center at the source-provided depth or the configured default depth.

Current gate:

```powershell
python tools\validate_proxy_targets_payload_schema.py --input godot-android\fixtures\proxy_targets_sample.json --input godot-android\fixtures\vst_proxy_targets_sample.json
```

If a real source can emit this canonical payload, the integration should only need to replace the publisher.
