# Capture clip manifest and data tiers

## Purpose

`docs/capture_clip_manifest.json` is the clip/session-level label layer for the
real VST capture package used in `docs/yolov8n_vst_verification.json`. It keeps
the package inventory shape separate from the data-grading labels: scene, person
count, distance, motion, lighting, and enter/exit event.

Code form: `smartxr/clip_manifest_schema.py`. Gate command:

```powershell
python tools\validate_clip_manifest_schema.py --input docs\capture_clip_manifest.json
```

The source package path recorded by the older verification report is not present
in this workspace, so this first manifest uses committed verification statistics
for observed labels and marks distance, lateral motion, and lighting as
`unknown`/`unlabeled` where the committed artifacts do not carry that evidence.
Those fields are still required so future capture packages cannot silently omit
them.

## Manifest shape

- `type`: `capture_clip_manifest`
- `schema_version`: `1`
- `source_package`: package id, source manifest name, verification artifact, and
  tracker replay fixture. `source_manifest` is `CAPTURE_PACKAGE_MANIFEST.json`
  so the clip manifest can extend that package-level inventory when the raw
  package is available.
- `clips`: one object per clip/session.
- `clips[].tier`: one of `T0`, `T1`, `T2`, `T3`.
- `clips[].labels.scene`: scene value plus label confidence.
- `clips[].labels.people`: sampled min/max/dominant counts and the sampled count
  histogram from the yolov8n verification report.
- `clips[].labels.distance`: `near`, `mid`, `far`, `mixed`, or `unknown`.
- `clips[].labels.motion`: `static`, `lateral`, `approach_recede`, `mixed`,
  `presence_change`, `sparse_presence`, `steady_presence`, or `unknown`.
- `clips[].labels.lighting`: `normal_indoor`, `low_light`, `backlit`, `mixed`,
  or `unknown`.
- `clips[].labels.entry_exit`: `yes`, `no`, `candidate`, or `unknown`.

## T0-T3 tiers

| Tier | Definition | Use | Gate |
| --- | --- | --- | --- |
| T0 | Smoke data: synthetic frames, fake publishers, replay plumbing checks, and short capture sanity runs. | Verify tooling and schema wiring only. | Must not be used to accept detector/tracker quality. |
| T1 | Basic real VST data: current six recorded sessions, including empty frames, single person, two-plus people, sparse presence, steady presence, and candidate enter/exit transitions. | Run yolov8n + tracker on true images to get a first real-world signal. | Manifest validates, `docs/yolov8n_vst_verification.md` covers the six-session detector sweep, and `godot-android/fixtures/tracking_raw_replay_c1.jsonl` covers the committed tracker replay window. |
| T2 | Complex real VST data: targeted clips for occlusion, dense crowds, fast motion, back-facing people, half-body/edge-body framing, low light, backlight, and clutter. | Reproduce specific weaknesses found in T1 or later field runs. | Each clip must carry the same clip-level labels before being used for regression decisions. |
| T3 | Annotated evaluation data: targeted frames/clips with frame-level 2D bbox + id labels. 3D ground truth is only collected through controlled acquisition, such as known-distance/stereo capture, not by visual estimation. | Quantitative detector/tracker evaluation and id-switch measurement. | Created only after the T3 gate below opens. |

## T3 gate

T3 gate: run the T1 captures through yolov8n + tracker first, review the real
failure modes, then annotate only the slices needed to measure that gap. The
current T1 report (`docs/yolov8n_vst_verification.md`) found yolov8n adequate for
the v1 "card near the person" goal. The tracker path is covered by the committed
real-detection replay fixture `godot-android/fixtures/tracking_raw_replay_c1.jsonl`
for `capture_20260415T065340Z` frames 351-550, which exercises the C1 lifecycle,
empty-frame handling, and id-stability sanity bound. Together these T1 checks do
not open a v1 T3 annotation set yet.

If a future T1/T2 run exposes a concrete gap, create a targeted T3 set with:

- session id and frame range;
- 2D bbox + id per visible person;
- occlusion/truncation flags when they explain misses or id switches;
- the exact detector/tracker version evaluated;
- metric target, such as recall on low light or id-switch rate under occlusion.

3D ground truth belongs to the controlled stereo-depth iteration. It should be
captured with known geometry or dual-eye measurement, not manually estimated
from a single RGB frame.

## Current T1 labels

| Session | People histogram | Motion label | Enter/exit label | Notes |
| --- | --- | --- | --- | --- |
| `capture_20260415T055846Z` | 0:57, 1:39, 2:9 | `presence_change` | `candidate` | Real VST replay; distance and lighting not encoded. |
| `capture_20260415T062913Z` | 0:23, 1:4, 2:1, 3:1 | `sparse_presence` | `candidate` | Smoke-test-like real session with few person frames. |
| `capture_20260415T063047Z` | 0:43, 1:29, 2:21, 3:22, 4:3, 5:3 | `presence_change` | `candidate` | Multi-person T1 coverage. |
| `capture_20260415T063848Z` | 0:23, 1:38, 2:16, 3:17, 4:11 | `presence_change` | `candidate` | Frequent person detections. |
| `capture_20260415T065340Z` | 0:85, 1:36, 2:28, 3:10, 4:9, 5:6, 6:3 | `presence_change` | `candidate` | Widest sampled person-count range. |
| `capture_20260417T073836Z` | 0:3, 1:219, 2:5 | `steady_presence` | `no` | Current single-person steady baseline. |
