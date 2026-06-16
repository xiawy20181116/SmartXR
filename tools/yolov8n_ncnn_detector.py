"""PC-side ncnn yolov8n person detector (module 1 detection backend, YAN-108).

This is the **PC-offload** detection backend: it runs the same
``godot-android/ncnn/yolov8n_320`` model the on-device path uses, but on a PC
over recorded (or, in deployment, streamed) frames. It decodes NV12 with the
pure-stdlib :mod:`smartxr.nv12_reader`, runs ncnn, and returns person
detections as normalized boxes -- the shape :mod:`smartxr.detection_backend`
expects, so the tracker / C1 producer are identical to the on-device topology.

Optional dependencies (numpy, opencv, ncnn) are imported lazily so importing
this module never breaks the dependency-free test suite; only constructing the
detector requires them. Set them up with::

    uv venv --python 3.12 .venv-detect
    uv pip install --python .venv-detect ncnn numpy opencv-python-headless

The model output ``out0`` is head-decoded: shape ``(84, 2100)`` = 4 box
(cx, cy, w, h in 320-letterbox pixels) + 80 class scores; person is class 0.
"""

from __future__ import annotations

import struct
from pathlib import Path

_HEADER = struct.Struct("<6IQ")
_HEADER_SIZE = _HEADER.size
INPUT_SIZE = 320
PERSON_CLASS = 0
PAD_VALUE = 114


class Yolov8nNcnnDetector:
    def __init__(
        self,
        param_path: Path,
        bin_path: Path,
        conf_threshold: float = 0.25,
        nms_iou: float = 0.5,
        input_size: int = INPUT_SIZE,
    ) -> None:
        import ncnn  # lazy

        self.conf_threshold = conf_threshold
        self.nms_iou = nms_iou
        self.input_size = input_size
        self._net = ncnn.Net()
        self._net.load_param(str(param_path))
        self._net.load_model(str(bin_path))
        self._ncnn = ncnn

    @staticmethod
    def decode_nv12(raw: bytes):
        """Decode one NV12 packet (header + payload) to a BGR ndarray (H, W, 3)."""
        import numpy as np
        import cv2

        magic, hsize, w, h, stride, payload, _ts = _HEADER.unpack_from(raw, 0)
        data = np.frombuffer(raw[_HEADER_SIZE : _HEADER_SIZE + payload], dtype=np.uint8)
        yuv = data.reshape((h * 3 // 2, stride))
        bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)  # treats stride as width
        return bgr[:, :w]  # drop stride padding columns

    def detect_bgr(self, bgr) -> list[dict]:
        """Detect people in a BGR image. Returns normalized-bbox records.

        Each record: ``{"bbox": [x, y, w, h], "confidence": c}`` in normalized
        (0..1) image coordinates, top-left x/y + width/height.
        """
        import numpy as np
        import cv2

        h, w = bgr.shape[:2]
        s = self.input_size
        r = min(s / w, s / h)
        nw, nh = int(round(w * r)), int(round(h * r))
        dx, dy = (s - nw) // 2, (s - nh) // 2
        canvas = np.full((s, s, 3), PAD_VALUE, np.uint8)
        canvas[dy : dy + nh, dx : dx + nw] = cv2.resize(bgr, (nw, nh))

        mat = self._ncnn.Mat.from_pixels(
            canvas.copy(), self._ncnn.Mat.PixelType.PIXEL_BGR2RGB, s, s
        )
        mat.substract_mean_normalize([], [1 / 255.0, 1 / 255.0, 1 / 255.0])
        ex = self._net.create_extractor()
        ex.input("in0", mat)
        _ret, out = ex.extract("out0")
        o = np.array(out)  # (84, 2100)

        boxes = o[:4].T  # (2100, 4) cx,cy,w,h in letterbox pixels
        scores = o[4:].T  # (2100, 80)
        cls = scores.argmax(1)
        conf = scores.max(1)
        keep = (cls == PERSON_CLASS) & (conf >= self.conf_threshold)

        dets = []
        for (cx, cy, bw, bh), c in zip(boxes[keep], conf[keep]):
            # letterbox pixels -> original image pixels
            x1 = (cx - bw / 2 - dx) / r
            y1 = (cy - bh / 2 - dy) / r
            x2 = (cx + bw / 2 - dx) / r
            y2 = (cy + bh / 2 - dy) / r
            dets.append([x1, y1, x2, y2, float(c)])

        dets = self._nms(dets)
        records = []
        for x1, y1, x2, y2, c in dets:
            # clamp to image, normalize
            x1 = max(0.0, min(x1, w))
            y1 = max(0.0, min(y1, h))
            x2 = max(0.0, min(x2, w))
            y2 = max(0.0, min(y2, h))
            records.append(
                {
                    "bbox": [
                        round(float(x1 / w), 6),
                        round(float(y1 / h), 6),
                        round(float((x2 - x1) / w), 6),
                        round(float((y2 - y1) / h), 6),
                    ],
                    "confidence": round(float(c), 4),
                }
            )
        return records

    def detect_nv12(self, raw: bytes) -> list[dict]:
        return self.detect_bgr(self.decode_nv12(raw))

    def _nms(self, dets: list[list[float]]) -> list[list[float]]:
        dets = sorted(dets, key=lambda d: -d[4])
        kept: list[list[float]] = []
        for d in dets:
            if all(self._iou_xyxy(d, k) < self.nms_iou for k in kept):
                kept.append(d)
        return kept

    @staticmethod
    def _iou_xyxy(a, b) -> float:
        ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
        ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
        iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
        inter = iw * ih
        ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / ua if ua > 0 else 0.0
