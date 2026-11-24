"""Yaml shape for wallets. Validation lives here so providers stay dumb."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from pinme.routing import ConfigError
from pinme.wallets.chains import EVM_CHAINS


WATCH_FLAGS = {"native_balance", "token_balance", "transfers"}


@dataclass(frozen=True)
class TokenSpec:
    symbol: str
    contract: str
    decimals: int
    min_change: Decimal


@dataclass(frozen=True)
class WebhookProviderSpec:
    name: str
    enabled: bool
    secret_env: str


@dataclass(frozen=True)
class WalletSpec:
    id: str
    label: str
    enabled: bool
    provider: str
    chain: str
    address: str
    watch: frozenset[str]
    min_change: Decimal
    tokens: tuple[TokenSpec, ...] = ()
    rpc_env: str = ""
    api_key_env: str = ""
    explorer_api_key_env: str = "ETHERSCAN_API_KEY"


@dataclass(frozen=True)
class WalletFile:
    poll_seconds: int
    wallets: tuple[WalletSpec, ...]
    webhooks: dict[str, WebhookProviderSpec] = field(default_factory=dict)


def _decimal(value: object, where: str, default: str = "0") -> Decimal:
    raw = default if value is None else str(value).strip()
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ConfigError(f"{where} must be a number, got {value!r}") from exc
    if parsed < 0:
        raise ConfigError(f"{where} cannot be negative")
    return parsed


def _token(item: object, where: str, fallback_min: Decimal) -> TokenSpec:
    if not isinstance(item, dict):
        raise ConfigError(f"{where} must be a mapping")
    symbol = str(item.get("symbol") or "").strip()
    contract = str(item.get("contract") or "").strip()
    if not symbol or not contract or "REPLACE" in contract:
        raise ConfigError(f"{where} needs a symbol and a contract address")
    try:
        decimals = int(item.get("decimals"))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{where}.decimals must be an integer") from exc
    return TokenSpec(
        symbol=symbol,
        contract=contract,
        decimals=decimals,
        min_change=_decimal(item.get("min_change"), f"{where}.min_change", str(fallback_min)),
    )


def load_wallet_file(path: Path) -> WalletFile:
    if not path.exists():
        raise ConfigError(f"missing wallets file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must be a mapping")
    try:
        poll_seconds = int(data.get("poll_seconds") or 60)
    except (TypeError, ValueError) as exc:
        raise ConfigError("poll_seconds must be an integer") from exc
    if poll_seconds < 15:
        raise ConfigError("poll_seconds must be at least 15 so we do not hammer RPCs")

    webhooks: dict[str, WebhookProviderSpec] = {}
    raw_hooks = data.get("webhook_providers") or {}
    if not isinstance(raw_hooks, dict):
        raise ConfigError("webhook_providers must be a mapping")
    for name, spec in raw_hooks.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"webhook_providers.{name} must be a mapping")
        webhooks[str(name)] = WebhookProviderSpec(
            name=str(name),
            enabled=bool(spec.get("enabled", False)),
            secret_env=str(spec.get("signing_key_env") or spec.get("secret_env") or ""),
        )

    wallets: list[WalletSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(data.get("wallets") or []):
        where = f"wallets[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{where} must be a mapping")
        wallet_id = str(item.get("id") or "").strip()
        if not wallet_id:
            raise ConfigError(f"{where} needs an id")
        if wallet_id in seen:
            raise ConfigError(f"duplicate wallet id {wallet_id!r}")
        seen.add(wallet_id)
        provider = str(item.get("provider") or "").strip().lower()
        chain = str(item.get("chain") or "").strip().lower()
        address = str(item.get("address") or "").strip()
        if provider not in {"evm", "tron"}:
            raise ConfigError(f"{where}.provider must be 'evm' or 'tron'")
        if provider == "evm" and chain not in EVM_CHAINS:
            known = ", ".join(sorted(EVM_CHAINS))
            raise ConfigError(f"{where}.chain {chain!r} is unknown. Known EVM chains: {known}")
        if provider == "tron" and chain != "tron":
            raise ConfigError(f"{where}.chain must be 'tron' when provider is tron")
        watch_raw = item.get("watch") or ["native_balance"]
        if not isinstance(watch_raw, list) or not watch_raw:
            raise ConfigError(f"{where}.watch must be a non-empty list")
        unknown = [flag for flag in watch_raw if flag not in WATCH_FLAGS]
        if unknown:
            raise ConfigError(f"{where}.watch has unknown flags: {unknown}")
        min_change = _decimal(item.get("min_change"), f"{where}.min_change", "0")
        tokens = tuple(
            _token(token, f"{where}.tokens[{i}]", min_change)
            for i, token in enumerate(item.get("tokens") or [])
        )
        wallets.append(
            WalletSpec(
                id=wallet_id,
                label=str(item.get("label") or wallet_id),
                enabled=bool(item.get("enabled", True)),
                provider=provider,
                chain=chain,
                address=address,
                watch=frozenset(str(flag) for flag in watch_raw),
                min_change=min_change,
                tokens=tokens,
                rpc_env=str(item.get("rpc_env") or "").strip(),
                api_key_env=str(item.get("api_key_env") or "TRONGRID_API_KEY").strip(),
                explorer_api_key_env=str(item.get("explorer_api_key_env") or "ETHERSCAN_API_KEY").strip(),
            )
        )
    return WalletFile(poll_seconds=poll_seconds, wallets=tuple(wallets), webhooks=webhooks)


def is_placeholder(address: str) -> bool:
    text = address.upper()
    return (not address) or ("REPLACE" in text) or address.startswith("0xREPLACE")
