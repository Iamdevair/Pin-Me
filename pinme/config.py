"""Environment variables and the three yaml files.

Secrets come from the environment. Everything a second developer is expected
to change (wallets, events, channels) comes from config/*.yaml.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from pinme.routing import ConfigError, RouteTable, load_routes

ROOT = Path(__file__).resolve().parent.parent


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: str) -> Path:
    raw = os.getenv(name, default)
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str
    discord_guild_id: int | None
    host: str
    port: int
    log_level: str
    public_base_url: str
    state_dir: Path
    wallets_file: Path
    routes_file: Path
    events_file: Path
    paystack_secret_key: str
    paystack_public_key: str
    paystack_webhook_secret: str
    paystack_enforce_ip: bool
    paystack_base_url: str
    shopify_shop: str
    shopify_admin_token: str
    shopify_webhook_secret: str
    shopify_api_version: str
    etherscan_api_key: str
    trongrid_api_key: str
    trongrid_base_url: str
    alchemy_signing_key: str
    moralis_streams_secret: str

    @property
    def routes(self) -> RouteTable:
        return load_routes(self.routes_file)


def _example_or_real(real: Path) -> Path:
    """Use the example file until the operator copies it, so a fresh clone boots."""
    if real.exists():
        return real
    example = real.with_name(real.name.replace(".yaml", ".example.yaml"))
    if real.name.endswith(".yaml") and example.exists():
        return example
    return real


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    guild_raw = os.getenv("DISCORD_GUILD_ID", "").strip()
    guild_id: int | None = None
    if guild_raw:
        if not guild_raw.isdigit():
            raise ConfigError("DISCORD_GUILD_ID must be a numeric server id")
        guild_id = int(guild_raw)
    try:
        port = int(os.getenv("PORT", "8080"))
    except ValueError as exc:
        raise ConfigError("PORT must be an integer") from exc

    wallets = _example_or_real(_path("PINME_WALLETS_FILE", "config/wallets.yaml"))
    routes = _example_or_real(_path("PINME_ROUTES_FILE", "config/routes.yaml"))
    events = _example_or_real(_path("PINME_EVENTS_FILE", "config/events.yaml"))

    return Settings(
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", "").strip(),
        discord_guild_id=guild_id,
        host=os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0",
        port=port,
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        public_base_url=os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/"),
        state_dir=_path("STATE_DIR", "data"),
        wallets_file=wallets,
        routes_file=routes,
        events_file=events,
        paystack_secret_key=os.getenv("PAYSTACK_SECRET_KEY", "").strip(),
        paystack_public_key=os.getenv("PAYSTACK_PUBLIC_KEY", "").strip(),
        paystack_webhook_secret=os.getenv("PAYSTACK_WEBHOOK_SECRET", "").strip(),
        paystack_enforce_ip=_flag("PAYSTACK_ENFORCE_IP", False),
        paystack_base_url=os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co").rstrip("/"),
        shopify_shop=os.getenv("SHOPIFY_SHOP", "").strip(),
        shopify_admin_token=os.getenv("SHOPIFY_ADMIN_TOKEN", "").strip(),
        shopify_webhook_secret=os.getenv("SHOPIFY_WEBHOOK_SECRET", "").strip(),
        shopify_api_version=os.getenv("SHOPIFY_API_VERSION", "2026-10").strip(),
        etherscan_api_key=os.getenv("ETHERSCAN_API_KEY", "").strip(),
        trongrid_api_key=os.getenv("TRONGRID_API_KEY", "").strip(),
        trongrid_base_url=os.getenv("TRONGRID_BASE_URL", "https://api.trongrid.io").rstrip("/"),
        alchemy_signing_key=os.getenv("ALCHEMY_WEBHOOK_SIGNING_KEY", "").strip(),
        moralis_streams_secret=os.getenv("MORALIS_STREAMS_SECRET", "").strip(),
    )


def check_settings(settings: Settings, *, strict: bool = False) -> list[str]:
    """Return human-readable warnings. Raise ConfigError when the files are broken."""
    warnings: list[str] = []
    # Touch the route table so a bad yaml fails here, not after Discord connects.
    table = settings.routes
    if table.default_channel_id is None and not table.routes:
        warnings.append("no Discord channel ids configured in the routes file")
    if not settings.discord_bot_token:
        warnings.append("DISCORD_BOT_TOKEN is empty — the bot cannot log in")
    if not settings.public_base_url or "REPLACE" in settings.public_base_url:
        warnings.append("PUBLIC_BASE_URL is not a real HTTPS origin yet")
    if "example" in settings.wallets_file.name:
        warnings.append(f"using {settings.wallets_file.name} — copy it to config/wallets.yaml")
    if "example" in settings.routes_file.name:
        warnings.append(f"using {settings.routes_file.name} — copy it to config/routes.yaml")
    if "example" in settings.events_file.name:
        warnings.append(f"using {settings.events_file.name} — copy it to config/events.yaml")
    if strict and warnings:
        raise ConfigError("strict check failed:\n- " + "\n- ".join(warnings))
    return warnings
