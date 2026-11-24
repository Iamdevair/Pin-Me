"""Optional push providers. Polling is the default and needs no paid stream.

Alchemy Address Activity and Moralis Streams both POST into this process.
Enable one in config/wallets.yaml (`webhook_providers`) and set its secret.
Only addresses listed in that same file are turned into alerts.

Moralis has documented two signing styles (raw body + secret, and
JSON.stringify(body) + secret), both keccak256, header `x-signature`.
We accept either. If their account signs with a different secret than the
one in MORALIS_STREAMS_SECRET, verification fails closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from Crypto.Hash import keccak

from pinme.core.alerts import Alert
from pinme.wallets.format import short_hash
from pinme.wallets.models import WalletFile, WalletSpec

log = logging.getLogger(__name__)


def _keccak_hex(data: bytes) -> str:
    digest = keccak.new(digest_bits=256)
    digest.update(data)
    return digest.hexdigest()


def verify_alchemy(raw: bytes, header: str | None, signing_key: str) -> bool:
    if not header or not signing_key:
        return False
    expected = hmac.new(signing_key.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip().lower())


def verify_moralis(raw: bytes, header: str | None, secret: str) -> bool:
    if not header or not secret:
        return False
    provided = header.strip().lower().removeprefix("0x")
    candidates = [raw + secret.encode()]
    try:
        parsed = json.loads(raw.decode("utf-8"))
        compact = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        candidates.append(compact + secret.encode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    for blob in candidates:
        if hmac.compare_digest(_keccak_hex(blob), provided):
            return True
    return False


def alchemy_alerts(payload: dict, wallet_file: WalletFile) -> list[Alert]:
    event = payload.get("event") or {}
    activity = event.get("activity") or []
    if not isinstance(activity, list):
        return []
    network = str(event.get("network") or "")
    alerts: list[Alert] = []
    for item in activity:
        if not isinstance(item, dict):
            continue
        wallet = _match_address(
            wallet_file,
            [str(item.get("fromAddress") or ""), str(item.get("toAddress") or "")],
        )
        if wallet is None:
            continue
        asset = str(item.get("asset") or "token")
        value = item.get("value")
        tx_hash = str(item.get("hash") or "")
        incoming = str(item.get("toAddress") or "").lower() == wallet.address.lower()
        alerts.append(
            Alert(
                source="wallets",
                event="transfer.in" if incoming else "transfer.out",
                title=f"{wallet.label} {'incoming' if incoming else 'outgoing'} {value} {asset}",
                body=f"Alchemy address activity on {network or wallet.chain}.",
                severity="success" if incoming else "warning",
                fields={
                    "Tx": short_hash(tx_hash, 8) if tx_hash else "n/a",
                    "From": str(item.get("fromAddress") or ""),
                    "To": str(item.get("toAddress") or ""),
                    "Asset": asset,
                    "Network": network or wallet.chain,
                },
                dedupe_key=f"alchemy:{tx_hash}:{item.get('fromAddress')}:{item.get('toAddress')}:{asset}:{value}",
            )
        )
    return alerts


def moralis_alerts(payload: dict, wallet_file: WalletFile) -> list[Alert]:
    """Turn confirmed ERC-20 transfers into alerts. Native txs use the same shape."""
    if payload.get("confirmed") is False:
        return []
    alerts: list[Alert] = []
    transfers = payload.get("erc20Transfers") or []
    if isinstance(transfers, list):
        for item in transfers:
            if isinstance(item, dict):
                alert = _moralis_transfer(item, wallet_file, kind="erc20")
                if alert:
                    alerts.append(alert)
    txs = payload.get("txs") or []
    if isinstance(txs, list):
        for item in txs:
            if isinstance(item, dict):
                alert = _moralis_transfer(item, wallet_file, kind="native")
                if alert:
                    alerts.append(alert)
    return alerts


def _moralis_transfer(item: dict, wallet_file: WalletFile, *, kind: str) -> Alert | None:
    from_addr = str(item.get("from") or item.get("fromAddress") or "")
    to_addr = str(item.get("to") or item.get("toAddress") or "")
    wallet = _match_address(wallet_file, [from_addr, to_addr])
    if wallet is None:
        return None
    incoming = to_addr.lower() == wallet.address.lower()
    symbol = str(item.get("tokenSymbol") or ("native" if kind == "native" else "token"))
    value = str(item.get("value") or item.get("valueWithDecimals") or item.get("valueDecimal") or "")
    tx_hash = str(item.get("transactionHash") or item.get("hash") or "")
    return Alert(
        source="wallets",
        event="transfer.in" if incoming else "transfer.out",
        title=f"{wallet.label} {'incoming' if incoming else 'outgoing'} {value} {symbol}".strip(),
        body="Moralis stream delivery.",
        severity="success" if incoming else "warning",
        fields={
            "Tx": short_hash(tx_hash, 8) if tx_hash else "n/a",
            "From": from_addr,
            "To": to_addr,
            "Asset": symbol,
            "Chain": str(payload_chain(item, wallet)),
        },
        dedupe_key=f"moralis:{tx_hash}:{from_addr}:{to_addr}:{symbol}:{value}",
    )


def payload_chain(item: dict, wallet: WalletSpec) -> str:
    return str(item.get("chain") or wallet.chain)


def _match_address(wallet_file: WalletFile, candidates: list[str]) -> WalletSpec | None:
    wanted = {item.lower() for item in candidates if item}
    for wallet in wallet_file.wallets:
        if not wallet.enabled:
            continue
        if wallet.address.lower() in wanted:
            return wallet
    return None
