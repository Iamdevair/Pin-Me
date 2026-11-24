"""Pure balance comparison. Providers call this so the rule is testable without RPC."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

Direction = Literal["up", "down"]


def balance_direction(
    previous: Decimal | None,
    current: Decimal,
    min_change: Decimal,
    *,
    bootstrapped: bool,
) -> Direction | None:
    """None means 'do not alert' — either this is the baseline or the move is dust."""
    if not bootstrapped or previous is None:
        return None
    delta = current - previous
    if abs(delta) < min_change:
        return None
    if delta == 0:
        return None
    return "up" if delta > 0 else "down"
