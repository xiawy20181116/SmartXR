"""Compatibility wrapper. Implementation lives in the ``smartxr`` package.

Kept so existing runners, tests, and docs that reference
``tools/fake_proxy_targets_publisher.py`` keep working unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.cli.fake_publisher import main, parse_args, serve  # noqa: E402,F401
from smartxr.publisher import (  # noqa: E402,F401
    build_fake_proxy_targets_message as build_proxy_targets_message,
)
from smartxr.transport import (  # noqa: E402,F401
    WEBSOCKET_GUID,
    decode_websocket_frame,
    drain_client_frames as _drain_client_frames,
    encode_websocket_control_frame,
    encode_websocket_text_frame,
    handshake as _handshake,
    parse_headers as _parse_headers,
    read_http_request as _read_http_request,
)

if __name__ == "__main__":
    main()
