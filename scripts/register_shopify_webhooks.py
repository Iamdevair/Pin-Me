"""Register one Shopify webhook subscription per topic in config/events.yaml.

Does not hardcode topics. Edit the yaml, then run:

    python scripts/register_shopify_webhooks.py

Requires SHOPIFY_SHOP, SHOPIFY_ADMIN_TOKEN, SHOPIFY_WEBHOOK_SECRET (the app
client secret, because these subscriptions are created by the app), and
PUBLIC_BASE_URL. The callback is {PUBLIC_BASE_URL}/webhooks/shopify.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pinme.config import load_settings
from pinme.filters import load_source_filter
from pinme.shopify.client import ShopifyClient
from pinme.shopify.events import graphql_topic


async def _main() -> int:
    settings = load_settings()
    source = load_source_filter(settings.events_file, "shopify")
    if not settings.public_base_url or "REPLACE" in settings.public_base_url:
        print("Set PUBLIC_BASE_URL to the HTTPS origin Shopify can reach.")
        return 2
    client = ShopifyClient(settings.shopify_shop, settings.shopify_admin_token, settings.shopify_api_version)
    if not client.configured:
        print("Set SHOPIFY_SHOP and SHOPIFY_ADMIN_TOKEN.")
        return 2
    if "*" in source.allow:
        print("Refusing to subscribe to every Shopify topic ('*'). List the topics you want.")
        return 2
    callback = settings.public_base_url + "/webhooks/shopify"
    async with aiohttp.ClientSession() as session:
        for topic in sorted(source.allow):
            enum_name = graphql_topic(topic)
            print(f"subscribing {topic} ({enum_name}) -> {callback}")
            payload = await client.register_webhook(enum_name, callback, session)
            result = ((payload.get("data") or {}).get("webhookSubscriptionCreate") or {})
            errors = result.get("userErrors") or []
            if errors:
                print(f"  error: {errors}")
            else:
                created = result.get("webhookSubscription") or {}
                print(f"  ok: {created.get('id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
