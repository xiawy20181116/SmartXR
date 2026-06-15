"""Compatibility wrapper for the assistant_updates fake publisher."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smartxr.cli.assistant_updates_publisher import (  # noqa: E402,F401
    build_demo_payload,
    is_assistant_updates_request,
    main,
    parse_args,
    serve,
)


if __name__ == "__main__":
    main()
