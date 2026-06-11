# HANDOFF

Last updated: 2026-06-11 (YAN-71 offline simulation toolkit)

## Current state

- Branch `agent/orion/4bb5e36c` (from `main`) adds the offline simulation +
  jitter toolkit. All tests pass: 128 python unittests, 65 validate_project.ps1
  checks.
- PR #6 (Card attach 3D position diagnostics, Godot side) is still **open** and
  independent of this branch — no file overlap.

## What works now (verified)

- Offline replay without headset: `python tools/vst_proxy_targets_publisher.py
  --input <session.jsonl> --hz 20 [--smooth one_euro]` serves recorded frames
  over WS to the desktop PCMR consumer.
- Offline jitter metrics: `python tools/analyze_proxy_targets_jitter.py
  --input <session.jsonl> [--smooth ...] [--output report.json]`.
- Live publisher accepts the same `--smooth*` flags (not yet device-tested).
- Full workflow doc: `docs/offline_jitter_simulation.md`.

## Unfinished / risks

- **No real recorded session exists yet.** All offline verification so far used
  synthetic noisy sessions. Someone must run
  `dump_antman_vst_humantrackor_jsonl.py --out session.jsonl` once against the
  live VST source and ideally commit a short anonymized sample as a fixture.
- Smoothing defaults (`one_euro min_cutoff=1.0 beta=0.05`) are educated
  guesses; tune against the real session before judging.
- The smoother is applied to all targets in a message; if multiple people are
  tracked, per-target state is independent (by `target_id`), but track-id
  swaps from the tracker will look like position jumps — the filter does not
  hide those.
- Consumer-side jitter (head-to-world in Godot) is intentionally out of scope;
  see DECISIONS.md.

## Next concrete step

Record one real session, run the analyzer, pick parameters, replay into
desktop PCMR for a visual A/B, then enable `--smooth` on the device publisher.
