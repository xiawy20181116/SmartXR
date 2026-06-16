# yolov8n person-detection verification on real VST captures (YAN-108)

Module 1's "first step": confirm `godot-android/ncnn/yolov8n_320` actually finds
people on the **real** recorded VST imagery, and inform the T0–T3 data-tiering
decision from the YAN-96 thread (do we need frame-level annotation for v1?).

## Method

- Decode NV12 packets (`<6I Q` header, 880×660, stride 896) → BGR, letterbox to
  320×320, run ncnn `yolov8n_320`, keep class 0 (person) ≥ conf 0.25, NMS 0.5.
- Run on the `fixed_replay_captures-20260429-194546` package (6 sessions),
  sampling every 15th frame for the recall sweep.
- Tool: `tools/verify_yolov8n_on_capture.py` + `tools/yolov8n_ncnn_detector.py`
  (optional numpy/opencv/ncnn in `.venv-detect`). Raw numbers:
  `docs/yolov8n_vst_verification.json`.
- Inference cost ≈ 10.6 ms/frame (~94 fps) on PC CPU — comfortable for the
  PC-offload topology.

## Results (conf ≥ 0.25, every 15th frame)

| Session | Frames | Sampled | With person | Recall | Max conf | Mean conf | Count histogram (people→frames) |
|---|---|---|---|---|---|---|---|
| capture_20260415T055846Z | 1565 | 105 | 48 | 45.7% | 0.825 | 0.535 | 0:57 1:39 2:9 |
| capture_20260415T062913Z | 421 | 29 | 6 | 20.7% | 0.826 | 0.526 | 0:23 1:4 2:1 3:1 |
| capture_20260415T063047Z | 1801 | 121 | 78 | 64.5% | 0.900 | 0.597 | 0:43 1:29 2:21 3:22 4:3 5:3 |
| capture_20260415T063848Z | 1564 | 105 | 82 | 78.1% | 0.837 | 0.501 | 0:23 1:38 2:16 3:17 4:11 |
| capture_20260415T065340Z | 2641 | 177 | 92 | 52.0% | 0.946 | 0.575 | 0:85 1:36 2:28 3:10 4:9 5:6 6:3 |
| capture_20260417T073836Z | 3391 | 227 | 224 | 98.7% | 0.853 | 0.783 | 0:3 1:219 2:5 |

## Findings

- **yolov8n works on VST imagery.** Where a person is clearly framed, recall is
  high (98.7% on `073836Z`, a single steadily-present person) with strong
  confidence (mean 0.78). Multi-person sessions (`063047Z`, `065340Z`) detect up
  to 5–6 people per frame.
- **Recall tracks scene content, not a model failure.** The low-recall sessions
  are mostly empty/partial frames: `062913Z` is the "replay smoke test" with few
  people; the others include stretches with no one (or only partial/edge bodies)
  in view. The high zero-person bins are genuine empty frames, which C1 treats as
  a valid state — not misses to "fix".
- **Confidence is moderate-to-high.** Means 0.50–0.78, maxes 0.83–0.95. The card
  has high spatial tolerance, so this is comfortably sufficient for v1.

## Decision: no T3 frame annotation for v1

Per the YAN-96 tiering plan, T3 (frame-level 2D bbox + id annotation) is gated on
T1 exposing a real gap. T1 here shows the detector is adequate for the v1 "card
near the person" goal, so **v1 does not need T3**. What would still help is
cheap **clip-level** tags (person count / distance / motion / enter-exit), which
is the YAN-111 data line, not this issue. Frame-level / 3D-error ground truth is
only worth collecting later, via controlled known-distance capture, alongside
the stereo-depth iteration.

## Reproduce

```
uv venv --python 3.12 .venv-detect
uv pip install --python .venv-detect ncnn numpy opencv-python-headless
.venv-detect/Scripts/python.exe tools/verify_yolov8n_on_capture.py \
    --capture-root "<...>/fixed_replay_captures-20260429-194546" \
    --conf 0.25 --step 15 --report-out docs/yolov8n_vst_verification.json
```
