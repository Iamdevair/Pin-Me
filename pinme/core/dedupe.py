"""Remember alert keys so a Paystack retry or a restarted poll does not double-post.

Memory is the hot path. A JSON file survives restarts. Keys expire so the
file cannot grow without bound.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 48 * 60 * 60


class DedupeStore:
    def __init__(self, path: Path | None = None, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self._seen: dict[str, float] = {}
        if path is not None and path.exists():
            self._load()

    def allow(self, key: str | None) -> bool:
        """Return True if this key should be delivered."""
        if not key:
            return True
        now = time.time()
        self._expire(now)
        seen_at = self._seen.get(key)
        if seen_at is not None and now - seen_at < self.ttl_seconds:
            return False
        self._seen[key] = now
        self._save()
        return True

    def _expire(self, now: float) -> None:
        dead = [key for key, seen_at in self._seen.items() if now - seen_at >= self.ttl_seconds]
        for key in dead:
            del self._seen[key]

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
        except (OSError, json.JSONDecodeError):
            log.warning("dedupe store unreadable, starting empty")
            return
        if isinstance(raw, dict):
            self._seen = {str(k): float(v) for k, v in raw.items()}

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._seen)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)
