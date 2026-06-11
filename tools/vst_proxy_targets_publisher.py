"""Compatibility wrapper. Implementation lives in the ``smartxr`` package.

Kept so existing runners, tests, and docs that reference
``tools/vst_proxy_targets_publisher.py`` keep working unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.cli.vst_publisher import main, parse_args, serve  # noqa: E402,F401
from smartxr.geometry import vst_camera_point_to_head as _vst_camera_point_to_head  # noqa: E402,F401
from smartxr.publisher import (  # noqa: E402,F401
    DEFAULT_COORDINATE_SPACE,
    DEFAULT_HORIZONTAL_FOV_DEG,
    DEFAULT_TARGET_DEPTH_M,
    DEFAULT_VERTICAL_FOV_DEG,
    load_source_messages,
    load_source_payload,
    normalize_source_payload,
    replay_message_at,
)

if __name__ == "__main__":
    raise SystemExit(main())
