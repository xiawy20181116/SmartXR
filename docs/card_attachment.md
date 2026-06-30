# CardAttachment subsystem (Godot)

`godot-android/scripts/card_attachment.gd` (`CardAttachment`) owns the
card-id to target-id attachment store, per-frame application of target poses,
fallback behavior, and offset-rule math.

The card still owns scene nodes and user-facing behavior. CardAttachment is a
pure coordinator around target resolution and transform math.

## Boundary

CardAttachment owns:

- Attachment records keyed by card id.
- `attach` / `detach` state changes.
- Per-frame target resolution and card-anchor placement.
- Fallback modes when a target cannot be resolved.
- Offset-rule normalization and transform math.
- Last resolved position per attachment.

`AndroidMovingCard.gd` still owns:

- Public methods such as `attach_to_target` and `detach_card`.
- The visible card anchor node.
- Anchor-mode changes and orientation updates.
- Target registry wiring.
- Apply counters and status snapshot fields.

## Public surface

| API | Caller | Meaning |
|---|---|---|
| `set_resolver(callable)` | Card setup | Supplies target lookup, usually `_target_registry.resolve`. |
| `set_reference_transform_provider(callable)` | Card setup | Supplies the viewer/camera transform for depth-scaled placement modes. Latched proxy targets can override this with their stored latch reference. |
| `set_on_applied(callable)` | Card setup | Notifies the card after a target transform is applied. |
| `set_on_detach_card(callable)` | Card setup | Routes detach fallback back through card-side behavior. |
| `attach(card_id, target_id, offset_rule)` | Card public API wrapper | Stores or replaces an attachment. |
| `detach(card_id)` | Card public API wrapper | Removes an attachment. |
| `update_attachments(card_anchor, primary_card_id)` | Card `_process` path | Resolves targets and applies the selected attachment to the card anchor. |
| `apply_fallback(attachment, card_anchor, primary_card_id)` | Internal/probes | Applies the configured fallback behavior. |
| `size()` / `is_empty()` / `has_attachment()` | Card and probes | Inspection helpers. |
| `get_attachment(card_id)` | Card and probes | Returns the attachment Dictionary or null. |
| `attached_target_id(card_id)` | Status snapshot | Returns the target id for a card id. |
| `last_resolved_position(card_id)` | Status snapshot | Returns the last resolved target position or null. |

Static helpers:

| API | Meaning |
|---|---|
| `normalize_offset_rule(offset_rule)` | Merges caller input with `DEFAULT_OFFSET_RULE`. |
| `offset_transform(target_transform, offset_rule)` | Dispatches world vs target-space offset math. |
| `offset_transform_with_context(target_transform, offset_rule, reference_transform, target_size_m)` | Applies offset math that needs viewer pose or target dimensions. |
| `depth_scaled_right_half_width_transform(...)` | Places the card farther than the target and shifts it along viewer-right by target width fraction. |
| `depth_scaled_right_angle_transform(...)` | Places the card farther than the target and shifts it along viewer-right by a configured visual angle. |
| `world_offset_transform(target_transform, offset_rule)` | Applies the offset in world space. |
| `local_offset_transform(target_transform, offset_rule)` | Applies the offset in target local space. |
| `offset_vector(offset_rule)` | Computes the requested offset vector. |

## Offset rules

`DEFAULT_OFFSET_RULE` keeps the historical behavior for target attachments.

| Key | Values | Meaning |
|---|---|---|
| `mode` | `depth_scaled_right_half_width`, `depth_scaled_right_angle`, `right_top`, `top_right`, `right`, `top`, `front`, `custom` | Direction to place the card relative to the target. |
| `offset_space` | `world`, `target` | Whether the vector is applied in world axes or target local axes. |
| `distance_m` | Number | Distance for named modes. |
| `depth_scale` | Number | For `depth_scaled_right_half_width`, multiplies horizontal viewer-to-target depth; `1.3` puts the card 30% behind the target. |
| `depth_offset_m` | Number | For `depth_scaled_right_half_width`, adds meters after scaling depth; positive moves farther along the horizontal viewer-to-target ray, negative moves closer. |
| `right_width_fraction` | Number | For `depth_scaled_right_half_width`, multiplies target physical width; `0.5` shifts right by half the target width along the viewer's horizontal right axis. |
| `right_angle_deg` | Number | For `depth_scaled_right_angle`, shifts right by `tan(angle) * final_depth`; positive is viewer-right, negative is viewer-left. |
| `x`, `y`, `z` | Numbers | Custom vector components. |
| `fallback` | `hold_last_pose`, `detach`, `fade_out` | Behavior when the target is unavailable. |

Fallback constants:

| Constant | Behavior |
|---|---|
| `TARGET_FALLBACK_HOLD_LAST_POSE` | Keep the card where it was last applied. |
| `TARGET_FALLBACK_DETACH` | Call the card's detach path. |
| `TARGET_FALLBACK_FADE_OUT` | Reserved behavior; currently holds position unless the card implements the visual fade. |

## Runtime behavior

Each frame, the card calls `update_attachments(card_anchor, primary_card_id)`.
The subsystem resolves the selected attachment's target, computes the offset
transform, applies it to the card anchor, records the last resolved position,
and fires `on_applied`.

For proxy targets in `world_latched` mode, the consumer stores the viewer
reference transform and target size from the first fresh target. The
depth-scaled offset then uses those stored values, so later head motion and
bbox width jitter do not move the latched card.

If the target cannot be resolved, fallback is applied from the attachment's
normalized offset rule. The card-side detach callback keeps anchor-mode side
effects outside this script.

## Runtime verification

```powershell
powershell -File tools\run_godot_card_attachment_probe.ps1
```

The probe runs `godot-android/tests/script_only_card_attachment_probe.gd` in
no-project mode. It verifies attach/detach state, resolver wiring,
world/target-space offset math, fallback behavior, apply callbacks, and status
inspection helpers.

Python coverage:

```powershell
python -m unittest tests.test_godot_card_attachment
```

## Extending CardAttachment

1. Add new offset modes as static math helpers and cover them in the probe.
2. Keep target lookup behind the resolver Callable.
3. Keep card-visible side effects in `AndroidMovingCard.gd`; route them through
   callbacks when needed.
4. Keep probe-visible code free of self-references to `CardAttachment` return
   types, because no-project mode does not register global classes.
