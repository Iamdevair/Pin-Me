"""The only object a source is allowed to hand to Discord.

Wallets, Paystack, and Shopify all build an Alert. The Discord layer does not
know which API the alert came from. Add a source by publishing these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


SEVERITIES = ("info", "success", "warning", "critical")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Alert:
    source: str
    event: str
    title: str
    body: str
    severity: str = "info"
    fields: dict[str, str] = field(default_factory=dict)
    dedupe_key: str | None = None
    url: str | None = None
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")
        self.source = self.source.strip().lower()
        self.event = self.event.strip()
        # Discord field values are capped at 1024. Trim here so every source
        # gets the same safety without importing discord.py.
        clean: dict[str, str] = {}
        for key, value in self.fields.items():
            text = "" if value is None else str(value)
            clean[str(key)[:256]] = text[:1024]
        self.fields = clean
        self.title = self.title[:256]
        self.body = self.body[:4000]
