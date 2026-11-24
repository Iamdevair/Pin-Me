"""Provider contract. A new chain family implements poll() and nothing else."""

from __future__ import annotations

from typing import Protocol

import aiohttp

from pinme.core.alerts import Alert
from pinme.wallets.models import WalletSpec
from pinme.wallets.state import WalletState


class WalletProvider(Protocol):
    name: str

    async def poll(
        self,
        session: aiohttp.ClientSession,
        wallet: WalletSpec,
        state: WalletState,
    ) -> list[Alert]:
        """Return alerts since the last poll. Persist state only via WalletState."""
