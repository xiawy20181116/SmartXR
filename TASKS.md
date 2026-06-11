# TASKS

Issue: YAN-71 — VST Card alignment + jitter (offline simulation support)

## Completed

- [x] YAN-63 chain: publisher -> proxy_targets WS -> Godot consumer -> Card attach (merged)
- [x] VST camera -> head coordinate conversion, FOV projection, right-eye-to-head, source_coordinate diagnostics (PR #1, merged)
- [x] PCMR see-through alpha blend, head-space world transform, default depth 5m (merged)
- [x] Card attach 3D position diagnostics in live status (PR #6, open, waiting review/merge)
- [x] Offline simulation + jitter toolkit (this branch):
  - `tools/proxy_targets_smoothing.py` — EMA + One Euro per-target position filters
  - `tools/analyze_proxy_targets_jitter.py` — offline jitter metrics from recorded JSONL, raw vs smoothed
  - `--smooth*` flags wired into replay publisher (`vst_proxy_targets_publisher.py`) and live publisher (`antman_vst_proxy_targets_live_publisher.py`)
  - `docs/offline_jitter_simulation.md` — record -> analyze -> tune -> replay -> deploy workflow
  - Tests: 128 python unittests + 65 validate_project.ps1 checks pass

## Next

- [ ] Record a real session with `dump_antman_vst_humantrackor_jsonl.py --out session.jsonl` (one-time, needs live VST source)
- [ ] Run analyzer on the real session, pick smoothing parameters (start: `--smooth one_euro --smooth-min-cutoff 0.5 --smooth-beta 0.1`)
- [ ] Visual check: replay with/without `--smooth` into desktop PCMR
- [ ] Apply tuned flags to live publisher on device; capture jitter status
- [ ] Review/merge PR #6 (3D position diagnostics), then PR for this branch
- [ ] If jitter persists with smooth replayed stream: investigate consumer-side (head-to-world transform in Godot)
