"""Tiny async pub/sub. One process, no external broker.

Sources publish. The Discord notifier is the default subscriber. Tests can
subscribe a list and never open a socket.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from pinme.core.alerts import Alert

log = logging.getLogger(__name__)

Subscriber = Callable[[Alert], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, handler: Subscriber) -> None:
        self._subscribers.append(handler)

    async def publish(self, alert: Alert) -> None:
        for handler in self._subscribers:
            try:
                await handler(alert)
            except Exception:
                log.exception(
                    "subscriber failed for %s %s", alert.source, alert.event
                )
