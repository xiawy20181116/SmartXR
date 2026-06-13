# TargetRegistry subsystem (Godot)

`godot-android/scripts/target_registry.gd` (`TargetRegistry`) is the card's
id-to-target lookup table. It stores duck-typed adapters that can resolve a
target id to a `Node3D` and expose the node's current global transform.

The registry is intentionally small and dependency-free. It does not search
the scene tree on its own; the card supplies the lookup root when it creates
adapters.

## Boundary

TargetRegistry owns:

- Mapping target ids to target adapters.
- Resolving a target id to the registered adapter.
- Adapter support for direct `Node3D`, `NodePath`, or String paths.
- Availability checks for registered targets.

`AndroidMovingCard.gd` still owns:

- Public card-facing methods such as `register_node3d_target`,
  `unregister_target`, and `attach_to_target`.
- Deciding which runtime objects become targets.
- Attachment fallback behavior when a target is missing.
- Status snapshot assembly.

## Public surface

| API | Caller | Meaning |
|---|---|---|
| `TargetRegistry.new()` | `AndroidMovingCard.gd` | Creates an empty registry. |
| `register(target_id, adapter)` | Card public API wrapper | Stores `adapter` under `target_id`; returns false for empty ids or null adapters. |
| `unregister(target_id)` | Card public API wrapper | Removes a target id if present. |
| `resolve(target_id)` | CardAttachment resolver and card helpers | Returns the adapter or null. |
| `Node3DTargetAdapter.new(root, node_or_path)` | Card registration path | Wraps a direct node, `NodePath`, or String path. |
| `adapter.get_node3d()` | Attachment and probes | Resolves the live node. |
| `adapter.is_available()` | Attachment and probes | True when the target resolves to a valid `Node3D`. |
| `adapter.get_global_transform()` | Attachment and probes | Returns the target's global transform. |

## Adapter inputs

| Input | Resolution |
|---|---|
| `Node3D` | Stored directly. |
| `NodePath` | Resolved against the root passed to the adapter. |
| String path | Converted to `NodePath` and resolved against the root. |

The adapter returns null when a path cannot be resolved or the resolved object
is not a `Node3D`.

## Runtime behavior

The card creates one registry instance and uses it as the shared target lookup
for attachments and proxy target nodes. `CardAttachment` receives
`_target_registry.resolve` as its resolver Callable, which keeps attachment
logic independent from the scene tree.

This means a target can disappear without corrupting the registry. The adapter
becomes unavailable, and the attachment subsystem applies its configured
fallback mode.

## Runtime verification

```powershell
powershell -File tools\run_godot_target_registry_probe.ps1
```

The probe runs `godot-android/tests/script_only_target_registry_probe.gd` in
no-project mode. It verifies direct-node registration, path registration,
missing targets, unregister behavior, transform access, and invalid input
handling.

Python coverage:

```powershell
python -m unittest tests.test_godot_target_registry
```

## Extending TargetRegistry

1. Keep the registry dependency-free and scene-agnostic.
2. Add new target adapter behavior to the adapter, not to card attachment.
3. Preserve null-on-missing behavior so fallback stays centralized in
   `CardAttachment`.
4. Keep probe-visible code free of self-references to `TargetRegistry` return
   types, because no-project mode does not register global classes.
