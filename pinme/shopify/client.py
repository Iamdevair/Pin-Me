"""Admin API helper used by scripts/register_shopify_webhooks.py.

Token header: X-Shopify-Access-Token: shpca_... / shpat_...
GraphQL endpoint:
    POST https://{shop}/admin/api/{version}/graphql.json

Webhook subscriptions created here are signed with the app client secret.
That secret must be SHOPIFY_WEBHOOK_SECRET or verification will fail.
"""

from __future__ import annotations

import aiohttp

CREATE_WEBHOOK = """
mutation webhookSubscriptionCreate($topic: WebhookSubscriptionTopic!, $webhookSubscription: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $webhookSubscription) {
    webhookSubscription { id topic uri }
    userErrors { field message }
  }
}
"""


class ShopifyClient:
    def __init__(self, shop: str, token: str, api_version: str) -> None:
        self.shop = shop.replace("https://", "").strip().strip("/")
        self.token = token
        self.api_version = api_version

    @property
    def configured(self) -> bool:
        return bool(self.shop and self.token and "your-store" not in self.shop)

    def _headers(self) -> dict[str, str]:
        return {"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"}

    def _graphql_url(self) -> str:
        return f"https://{self.shop}/admin/api/{self.api_version}/graphql.json"

    async def graphql(self, query: str, variables: dict, session: aiohttp.ClientSession) -> dict:
        async with session.post(
            self._graphql_url(),
            headers=self._headers(),
            json={"query": query, "variables": variables},
            timeout=30,
        ) as response:
            payload = await response.json(content_type=None)
        if response.status >= 400:
            raise RuntimeError(f"Shopify GraphQL HTTP {response.status}: {payload}")
        if not isinstance(payload, dict):
            raise RuntimeError("Shopify GraphQL returned a non-object")
        if payload.get("errors"):
            raise RuntimeError(f"Shopify GraphQL errors: {payload['errors']}")
        return payload

    async def register_webhook(self, topic_enum: str, callback_url: str, session: aiohttp.ClientSession) -> dict:
        return await self.graphql(
            CREATE_WEBHOOK,
            {
                "topic": topic_enum,
                "webhookSubscription": {"uri": callback_url, "format": "JSON"},
            },
            session,
        )
