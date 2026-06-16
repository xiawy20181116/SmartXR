"""Fake producer and fake consumer for the card_lifecycle (C3) seam.

Both speak only the C3 schema (``smartxr.card_lifecycle_schema``); neither
depends on the real card producer (module 3/5) nor the real godot card (module
2). This satisfies the section-5 freeze requirement #3.

The producer emits a canonical lifecycle sequence (attach/appear -> expand ->
contract -> detach/disappear). The consumer runs the C3 state machine per card
and rejects illegal transitions, so the transition contract is observable
without the Godot runtime.
"""

from __future__ import annotations

from typing import Any

from smartxr.card_lifecycle_schema import (
    ALLOWED_TRANSITIONS,
    DEFAULT_ANIMATION_MS,
    DETACHED,
    MESSAGE_TYPE,
    SCHEMA_VERSION,
    default_offset_rule,
    validate_message,
)


def _command(
    card_id: str,
    target_id: str,
    verb: str,
    card_state: str,
    *,
    with_offset_rule: bool = False,
) -> dict[str, Any]:
    command: dict[str, Any] = {
        "card_id": card_id,
        "target_id": target_id,
        "command": verb,
        "card_state": card_state,
        "animation": {
            "duration_ms": DEFAULT_ANIMATION_MS[card_state],
            "easing": "ease_in_out",
        },
    }
    if with_offset_rule:
        command["offset_rule"] = default_offset_rule()
    return command


def build_fake_card_lifecycle_message(
    card_id: str = "CardAnchor",
    target_id: str = "person-7",
    sequence: int = 0,
    timestamp_ms: float = 0.0,
) -> dict[str, Any]:
    """A single C3 message carrying the full canonical lifecycle for one card.

    attach/appear -> update/expand -> update/contract -> update/expand ->
    detach/disappear. Every transition in this sequence is legal per
    ``ALLOWED_TRANSITIONS``.
    """
    return {
        "type": MESSAGE_TYPE,
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "timestamp_ms": timestamp_ms,
        "commands": [
            _command(card_id, target_id, "attach", "appear", with_offset_rule=True),
            _command(card_id, target_id, "update", "expand"),
            _command(card_id, target_id, "update", "contract"),
            _command(card_id, target_id, "update", "expand"),
            _command(card_id, target_id, "detach", "disappear"),
        ],
    }


class CardLifecycleConsumer:
    """Fake C3 consumer: validates messages and runs the per-card state machine.

    Tracks each card's current card_state (starting from DETACHED) and accepts a
    command only if (current_state -> command.card_state) is in
    ``ALLOWED_TRANSITIONS``. After a ``disappear`` the card returns to DETACHED so
    it can be re-attached. Illegal transitions are rejected, not applied.
    """

    def __init__(self) -> None:
        self.commands_accepted = 0
        self.commands_rejected = 0
        self.messages_rejected = 0
        self.state_by_card: dict[str, str] = {}
        self.errors: list[str] = []

    def current_state(self, card_id: str) -> str:
        return self.state_by_card.get(card_id, DETACHED)

    def consume(self, message: Any) -> bool:
        """Validate the message shape, then apply each command in order.

        Returns True only if the message is well-formed AND every command is a
        legal transition.
        """
        errors = validate_message(message)
        if errors:
            self.messages_rejected += 1
            self.errors.extend(errors)
            return False

        all_ok = True
        for index, command in enumerate(message["commands"]):
            card_id = command["card_id"]
            target = command["card_state"]
            current = self.current_state(card_id)
            if (current, target) not in ALLOWED_TRANSITIONS:
                self.commands_rejected += 1
                self.errors.append(
                    f"$.commands[{index}] illegal transition {current} -> {target} "
                    f"for card {card_id}"
                )
                all_ok = False
                continue
            self.commands_accepted += 1
            # After disappear the card is cleaned up back to DETACHED.
            self.state_by_card[card_id] = DETACHED if target == "disappear" else target
        return all_ok
