"""Canonical card_lifecycle (C3) message model and validation.

This module is the code form of ``docs/card_lifecycle_payload_contract.md`` and
the C3 seam in ``docs/architecture_modules.md`` (section 4). C3 carries card
commands from the producer side (module 3 / module 5) to module 2 (godot card):
the binding command (``attach`` / ``detach``) plus the visual ``card_state``
lifecycle (``appear`` / ``expand`` / ``contract`` / ``disappear``) with a
defined transition machine, an optional ``offset_rule`` (same shape as the C2
proxy_targets offset rule) and per-step animation durations.

The state machine itself (legal transitions) is enforced by the fake consumer
in ``smartxr.card_lifecycle_fakes`` and documented in the semantics doc; this
module validates message *shape* and the command/card_state coupling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

MESSAGE_TYPE = "card_lifecycle"

# Binding commands.
ALLOWED_COMMANDS = {"attach", "update", "detach"}

# Visual lifecycle states (the card_state enum).
ALLOWED_CARD_STATES = {"appear", "expand", "contract", "disappear"}

# "detached" is the implicit null state before attach / after detach completes.
# It is not a card_state value carried on the wire.
DETACHED = "detached"

# Command -> the card_state(s) that command may carry. This is the static
# coupling rule validated here; the dynamic transition machine (which prior
# state each may follow) lives in the consumer.
COMMAND_CARD_STATES = {
    "attach": {"appear"},
    "update": {"expand", "contract"},
    "detach": {"disappear"},
}

# Legal card_state transitions, including the implicit DETACHED null state.
# Enforced by the consumer; documented for both sides to build against.
ALLOWED_TRANSITIONS = {
    (DETACHED, "appear"),     # attach
    ("appear", "expand"),     # update
    ("expand", "contract"),   # update
    ("contract", "expand"),   # update
    ("appear", "disappear"),  # detach
    ("expand", "disappear"),  # detach
    ("contract", "disappear"),  # detach
    ("disappear", DETACHED),  # cleanup after detach completes
}

# Default per-state animation durations (ms). Producers may override per command
# via the optional ``animation.duration_ms``; consumers fall back to these.
DEFAULT_ANIMATION_MS = {
    "appear": 250,
    "expand": 200,
    "contract": 200,
    "disappear": 300,
}


def default_offset_rule() -> dict[str, Any]:
    """Default card offset rule, identical in shape to the C2 proxy_targets rule."""
    return {
        "mode": "right_top",
        "offset_space": "world",
        "right_m": 0.35,
        "up_m": 0.25,
        "fallback": "hold_last_pose",
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_animation(animation: Any, path: str, errors: list[str]) -> None:
    if not isinstance(animation, dict):
        errors.append(f"{path} must be an object when present")
        return
    duration = animation.get("duration_ms")
    if not _is_number(duration) or duration < 0:
        errors.append(f"{path}.duration_ms must be a non-negative number")
    if "easing" in animation and not isinstance(animation["easing"], str):
        errors.append(f"{path}.easing must be a string when present")


def _validate_command(command: Any, index: int, errors: list[str]) -> None:
    path = f"$.commands[{index}]"
    if not isinstance(command, dict):
        errors.append(f"{path} must be an object")
        return

    if not isinstance(command.get("card_id"), str) or not command.get("card_id"):
        errors.append(f"{path}.card_id must be a non-empty string")
    if not isinstance(command.get("target_id"), str) or not command.get("target_id"):
        errors.append(f"{path}.target_id must be a non-empty string")

    verb = command.get("command")
    card_state = command.get("card_state")
    if verb not in ALLOWED_COMMANDS:
        errors.append(f"{path}.command must be one of {sorted(ALLOWED_COMMANDS)}")
    if card_state not in ALLOWED_CARD_STATES:
        errors.append(f"{path}.card_state must be one of {sorted(ALLOWED_CARD_STATES)}")
    if verb in COMMAND_CARD_STATES and card_state not in COMMAND_CARD_STATES[verb]:
        errors.append(
            f"{path}.card_state must be one of {sorted(COMMAND_CARD_STATES[verb])} "
            f"for command '{verb}'"
        )

    if "offset_rule" in command and not isinstance(command["offset_rule"], dict):
        errors.append(f"{path}.offset_rule must be an object when present")
    if "animation" in command:
        _validate_animation(command["animation"], f"{path}.animation", errors)


def validate_message(message: Any) -> list[str]:
    """Validate a canonical card_lifecycle (C3) message. Returns a list of errors."""
    errors: list[str] = []
    if not isinstance(message, dict):
        return ["$ must be an object"]

    if message.get("type") != MESSAGE_TYPE:
        errors.append(f"$.type must be {MESSAGE_TYPE}")
    if message.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"$.schema_version must be {SCHEMA_VERSION}")
    if not _is_int(message.get("sequence")):
        errors.append("$.sequence must be an integer")
    if not _is_number(message.get("timestamp_ms")):
        errors.append("$.timestamp_ms must be a number")

    commands = message.get("commands")
    if not isinstance(commands, list) or not commands:
        errors.append("$.commands must be a non-empty array")
    else:
        for index, command in enumerate(commands):
            _validate_command(command, index, errors)

    return errors


def load_message(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
