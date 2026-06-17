"""Compatibility wrapper. Implementation lives in ``smartxr``.

Module 3 live bridge -- subscribe to a C1 tracking_raw WS, convert to
proxy_targets, serve it to the Godot card:

    python tools/run_mr_integration_bridge.py \
        --c1-url ws://127.0.0.1:8770/tracking_raw \
        --host 127.0.0.1 --port 8766 [--right-eye-to-head matrix.json]
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.cli.mr_integration_bridge import main  # noqa: E402,F401

if __name__ == "__main__":
    raise SystemExit(main())
