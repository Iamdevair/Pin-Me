"""Map an alert to a Discord channel. Edit config/routes.yaml, not this file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Yaml or env is present but not usable. The message lists every problem."""


@dataclass(frozen=True)
class Route:
    source: str
    event: str
    channel_id: int


@dataclass(frozen=True)
class RouteTable:
    default_channel_id: int | None
    routes: tuple[Route, ...]


def _as_channel(value: object, where: str) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or "REPLACE" in text or text.lower() in {"todo", "changeme"}:
        return None
    if not text.isdigit():
        raise ConfigError(f"{where} must be a Discord channel id, got {value!r}")
    return int(text)


def load_routes(path: Path) -> RouteTable:
    if not path.exists():
        raise ConfigError(f"missing routes file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must be a mapping")
    default = _as_channel(data.get("default_channel_id"), f"{path} default_channel_id")
    routes: list[Route] = []
    for index, item in enumerate(data.get("routes") or []):
        if not isinstance(item, dict):
            raise ConfigError(f"{path} routes[{index}] must be a mapping")
        source = str(item.get("source") or "*").strip().lower()
        event = str(item.get("event") or "*").strip()
        channel = _as_channel(item.get("channel_id"), f"{path} routes[{index}].channel_id")
        if channel is None:
            continue
        routes.append(Route(source=source, event=event, channel_id=channel))
    return RouteTable(default_channel_id=default, routes=tuple(routes))


def resolve_channel(table: RouteTable, source: str, event: str) -> int | None:
    """Pick a channel.

    Order: exact source+event, any-source+exact event, source+wildcard,
    any-source+wildcard, then the file's default channel.
    """
    source = source.lower()
    found: dict[tuple[str, str], int] = {}
    for route in table.routes:
        found.setdefault((route.source, route.event), route.channel_id)
    for key in ((source, event), ("*", event), (source, "*"), ("*", "*")):
        if key in found:
            return found[key]
    return table.default_channel_id

