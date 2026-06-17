"""Compatibility wrapper for the clip-level capture manifest validator.

Documented gate command:

    python tools/validate_clip_manifest_schema.py --input docs/capture_clip_manifest.json
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.clip_manifest_schema import (  # noqa: E402,F401
    ALLOWED_ENTRY_EXIT,
    ALLOWED_LIGHTING,
    ALLOWED_MOTION_PATTERNS,
    ALLOWED_TIERS,
    REQUIRED_LABELS,
    load_manifest,
    validate_manifest,
)
from smartxr.cli.validate_clip_manifest import main  # noqa: E402,F401


if __name__ == "__main__":
    raise SystemExit(main())
