"""Compatibility wrapper. Implementation lives in ``smartxr``.

Module 3 display wiring -- convert C1 tracking_raw payloads to C2 proxy_targets:

    python tools/convert_tracking_raw_to_proxy_targets.py \
        --input <c1.json|c1.jsonl> [--output <c2.json|c2.jsonl>] \
        [--right-eye-to-head <matrix.json>]
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.cli.convert_tracking_raw import main  # noqa: E402,F401

if __name__ == "__main__":
    raise SystemExit(main())
