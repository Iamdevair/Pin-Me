"""aiohttp routes.

Paystack and Shopify must get a 2xx quickly. Verification and a queue put
are all that happen on the request. The Discord send runs on the notifier task.
Bad signatures get 401. Events we chose not to watch still get 200 so the
provider does not retry them for hours.
"""

from __future__ import annotations

import json
import logging

from aiohttp import web

from pinme.config import Settings
from pinme.core.bus import EventBus
from pinme.filters import SourceFilter
from pinme.paystack.events import PAYSTACK_IPS
from pinme.paystack.handlers import to_alert as paystack_alert
from pinme.paystack.signatures import verify_paystack
from pinme.shopify.handlers import to_alert as shopify_alert
from pinme.shopify.signatures import verify_shopify
from pinme.wallets.models import WalletFile
from pinme.wallets.providers.inbound import (
    alchemy_alerts,
    moralis_alerts,
    verify_alchemy,
    verify_moralis,
)

log = logging.getLogger(__name__)


class HttpApp:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        paystack_filter: SourceFilter,
        shopify_filter: SourceFilter,
        wallet_file: WalletFile,
        status: dict,
    ) -> None:
        self.settings = settings
        self.bus = bus
        self.paystack_filter = paystack_filter
        self.shopify_filter = shopify_filter
        self.wallet_file = wallet_file
        self.status = status

    def build(self) -> web.Application:
        app = web.Application(client_max_size=2 * 1024 * 1024)
        app.router.add_get("/health", self.health)
        app.router.add_post("/webhooks/paystack", self.paystack)
        app.router.add_post("/webhooks/shopify", self.shopify)
        app.router.add_post("/webhooks/wallets/alchemy", self.alchemy)
        app.router.add_post("/webhooks/wallets/moralis", self.moralis)
        return app

    async def health(self, _request: web.Request) -> web.Response:
        public = {key: value for key, value in self.status.items() if key != "notifier"}
        return web.json_response({"ok": True, **public})

    async def paystack(self, request: web.Request) -> web.Response:
        raw = await request.read()
        if self.settings.paystack_enforce_ip and not _ip_allowed(request):
            log.warning("paystack webhook rejected: source ip not in allow list")
            return web.Response(status=401, text="ip")
        ok = verify_paystack(
            raw,
            legacy_header=request.headers.get("x-paystack-signature"),
            v2_header=request.headers.get("Paystack-Signature"),
            secret_key=self.settings.paystack_secret_key,
            webhook_secret=self.settings.paystack_webhook_secret,
        )
        if not ok:
            log.warning("paystack webhook rejected: bad signature")
            return web.Response(status=401, text="signature")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return web.Response(status=400, text="json")
        if not isinstance(payload, dict):
            return web.Response(status=400, text="json")
        alert = paystack_alert(payload, self.paystack_filter)
        if alert is not None:
            self.status["last_paystack_event"] = alert.event
            await self.bus.publish(alert)
        else:
            log.info("paystack event ignored: %s", payload.get("event"))
        return web.Response(status=200, text="ok")

    async def shopify(self, request: web.Request) -> web.Response:
        raw = await request.read()
        if not verify_shopify(raw, request.headers.get("X-Shopify-Hmac-Sha256"), self.settings.shopify_webhook_secret):
            log.warning("shopify webhook rejected: bad signature")
            return web.Response(status=401, text="signature")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return web.Response(status=400, text="json")
        if not isinstance(payload, dict):
            payload = {}
        topic = request.headers.get("X-Shopify-Topic", "")
        alert = shopify_alert(
            topic,
            payload,
            self.shopify_filter,
            webhook_id=request.headers.get("X-Shopify-Webhook-Id", ""),
            shop_domain=request.headers.get("X-Shopify-Shop-Domain", ""),
        )
        if alert is not None:
            self.status["last_shopify_event"] = topic
            await self.bus.publish(alert)
        else:
            log.info("shopify topic ignored: %s", topic)
        return web.Response(status=200, text="ok")

    async def alchemy(self, request: web.Request) -> web.Response:
        spec = self.wallet_file.webhooks.get("alchemy")
        if spec is None or not spec.enabled:
            return web.Response(status=404, text="disabled")
        raw = await request.read()
        if not verify_alchemy(raw, request.headers.get("X-Alchemy-Signature"), self.settings.alchemy_signing_key):
            return web.Response(status=401, text="signature")
        payload = _json_object(raw)
        if payload is None:
            return web.Response(status=400, text="json")
        for alert in alchemy_alerts(payload, self.wallet_file):
            await self.bus.publish(alert)
        return web.Response(status=200, text="ok")

    async def moralis(self, request: web.Request) -> web.Response:
        spec = self.wallet_file.webhooks.get("moralis")
        if spec is None or not spec.enabled:
            return web.Response(status=404, text="disabled")
        raw = await request.read()
        if not verify_moralis(raw, request.headers.get("x-signature"), self.settings.moralis_streams_secret):
            return web.Response(status=401, text="signature")
        payload = _json_object(raw)
        if payload is None:
            return web.Response(status=400, text="json")
        for alert in moralis_alerts(payload, self.wallet_file):
            await self.bus.publish(alert)
        return web.Response(status=200, text="ok")


def _json_object(raw: bytes) -> dict | None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _ip_allowed(request: web.Request) -> bool:
    # Direct connection only. Do not trust X-Forwarded-For unless you terminate
    # TLS yourself and strip client-supplied forwarding headers.
    peer = request.remote or ""
    return peer in PAYSTACK_IPS
