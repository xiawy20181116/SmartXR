"""SmartXR shared Python library.

Layered like the pi monorepo, with strictly one-way dependencies:

- ``smartxr.schema``    canonical proxy_targets message model + validation
- ``smartxr.geometry``  pure bbox->camera->head math (single source of truth)
- ``smartxr.transport`` WebSocket server primitives (handshake, frames, serve loop)
- ``smartxr.frames``    tracker frame normalization (detections -> source payload)
- ``smartxr.publisher`` proxy_targets builders / normalization / replay
- ``smartxr.mr_integration`` module 3: C1 tracking_raw -> C2 proxy_targets (align)
- ``smartxr.cli``       thin entry points used by the ``tools/`` wrappers

``tools/*.py`` remain as thin compatibility wrappers so existing runners,
tests, and documentation keep working unchanged.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
