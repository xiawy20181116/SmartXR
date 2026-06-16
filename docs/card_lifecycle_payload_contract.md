# card_lifecycle (C3) payload contract

## Seam

C3 is the **card-lifecycle** seam: the card producer (module 3 / module 5)
sends card commands to module 2 (godot card). It carries the binding command
(`attach` / `detach`) plus the visual `card_state` lifecycle (`appear` /
`expand` / `contract` / `disappear`) with a defined transition machine, an
optional `offset_rule` (same shape as the C2 proxy_targets offset rule) and
per-step animation durations.

C3 is about **card commands and state**, not target geometry. Target poses come
over C2 (`proxy_targets`); C3 says which card binds to which target and how it
should animate through its lifecycle.

Code form: `smartxr/card_lifecycle_schema.py`. The state machine is enforced by
the fake consumer in `smartxr/card_lifecycle_fakes.py`.

## Message shape

Required top-level fields:

- `type`: `card_lifecycle`
- `schema_version`: `1`
- `sequence`: integer producer sequence
- `timestamp_ms`: producer clock (monotonic ms, documented epoch)
- `commands`: non-empty array of commands

Required command fields:

- `card_id`: card wrapper id, e.g. `CardAnchor`
- `target_id`: id of the target this card binds to (a target from the matching
  C2 stream)
- `command`: one of `attach`, `update`, `detach`
- `card_state`: one of `appear`, `expand`, `contract`, `disappear`

Optional command fields:

- `offset_rule`: object; same shape as the C2 offset rule
  (`{ mode, offset_space, right_m, up_m, fallback }`). If omitted, consumer
  defaults apply. Typically set on `attach`.
- `animation`: `{ duration_ms (>= 0), easing (string, optional) }`. If omitted,
  the consumer uses the default per-state duration below.

## Commands vs card_state

There are two axes. The **command** is the intent verb; the **card_state** is the
resulting visual state. They are coupled:

| command  | allowed card_state   | meaning                                        |
|----------|----------------------|------------------------------------------------|
| `attach` | `appear`             | bind the card to a target; the card appears    |
| `update` | `expand`, `contract` | drive the visual lifecycle while attached      |
| `detach` | `disappear`          | the card disappears and unbinds from the target|

A message that pairs a command with a card_state outside its allowed set (e.g.
`attach` + `expand`) is rejected at the schema boundary.

## State machine (transitions)

`detached` is the implicit null state before `attach` and after `detach`
completes; it is not a value carried on the wire. Legal transitions:

```
        attach/appear
detached ───────────────▶ appear
                            │  update/expand
                            ▼
                          expand ◀────┐
                            │         │ update/expand
              update/contract│        │
                            ▼         │
                         contract ────┘

  appear | expand | contract ──detach/disappear──▶ disappear
  disappear ──(cleanup)──▶ detached
```

Enumerated (`from -> to`): `detached -> appear`, `appear -> expand`,
`expand -> contract`, `contract -> expand`, `appear -> disappear`,
`expand -> disappear`, `contract -> disappear`, `disappear -> detached`.

The consumer tracks each card's current state and rejects any command whose
transition is not in this set (e.g. `update`/`expand` before `attach`, or
`appear -> contract`). Rejected commands are not applied (architecture section
12: malformed/illegal input is rejected, never partially applied). After
`disappear` the card returns to `detached` and may be re-attached.

## Default animation durations (ms)

Producers may override per command via `animation.duration_ms`; otherwise the
consumer falls back to:

| card_state | default duration_ms |
|------------|---------------------|
| `appear`   | 250                 |
| `expand`   | 200                 |
| `contract` | 200                 |
| `disappear`| 300                 |

## Freeze status (architecture section 5)

1. **Versioned schema**: `smartxr/card_lifecycle_schema.py` (`schema_version: 1`).
2. **Fixture + validator in the gate**: `card_lifecycle_sample.json` in
   `godot-android/fixtures/`, validated by
   `tools/validate_card_lifecycle_payload_schema.py` in CI.
3. **Fake producer + fake consumer**: `smartxr/card_lifecycle_fakes.py`
   (`build_fake_card_lifecycle_message` + `CardLifecycleConsumer`), each speaking
   only the schema. Round-trip + illegal-transition rejection in
   `tests/test_card_lifecycle_payload_schema.py`.
4. **Semantics doc**: this file.
5. **Change policy**: after freezing, only additive field changes are allowed.
   Any shape change (new command/card_state value that alters the machine,
   renamed/removed field) requires an explicit `schema_version++`. Silent
   reshaping is forbidden. Adding a card_state or transition is a shape change,
   not an additive field change.

## Gate command

```powershell
python tools\validate_card_lifecycle_payload_schema.py --input godot-android\fixtures\card_lifecycle_sample.json
```
