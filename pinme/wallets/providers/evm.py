"""EVM balances over JSON-RPC, plus optional Etherscan-style transfer history.

Swap the RPC by changing the env var named in the wallet's rpc_env.
The address, the chain, and the token list stay in config/wallets.yaml.
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal

import aiohttp

from pinme.core.alerts import Alert
from pinme.wallets.chains import EVM_CHAINS, EvmChain
from pinme.wallets.delta import balance_direction
from pinme.wallets.format import format_amount, from_units, short_hash
from pinme.wallets.models import TokenSpec, WalletSpec
from pinme.wallets.state import WalletState

log = logging.getLogger(__name__)

BALANCE_OF = "70a08231"


class EvmProvider:
    name = "evm"

    def __init__(self, explorer_api_key: str = "") -> None:
        self.explorer_api_key = explorer_api_key

    async def poll(
        self,
        session: aiohttp.ClientSession,
        wallet: WalletSpec,
        state: WalletState,
    ) -> list[Alert]:
        chain = EVM_CHAINS[wallet.chain]
        rpc_url = os.getenv(wallet.rpc_env, "").strip() if wallet.rpc_env else ""
        if not rpc_url:
            raise RuntimeError(
                f"wallet {wallet.id} needs {wallet.rpc_env or 'an rpc_env'} set in the environment"
            )
        alerts: list[Alert] = []
        bootstrapped = state.is_bootstrapped(wallet.id)
        if "native_balance" in wallet.watch:
            alerts.extend(await self._native(session, rpc_url, wallet, chain, state, bootstrapped))
        if "token_balance" in wallet.watch:
            for token in wallet.tokens:
                alerts.extend(
                    await self._token(session, rpc_url, wallet, chain, token, state, bootstrapped)
                )
        if "transfers" in wallet.watch:
            api_key = os.getenv(wallet.explorer_api_key_env, "").strip() or self.explorer_api_key
            if not api_key:
                log.info("wallet %s watches transfers but %s is empty", wallet.id, wallet.explorer_api_key_env)
            else:
                alerts.extend(await self._transfers(session, wallet, chain, api_key, state, bootstrapped))
        state.mark_bootstrapped(wallet.id)
        return alerts

    async def _native(self, session, rpc_url, wallet, chain, state, bootstrapped) -> list[Alert]:
        raw = await self._rpc(session, rpc_url, "eth_getBalance", [wallet.address, "latest"])
        current = from_units(int(raw, 16), chain.decimals)
        return self._balance_alerts(
            wallet, state, bootstrapped, key="native", symbol=chain.symbol,
            current=current, min_change=wallet.min_change,
        )

    async def _token(self, session, rpc_url, wallet, chain, token: TokenSpec, state, bootstrapped) -> list[Alert]:
        data = "0x" + BALANCE_OF + wallet.address.lower().removeprefix("0x").rjust(64, "0")
        raw = await self._rpc(
            session, rpc_url, "eth_call", [{"to": token.contract, "data": data}, "latest"]
        )
        if raw in (None, "0x"):
            amount = 0
        else:
            amount = int(raw, 16)
        current = from_units(amount, token.decimals)
        return self._balance_alerts(
            wallet, state, bootstrapped, key=f"token:{token.symbol}", symbol=token.symbol,
            current=current, min_change=token.min_change,
        )

    def _balance_alerts(
        self, wallet, state, bootstrapped, *, key, symbol, current: Decimal, min_change: Decimal,
    ) -> list[Alert]:
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
                    "Chain": wallet.chain,
                },
                dedupe_key=f"wallet:{wallet.id}:{key}:{format_amount(current, 8)}",
            )
        ]

    async def _transfers(self, session, wallet, chain: EvmChain, api_key: str, state, bootstrapped) -> list[Alert]:
        params = {
            "module": "account",
            "action": "txlist",
            "address": wallet.address,
            "startblock": 0,
            "endblock": 99999999,
            "page": 1,
            "offset": 20,
            "sort": "desc",
            "apikey": api_key,
        }
        if chain.explorer_style == "etherscan_v2":
            params["chainid"] = chain.chain_id
        async with session.get(chain.explorer_base, params=params, timeout=20) as response:
            payload = await response.json(content_type=None)
        rows = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            message = payload.get("message") if isinstance(payload, dict) else "no result"
            raise RuntimeError(f"explorer error for {wallet.id}: {message}")
        alerts: list[Alert] = []
        # Newest first. Record without alerting until the baseline poll is done.
        fresh = []
        for row in rows:
            tx_hash = str(row.get("hash") or "")
            if not tx_hash or state.seen(wallet.id, tx_hash):
                continue
            fresh.append(row)
        for row in reversed(fresh):
            tx_hash = str(row["hash"])
            state.remember(wallet.id, tx_hash)
            if not bootstrapped:
                continue
            alerts.append(self._transfer_alert(wallet, chain, row))
        return alerts

    def _transfer_alert(self, wallet: WalletSpec, chain: EvmChain, row: dict) -> Alert:
        tx_hash = str(row.get("hash") or "")
        value = from_units(int(row.get("value") or 0), chain.decimals)
        incoming = str(row.get("to") or "").lower() == wallet.address.lower()
        direction = "in" if incoming else "out"
        counterparty = str(row.get("from") if incoming else row.get("to") or "")
        failed = str(row.get("isError") or "0") == "1"
        return Alert(
            source="wallets",
            event=f"transfer.{direction}",
            title=f"{wallet.label} {'incoming' if incoming else 'outgoing'} {format_amount(value)} {chain.symbol}",
            body="Explorer saw a new transaction.",
            severity="critical" if failed else ("success" if incoming else "warning"),
            fields={
                "Tx": short_hash(tx_hash, 8),
                "Counterparty": counterparty,
                "Amount": f"{format_amount(value)} {chain.symbol}",
                "Status": "failed" if failed else "success",
                "Chain": wallet.chain,
            },
            dedupe_key=f"wallet:{wallet.id}:tx:{tx_hash}",
            url=_explorer_tx(wallet.chain, tx_hash),
        )

    async def _rpc(self, session, url: str, method: str, params: list) -> str:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with session.post(url, json=body, timeout=20) as response:
            payload = await response.json(content_type=None)
        if not isinstance(payload, dict):
            raise RuntimeError(f"RPC {method} returned a non-object")
        if payload.get("error"):
            raise RuntimeError(f"RPC {method} error: {payload['error']}")
        result = payload.get("result")
        if not isinstance(result, str):
            raise RuntimeError(f"RPC {method} missing result")
        return result


def chain_line(wallet: WalletSpec) -> str:
    return f"{wallet.label} on {wallet.chain}"


def _explorer_tx(chain: str, tx_hash: str) -> str | None:
    hosts = {
        "ethereum": "https://etherscan.io/tx/",
        "base": "https://basescan.org/tx/",
        "polygon": "https://polygonscan.com/tx/",
        "bsc": "https://bscscan.com/tx/",
        "arbitrum": "https://arbiscan.io/tx/",
        "optimism": "https://optimistic.etherscan.io/tx/",
        "celo": "https://celoscan.io/tx/",
    }
    prefix = hosts.get(chain)
    if not prefix or not tx_hash:
        return None
    return prefix + tx_hash
