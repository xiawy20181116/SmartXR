"""Compatibility wrapper. Implementation lives in ``smartxr``.

Keeps the documented C1 schema-gate command stable:

    python tools/validate_tracking_raw_payload_schema.py --input <payload.json>
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.cli.validate_tracking_raw import main  # noqa: E402,F401
from smartxr.tracking_raw_schema import (  # noqa: E402,F401
    ALLOWED_POSE_QUALITY,
    ALLOWED_STATES,
    RAW_SOURCE_FIELDS,
    load_message,
    validate_message,
)

if __name__ == "__main__":
    raise SystemExit(main())
