"""Wire the modules together and run one process.

The process holds:
- the Discord gateway (outbound alerts + slash commands)
- an HTTP server (Paystack, Shopify, optional wallet streams, /health)
- the wallet poll loop
"""

from __future__ import annotations

import asyncio
import logging
import signal

from aiohttp import web

from pinme.config import Settings, load_settings
from pinme.core.bus import EventBus
from pinme.core.dedupe import DedupeStore
from pinme.discord_bot.bot import PinMeBot
from pinme.discord_bot.notifier import DiscordNotifier
from pinme.filters import load_source_filter
from pinme.http.server import HttpApp
from pinme.wallets.service import WalletService

log = logging.getLogger(__name__)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # discord.py is chatty at INFO when reconnecting.
    logging.getLogger("discord").setLevel(logging.WARNING)


async def run(settings: Settings) -> None:
    configure_logging(settings.log_level)
    bus = EventBus()
    service = WalletService(settings, bus)
    paystack_filter = load_source_filter(settings.events_file, "paystack")
    shopify_filter = load_source_filter(settings.events_file, "shopify")
    status: dict = {
        "bot_ready": False,
        "wallets": len(service.active_wallets()),
        "last_paystack_event": None,
        "last_shopify_event": None,
    }
    bot = PinMeBot(guild_id=settings.discord_guild_id, service=service, status=status)
    notifier = DiscordNotifier(
        bot,
        settings.routes,
        DedupeStore(settings.state_dir / "dedupe.json"),
    )
    status["notifier"] = notifier
    bus.subscribe(notifier.handle)

    http = HttpApp(
        settings=settings,
        bus=bus,
        paystack_filter=paystack_filter,
        shopify_filter=shopify_filter,
        wallet_file=service.wallet_file,
        status=status,
    )
    runner = web.AppRunner(http.build())
    await runner.setup()
    site = web.TCPSite(runner, host=settings.host, port=settings.port)
    await site.start()
    log.info("http listening on %s:%s", settings.host, settings.port)
    log.info("paystack webhook path: %s/webhooks/paystack", settings.public_base_url or f"http://{settings.host}:{settings.port}")
    log.info("shopify webhook path: %s/webhooks/shopify", settings.public_base_url or f"http://{settings.host}:{settings.port}")

    poller = asyncio.create_task(service.run(), name="wallet-poller")
    sender = asyncio.create_task(notifier.run(), name="discord-notifier")

    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        log.info("shutdown requested")
        asyncio.create_task(bot.close())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass

    try:
        await bot.start(settings.discord_bot_token)
    finally:
        poller.cancel()
        sender.cancel()
        for task in (poller, sender):
            try:
                await task
            except asyncio.CancelledError:
                pass
        if not bot.is_closed():
            await bot.close()
        await runner.cleanup()


def main(argv: list[str] | None = None) -> None:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    settings = load_settings()
    if "--check-config" in args:
        from pinme.config import check_settings
        from pinme.routing import ConfigError

        strict = "--strict" in args
        try:
            warnings = check_settings(settings, strict=strict)
        except ConfigError as exc:
            print(f"config error: {exc}")
            raise SystemExit(2) from exc
        # Importing the wallet file surfaces yaml errors the same way.
        try:
            WalletService(settings, EventBus())
            load_source_filter(settings.events_file, "paystack")
            load_source_filter(settings.events_file, "shopify")
        except ConfigError as exc:
            print(f"config error: {exc}")
            raise SystemExit(2) from exc
        if warnings:
            print("warnings:")
            for warning in warnings:
                print(f"- {warning}")
        else:
            print("config ok")
        raise SystemExit(0)

    if not settings.discord_bot_token:
        print("DISCORD_BOT_TOKEN is empty. Copy .env.example to .env and set it.")
        print("Run `python -m pinme --check-config` to validate the yaml without logging in.")
        raise SystemExit(2)
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        pass
