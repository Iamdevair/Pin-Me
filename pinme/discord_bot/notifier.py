"""Subscribe to the bus and post embeds. A short queue absorbs webhook bursts.

Discord's per-channel limit is roughly five messages in five seconds.
We space sends by 0.4s, which is enough for a single store and a few wallets.
"""

from __future__ import annotations

import asyncio
import logging

import discord

from pinme.core.alerts import Alert
from pinme.discord_bot.embeds import alert_to_embed
from pinme.routing import RouteTable, resolve_channel

log = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, bot: discord.Client, routes: RouteTable, dedupe) -> None:
        self.bot = bot
        self.routes = routes
        self.dedupe = dedupe
        self.queue: asyncio.Queue[Alert] = asyncio.Queue()
        self.ready = asyncio.Event()
        self.last_error: str | None = None

    async def handle(self, alert: Alert) -> None:
        if not self.dedupe.allow(alert.dedupe_key):
            log.info("deduped %s %s", alert.source, alert.dedupe_key)
            return
        await self.queue.put(alert)

    async def run(self) -> None:
        await self.ready.wait()
        while True:
            alert = await self.queue.get()
            try:
                await self._send(alert)
            except Exception as exc:
                self.last_error = str(exc)
                log.exception("failed to deliver %s %s", alert.source, alert.event)
            finally:
                self.queue.task_done()
            await asyncio.sleep(0.4)

    async def _send(self, alert: Alert) -> None:
        channel_id = resolve_channel(self.routes, alert.source, alert.event)
        if channel_id is None:
            log.warning("no channel for %s %s", alert.source, alert.event)
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError(f"channel {channel_id} cannot receive messages")
        await channel.send(embed=alert_to_embed(alert))
