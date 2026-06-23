from __future__ import annotations

import importlib.util
import shutil
import uuid
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "tools" / "verify_yolov8n_on_capture.py"
TMP = ROOT / ".tmp" / "test_verify_yolov8n_on_capture"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VerifyYolov8nOnCaptureTests(unittest.TestCase):
    def make_tmp_dir(self) -> Path:
        path = TMP / uuid.uuid4().hex
        path.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def test_session_dirs_accepts_direct_session_dir(self):
        verifier = load_module(VERIFIER, "verify_yolov8n_on_capture")
        session = self.make_tmp_dir()
        (session / "nv12_packets").mkdir()

        self.assertEqual(verifier._session_dirs(session), [session])

    def test_session_dirs_accepts_capture_root_with_child_sessions(self):
        verifier = load_module(VERIFIER, "verify_yolov8n_on_capture")
        root = self.make_tmp_dir()
        session = root / "capture_001"
        (session / "nv12_packets").mkdir(parents=True)

        self.assertEqual(verifier._session_dirs(root), [session])


if __name__ == "__main__":
    unittest.main()
