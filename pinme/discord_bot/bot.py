"""Slash commands only. Message content intent stays off.

Invite URL (replace CLIENT_ID):
https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=84992&scope=bot%20applications.commands

Permissions integer 84992 = View Channels + Send Messages + Embed Links + Read Message History.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from pinme.wallets.service import WalletService

log = logging.getLogger(__name__)


class PinMeBot(commands.Bot):
    """Holds the pieces the slash commands need to read."""

    def __init__(self, *, guild_id: int | None, service: WalletService, status: dict) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.guild_id = guild_id
        self.service = service
        self.pinme_status = status
        self._register_commands()

    def _register_commands(self) -> None:
        group = app_commands.Group(name="pin", description="Pin Me controls")

        @group.command(name="status", description="Show whether Pin Me is alive")
        async def status_cmd(interaction: discord.Interaction) -> None:
            wallets = self.service.active_wallets()
            lines = [
                f"Bot: {'ready' if self.pinme_status.get('bot_ready') else 'starting'}",
                f"Wallets watched: {len(wallets)}",
                f"Last Paystack event: {self.pinme_status.get('last_paystack_event') or 'none yet'}",
                f"Last Shopify event: {self.pinme_status.get('last_shopify_event') or 'none yet'}",
                f"Last wallet error: {self.service.last_error or 'none'}",
            ]
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        @group.command(name="wallets", description="List wallets from the yaml file")
        async def wallets_cmd(interaction: discord.Interaction) -> None:
            rows = []
            for wallet in self.service.wallet_file.wallets:
                state = "on" if wallet.enabled else "off"
                rows.append(f"- `{wallet.id}` {state} · {wallet.chain} · {wallet.address}")
            text = "\n".join(rows) if rows else "No wallets in the yaml file."
            await interaction.response.send_message(text[:1900], ephemeral=True)

        @group.command(name="test", description="Post a test alert through the normal pipeline")
        async def test_cmd(interaction: discord.Interaction) -> None:
            from pinme.core.alerts import Alert

            await self.service.bus.publish(
                Alert(
                    source="wallets",
                    event="test",
                    title="Pin Me test alert",
                    body="If you can read this, routing and the Discord notifier work.",
                    severity="info",
                    fields={"Triggered by": str(interaction.user)},
                )
            )
            await interaction.response.send_message(
                "Queued a test alert. It lands in the channel mapped to wallets/test, or the default channel.",
                ephemeral=True,
            )

        self.tree.add_command(group)

    async def setup_hook(self) -> None:
        if self.guild_id:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("synced %s commands to guild %s", len(synced), self.guild_id)
        else:
            synced = await self.tree.sync()
            log.info("synced %s global commands (can take up to an hour to appear)", len(synced))

    async def on_ready(self) -> None:
        self.pinme_status["bot_ready"] = True
        notifier = self.pinme_status.get("notifier")
        if notifier is not None:
            notifier.ready.set()
        log.info("discord ready as %s", self.user)
