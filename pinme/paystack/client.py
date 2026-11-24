"""Small REST client for the calls the bot makes on purpose.

Webhooks do not need this. Use it when you want to re-check a reference,
read the Paystack balance, or (if your integration is in the webhook
endpoints pilot) register a URL from code.

Auth header is always `Bearer <secret key>`.
Base URL defaults to https://api.paystack.co for both test and live.
Which mode you are in depends on whether the key is sk_test_ or sk_live_.
"""

from __future__ import annotations

import aiohttp


class PaystackClient:
    def __init__(self, secret_key: str, base_url: str = "https://api.paystack.co") -> None:
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.secret_key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.secret_key}", "Content-Type": "application/json"}

    async def get(self, path: str, session: aiohttp.ClientSession) -> dict:
        async with session.get(self.base_url + path, headers=self._headers(), timeout=20) as response:
            payload = await response.json(content_type=None)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Paystack {path} returned a non-object")
        return payload

    async def verify_transaction(self, reference: str, session: aiohttp.ClientSession) -> dict:
        return await self.get(f"/transaction/verify/{reference}", session)

    async def balance(self, session: aiohttp.ClientSession) -> dict:
        return await self.get("/balance", session)
