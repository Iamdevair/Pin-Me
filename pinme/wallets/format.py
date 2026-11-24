"""Shared number formatting for embeds."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


def from_units(raw: int, decimals: int) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** decimals)


def format_amount(value: Decimal, places: int = 6) -> str:
    quantum = Decimal(10) ** -places
    quantized = value.quantize(quantum, rounding=ROUND_DOWN)
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def short_hash(value: str, keep: int = 10) -> str:
    if len(value) <= keep * 2 + 1:
        return value
    return f"{value[:keep]}…{value[-keep:]}"
