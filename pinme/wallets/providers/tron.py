"""TRON balances and TRC-20 transfers via TronGrid.

Account balance is in sun (1 TRX = 1_000_000 sun). TRC-20 balances come back
as integer strings. The API key is the TRON-PRO-API-KEY header, named by
api_key_env on the wallet so you can point one wallet at a different key.
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal

import aiohttp

from pinme.core.alerts import Alert
from pinme.wallets.delta import balance_direction
from pinme.wallets.format import format_amount, from_units, short_hash
from pinme.wallets.models import WalletSpec
from pinme.wallets.providers.evm import chain_line
from pinme.wallets.state import WalletState

log = logging.getLogger(__name__)

SUN = 6


class TronProvider:
    name = "tron"

    def __init__(self, base_url: str, default_api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.default_api_key = default_api_key

    async def poll(
        self,
        session: aiohttp.ClientSession,
        wallet: WalletSpec,
        state: WalletState,
    ) -> list[Alert]:
        api_key = os.getenv(wallet.api_key_env, "").strip() or self.default_api_key
        headers = {"TRON-PRO-API-KEY": api_key} if api_key else {}
        account = await self._get(session, f"/v1/accounts/{wallet.address}", headers=headers)
        rows = account.get("data") if isinstance(account, dict) else None
        row = rows[0] if isinstance(rows, list) and rows else {}
        alerts: list[Alert] = []
        bootstrapped = state.is_bootstrapped(wallet.id)
        if "native_balance" in wallet.watch:
            sun = int(row.get("balance") or 0)
            alerts.extend(
                self._balance(
                    wallet, state, bootstrapped, key="native", symbol="TRX",
                    current=from_units(sun, SUN), min_change=wallet.min_change,
                )
            )
        if "token_balance" in wallet.watch:
            balances = _trc20_map(row.get("trc20"))
            for token in wallet.tokens:
                raw = int(balances.get(token.contract, "0") or 0)
                alerts.extend(
                    self._balance(
                        wallet, state, bootstrapped, key=f"token:{token.symbol}",
                        symbol=token.symbol, current=from_units(raw, token.decimals),
                        min_change=token.min_change,
                    )
                )
        if "transfers" in wallet.watch:
            alerts.extend(await self._transfers(session, wallet, state, bootstrapped, headers))
        state.mark_bootstrapped(wallet.id)
        return alerts

    def _balance(self, wallet, state, bootstrapped, *, key, symbol, current: Decimal, min_change) -> list[Alert]:
        previous_raw = state.balance(wallet.id, key)
        previous = Decimal(previous_raw) if previous_raw is not None else None
        state.set_balance(wallet.id, key, format(current, "f"))
        direction = balance_direction(previous, current, min_change, bootstrapped=bootstrapped)
        if direction is None or previous is None:
            return []
        delta = current - previous
        verb = "received" if direction == "up" else "sent"
        signed = format_amount(delta.copy_abs())
        return [
            Alert(
                source="wallets",
                event=f"balance.{direction}",
                title=f"{wallet.label} {verb} {signed} {symbol}",
                body=f"{chain_line(wallet)} balance is now {format_amount(current)} {symbol}.",
                severity="success" if direction == "up" else "warning",
                fields={
                    "Wallet": wallet.address,
                    "Change": f"{'+' if direction == 'up' else '-'}{signed} {symbol}",
                    "Balance": f"{format_amount(current)} {symbol}",
                    "Chain": "tron",
                },
                dedupe_key=f"wallet:{wallet.id}:{key}:{format_amount(current, 8)}",
            )
        ]

    async def _transfers(self, session, wallet, state, bootstrapped, headers) -> list[Alert]:
        payload = await self._get(
            session,
            f"/v1/accounts/{wallet.address}/transactions/trc20",
            params={"limit": 20, "only_confirmed": "true"},
            headers=headers,
        )
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        watched = {token.contract: token for token in wallet.tokens}
        alerts: list[Alert] = []
        fresh = []
        for row in rows:
            tx_id = str(row.get("transaction_id") or "")
            if not tx_id or state.seen(wallet.id, tx_id):
                continue
            fresh.append(row)
        for row in reversed(fresh):
            tx_id = str(row["transaction_id"])
            state.remember(wallet.id, tx_id)
            if not bootstrapped:
                continue
            token_info = row.get("token_info") or {}
            contract = str(token_info.get("address") or "")
            if watched and contract not in watched:
                continue
            token = watched.get(contract)
            decimals = token.decimals if token else int(token_info.get("decimals") or 0)
            symbol = token.symbol if token else str(token_info.get("symbol") or "TRC20")
            try:
                amount = from_units(int(row.get("value") or 0), decimals)
            except (TypeError, ValueError):
                continue
            incoming = str(row.get("to") or "") == wallet.address
            alerts.append(
                Alert(
                    source="wallets",
                    event="transfer.in" if incoming else "transfer.out",
                    title=f"{wallet.label} {'incoming' if incoming else 'outgoing'} {format_amount(amount)} {symbol}",
                    body="TronGrid saw a new TRC-20 transfer.",
                    severity="success" if incoming else "warning",
                    fields={
                        "Tx": short_hash(tx_id, 8),
                        "Counterparty": str(row.get("from") if incoming else row.get("to") or ""),
                        "Amount": f"{format_amount(amount)} {symbol}",
                        "Chain": "tron",
                    },
                    dedupe_key=f"wallet:{wallet.id}:tx:{tx_id}",
                    url=f"https://tronscan.org/#/transaction/{tx_id}",
                )
            )
        return alerts

    async def _get(self, session, path: str, params: dict | None = None, headers: dict | None = None) -> dict:
        async with session.get(self.base_url + path, params=params, headers=headers, timeout=20) as response:
            payload = await response.json(content_type=None)
        if response.status >= 400:
            raise RuntimeError(f"TronGrid {path} returned HTTP {response.status}")
        if not isinstance(payload, dict):
            raise RuntimeError(f"TronGrid {path} returned a non-object")
        return payload


def _trc20_map(raw: object) -> dict[str, str]:
    """TronGrid returns a list of single-key objects: [{contract: balance}, ...]."""
    found: dict[str, str] = {}
    if not isinstance(raw, list):
        return found
    for item in raw:
        if isinstance(item, dict):
            for contract, balance in item.items():
                found[str(contract)] = str(balance)
    return found
