# Offline Simulation and Jitter Debugging (No Headset Required)

This workflow lets you record one live VST session, then iterate on jitter
fixes entirely offline: quantify jitter numerically, tune a smoothing filter,
and visually verify in desktop PCMR — without connecting the headset again.

## Pipeline overview

```
record (one-time, live)            offline loop (no headset)
-----------------------            ------------------------------------------
dump_antman_vst_humantrackor  -->  analyze_proxy_targets_jitter.py  (metrics)
  _jsonl.py --> session.jsonl -->  vst_proxy_targets_publisher.py   (WS replay)
                                     --> Godot consumer / desktop PCMR (visual)
```

Both the analyzer and the replay publisher run the recorded frames through the
exact same math as the live publisher (`normalize_frame` +
`normalize_source_payload`), so offline results transfer 1:1 to the device.

## Step 1 — Record a session (one-time, with the live VST source)

```powershell
python tools\dump_antman_vst_humantrackor_jsonl.py --duration-seconds 60 --out .tmp\session.jsonl
```

Run `python tools\dump_antman_vst_humantrackor_jsonl.py --help` for source
options (`--antman-root`, `--shm-name`, model/backend flags). The output JSONL
contains one frame record per line: `frame_id`, `timestamp_ms`, image size,
and tracked people bboxes. Any JSONL in this shape works as replay input.

## Step 2 — Quantify jitter offline (no Godot, no headset)

```powershell
python tools\analyze_proxy_targets_jitter.py --input .tmp\session.jsonl
```

Reports per target: per-axis position std, frame-to-frame delta (mean / p95 /
max, in meters), angular jitter (deg), and bbox-center pixel jitter. Pixel
jitter tells you how much of the 3D jitter is plain detection noise; at the
default 5 m depth, 1 px of bbox noise is roughly 7 mm of head-space motion.

Compare smoothing settings without touching any pipeline code:

```powershell
python tools\analyze_proxy_targets_jitter.py --input .tmp\session.jsonl --smooth one_euro
python tools\analyze_proxy_targets_jitter.py --input .tmp\session.jsonl --smooth one_euro --smooth-min-cutoff 0.5 --smooth-beta 0.1
python tools\analyze_proxy_targets_jitter.py --input .tmp\session.jsonl --smooth ema --smooth-ema-alpha 0.3
python tools\analyze_proxy_targets_jitter.py --input .tmp\session.jsonl --smooth one_euro --output .tmp\report.json
```

The report shows raw vs smoothed metrics side by side plus a
`jitter_reduction_pct`. Tune until frame deltas are acceptable; One Euro's
`--smooth-min-cutoff` controls jitter removal at rest (lower = smoother) and
`--smooth-beta` controls responsiveness during fast motion (higher = less lag).

## Step 3 — Replay into desktop PCMR for visual verification

Terminal 1 — replay the recorded session over WebSocket (loops forever):

```powershell
python tools\vst_proxy_targets_publisher.py --input .tmp\session.jsonl --hz 20 --smooth one_euro
```

Terminal 2 — run the Godot consumer on Windows (PCMR preview, no headset):

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_windows_pcmr.ps1
Get-Content "$env:APPDATA\Godot\app_userdata\demo_run\proxy_targets_live_status.json" -Raw
```

Toggle `--smooth` on/off (or change parameters) and compare card stability
visually against the exact same recorded motion.

## Step 4 — Apply the tuned filter to the live publisher

The live publisher accepts the same flags, so the offline-tuned values carry
over unchanged:

```powershell
python tools\antman_vst_proxy_targets_live_publisher.py --smooth one_euro --smooth-min-cutoff 0.5 --smooth-beta 0.1
```

## Smoothing flags (shared by analyzer, replay, and live publisher)

| Flag | Default | Meaning |
| --- | --- | --- |
| `--smooth` | `none` | `none`, `ema`, or `one_euro` |
| `--smooth-ema-alpha` | `0.4` | EMA blend factor (lower = smoother, more lag) |
| `--smooth-min-cutoff` | `1.0` | One Euro min cutoff Hz (lower = smoother at rest) |
| `--smooth-beta` | `0.05` | One Euro speed coefficient (higher = less lag in motion) |
| `--smooth-d-cutoff` | `1.0` | One Euro derivative cutoff Hz |

Filter state is kept per `target_id` and resets on client reconnect and on
each replay loop wrap, so the end-of-recording jump is never smoothed into a
visible swoosh.

## Notes and limits

- Smoothing is applied publisher-side to head-space target positions, before
  the WebSocket send. Head-pose-induced jitter in the head-to-world transform
  happens consumer-side in Godot and is not covered by this filter; if jitter
  persists with a perfectly smooth replayed stream, the remaining source is
  consumer-side.
- The replay publisher paces frames at `--hz` (fixed rate); frame order and
  per-frame noise are preserved, which is what matters for jitter work.
