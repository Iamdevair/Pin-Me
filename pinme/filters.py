"""Per-source allow lists from config/events.yaml. Shared by every webhook module."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from pinme.routing import ConfigError


@dataclass(frozen=True)
class SourceFilter:
    enabled: bool
    allow: frozenset[str]
    include_customer_email: bool = False

    def accepts(self, event: str) -> bool:
        if not self.enabled:
            return False
        if "*" in self.allow:
            return True
        return event in self.allow


def load_source_filter(path: Path, source: str) -> SourceFilter:
    if not path.exists():
        raise ConfigError(f"missing events file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must be a mapping")
    block = data.get(source) or {}
    if not isinstance(block, dict):
        raise ConfigError(f"{path} key {source!r} must be a mapping")
    allow_raw = block.get("allow") or []
    if allow_raw == "*":
        allow = frozenset({"*"})
    elif isinstance(allow_raw, list):
        allow = frozenset(str(item).strip() for item in allow_raw if str(item).strip())
    else:
        raise ConfigError(f"{path} {source}.allow must be a list or '*'")
    return SourceFilter(
        enabled=bool(block.get("enabled", True)),
        allow=allow,
        include_customer_email=bool(block.get("include_customer_email", False)),
    )
