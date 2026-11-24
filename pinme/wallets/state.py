"""Last-seen balances and transaction ids, stored as JSON on disk.

The first observation is a baseline. Later observations diff against it.
Losing this file makes the next poll a new baseline (no historical replay).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

MAX_SEEN_TXS = 200


class WalletState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict = {"wallets": {}}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("wallets"), dict):
                    self._data = loaded
            except (OSError, json.JSONDecodeError):
                log.warning("wallet state unreadable, starting fresh")

    def wallet(self, wallet_id: str) -> dict:
        wallets = self._data.setdefault("wallets", {})
        slot = wallets.setdefault(wallet_id, {"balances": {}, "seen_txs": [], "bootstrapped": False})
        slot.setdefault("balances", {})
        slot.setdefault("seen_txs", [])
        slot.setdefault("bootstrapped", False)
        return slot

    def balance(self, wallet_id: str, key: str) -> str | None:
        value = self.wallet(wallet_id)["balances"].get(key)
        return None if value is None else str(value)

    def set_balance(self, wallet_id: str, key: str, value: str) -> None:
        self.wallet(wallet_id)["balances"][key] = value

    def mark_bootstrapped(self, wallet_id: str) -> None:
        self.wallet(wallet_id)["bootstrapped"] = True

    def is_bootstrapped(self, wallet_id: str) -> bool:
        return bool(self.wallet(wallet_id)["bootstrapped"])

    def seen(self, wallet_id: str, tx_id: str) -> bool:
        return tx_id in self.wallet(wallet_id)["seen_txs"]

    def remember(self, wallet_id: str, tx_id: str) -> None:
        txs: list[str] = self.wallet(wallet_id)["seen_txs"]
        txs.append(tx_id)
        if len(txs) > MAX_SEEN_TXS:
            del txs[: len(txs) - MAX_SEEN_TXS]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
