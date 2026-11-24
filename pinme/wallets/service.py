"""Poll loop. One place starts every wallet provider.

Adding a provider is a new class plus one line in PROVIDERS.
The loop isolates failures: one bad RPC does not stop the other wallets,
and the same error will not spam Discord on every tick (dedupe key).
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from pinme.config import Settings
from pinme.core.alerts import Alert
from pinme.core.bus import EventBus
from pinme.wallets.models import WalletFile, WalletSpec, is_placeholder, load_wallet_file
from pinme.wallets.providers.evm import EvmProvider
from pinme.wallets.providers.tron import TronProvider
from pinme.wallets.state import WalletState

log = logging.getLogger(__name__)


class WalletService:
    def __init__(self, settings: Settings, bus: EventBus) -> None:
        self.settings = settings
        self.bus = bus
        self.wallet_file: WalletFile = load_wallet_file(settings.wallets_file)
        self.state = WalletState(settings.state_dir / "wallet_state.json")
        self.evm = EvmProvider(explorer_api_key=settings.etherscan_api_key)
        self.tron = TronProvider(settings.trongrid_base_url, settings.trongrid_api_key)
        self.last_error: str | None = None

    def active_wallets(self) -> list[WalletSpec]:
        return [
            wallet
            for wallet in self.wallet_file.wallets
            if wallet.enabled and not is_placeholder(wallet.address)
        ]

    def _provider(self, wallet: WalletSpec):
        if wallet.provider == "evm":
            return self.evm
        if wallet.provider == "tron":
            return self.tron
        raise RuntimeError(f"no provider registered for {wallet.provider}")

    async def poll_once(self, session: aiohttp.ClientSession) -> int:
        sent = 0
        for wallet in self.active_wallets():
            try:
                alerts = await self._provider(wallet).poll(session, wallet, self.state)
            except Exception as exc:
                self.last_error = f"{wallet.id}: {exc}"
                log.exception("wallet poll failed for %s", wallet.id)
                alerts = [
                    Alert(
                        source="wallets",
                        event="poll.failed",
                        title=f"{wallet.label} poll failed",
                        body="The watcher could not read this wallet. The next tick will retry.",
                        severity="critical",
                        fields={"Wallet": wallet.id, "Error": str(exc)[:300]},
                        dedupe_key=f"wallet:{wallet.id}:poll-failed:{type(exc).__name__}",
                    )
                ]
            for alert in alerts:
                await self.bus.publish(alert)
                sent += 1
        self.state.save()
        return sent

    async def run(self) -> None:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                if self.active_wallets():
                    await self.poll_once(session)
                else:
                    log.info("no enabled wallets with real addresses — sleeping")
                await asyncio.sleep(self.wallet_file.poll_seconds)
