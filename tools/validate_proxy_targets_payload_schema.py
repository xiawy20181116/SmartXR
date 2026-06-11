"""Compatibility wrapper. Implementation lives in ``smartxr.schema``.

Kept so the documented gate command keeps working unchanged:

    python tools/validate_proxy_targets_payload_schema.py --input <payload.json>
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.cli.validate_payload import main  # noqa: E402,F401
from smartxr.schema import (  # noqa: E402,F401
    ALLOWED_STATES,
    RAW_SOURCE_FIELDS,
    load_message,
    validate_message,
)

if __name__ == "__main__":
    raise SystemExit(main())
