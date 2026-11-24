"""Alert → Discord embed. Change the look here, not in the source modules."""

from __future__ import annotations

import discord

from pinme.core.alerts import Alert

COLORS = {
    "info": 0x5865F2,
    "success": 0x57F287,
    "warning": 0xFEE75C,
    "critical": 0xED4245,
}


def alert_to_embed(alert: Alert) -> discord.Embed:
    embed = discord.Embed(
        title=alert.title,
        description=alert.body or None,
        color=COLORS.get(alert.severity, COLORS["info"]),
        timestamp=alert.created_at,
        url=alert.url,
    )
    for name, value in list(alert.fields.items())[:25]:
        embed.add_field(name=name, value=value or "—", inline=True)
    embed.set_footer(text=f"Pin Me · {alert.source} · {alert.event}")
    return embed
