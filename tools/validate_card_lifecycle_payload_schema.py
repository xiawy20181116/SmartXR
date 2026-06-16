"""Compatibility wrapper. Implementation lives in ``smartxr``.

Keeps the documented C3 schema-gate command stable:

    python tools/validate_card_lifecycle_payload_schema.py --input <payload.json>
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.cli.validate_card_lifecycle import main  # noqa: E402,F401
from smartxr.card_lifecycle_schema import (  # noqa: E402,F401
    ALLOWED_CARD_STATES,
    ALLOWED_COMMANDS,
    ALLOWED_TRANSITIONS,
    load_message,
    validate_message,
)

if __name__ == "__main__":
    raise SystemExit(main())
