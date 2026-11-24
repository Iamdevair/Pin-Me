"""Unit tests for the pieces that must stay correct without Discord or the network."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from decimal import Decimal
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from Crypto.Hash import keccak

from pinme.core.alerts import Alert
from pinme.core.bus import EventBus
from pinme.core.dedupe import DedupeStore
from pinme.filters import SourceFilter
from pinme.http.server import HttpApp
from pinme.paystack.handlers import to_alert as paystack_alert
from pinme.paystack.signatures import verify_paystack
from pinme.routing import Route, RouteTable, resolve_channel
from pinme.shopify.handlers import to_alert as shopify_alert
from pinme.shopify.signatures import verify_shopify
from pinme.wallets.delta import balance_direction
from pinme.wallets.models import WalletFile, WalletSpec, load_wallet_file
from pinme.wallets.providers.evm import EvmProvider
from pinme.wallets.providers.inbound import alchemy_alerts, verify_alchemy, verify_moralis
from pinme.wallets.providers.tron import _trc20_map
from pinme.wallets.state import WalletState

ROOT = Path(__file__).resolve().parent.parent


def test_balance_direction_baselines_once_then_respects_dust():
    assert balance_direction(None, Decimal("1"), Decimal("0.01"), bootstrapped=False) is None
    assert balance_direction(Decimal("1"), Decimal("1.00001"), Decimal("0.001"), bootstrapped=True) is None
    assert balance_direction(Decimal("1"), Decimal("1.2"), Decimal("0.001"), bootstrapped=True) == "up"
    assert balance_direction(Decimal("5"), Decimal("4"), Decimal("0.5"), bootstrapped=True) == "down"


def test_evm_balance_helper_skips_baseline(tmp_path: Path):
    state = WalletState(tmp_path / "state.json")
    wallet = WalletSpec(
        id="main",
        label="Main",
        enabled=True,
        provider="evm",
        chain="ethereum",
        address="0xabc",
        watch=frozenset({"native_balance"}),
        min_change=Decimal("0.001"),
    )
    provider = EvmProvider()
    first = provider._balance_alerts(
        wallet, state, False, key="native", symbol="ETH",
        current=Decimal("2"), min_change=Decimal("0.001"),
    )
    assert first == []
    state.mark_bootstrapped(wallet.id)
    second = provider._balance_alerts(
        wallet, state, True, key="native", symbol="ETH",
        current=Decimal("2.5"), min_change=Decimal("0.001"),
    )
    assert second[0].event == "balance.up"
    assert "0.5 ETH" in second[0].title


def test_routes_prefer_exact_event_over_wildcard():
    table = RouteTable(
        default_channel_id=1,
        routes=(
            Route("paystack", "*", 20),
            Route("paystack", "charge.success", 30),
            Route("*", "*", 40),
        ),
    )
    assert resolve_channel(table, "paystack", "charge.success") == 30
    assert resolve_channel(table, "paystack", "transfer.failed") == 20
    assert resolve_channel(table, "shopify", "orders/paid") == 40
    assert resolve_channel(table, "wallets", "balance.up") == 40


def test_example_yaml_files_load():
    wallets = load_wallet_file(ROOT / "config" / "wallets.example.yaml")
    assert wallets.poll_seconds >= 15
    assert {wallet.id for wallet in wallets.wallets} == {"main-eth", "ops-tron"}
    assert wallets.wallets[0].enabled is False


def test_unknown_chain_is_a_config_error(tmp_path: Path):
    path = tmp_path / "wallets.yaml"
    path.write_text(
        "poll_seconds: 60\nwallets:\n  - id: x\n    provider: evm\n    chain: nostr\n    address: '0x1'\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="unknown"):
        load_wallet_file(path)


def test_paystack_legacy_and_v2_signatures():
    body = b'{"event":"charge.success","data":{"reference":"ref_1"}}'
    secret = "sk_test_example"
    legacy = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    assert verify_paystack(body, legacy_header=legacy, v2_header=None, secret_key=secret, webhook_secret="")
    assert not verify_paystack(body + b" ", legacy_header=legacy, v2_header=None, secret_key=secret, webhook_secret="")

    webhook_secret = "whsec_example"
    now = 1_700_000_000
    signed = str(now).encode() + b"." + body
    digest = hmac.new(webhook_secret.encode(), signed, hashlib.sha512).hexdigest()
    header = f"t={now},v1=whk_test:{digest}"
    assert verify_paystack(
        body, legacy_header=None, v2_header=header, secret_key="", webhook_secret=webhook_secret, now=now
    )
    assert not verify_paystack(
        body, legacy_header=None, v2_header=header, secret_key="", webhook_secret=webhook_secret, now=now + 10_000
    )


def test_shopify_signature_is_base64_hmac():
    body = b'{"id":1}'
    secret = "shpss_example"
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    import base64

    header = base64.b64encode(digest).decode()
    assert verify_shopify(body, header, secret)
    assert not verify_shopify(body, header, "other")


def test_paystack_amount_is_converted_from_kobo_and_filter_drops_unknown():
    allow = SourceFilter(enabled=True, allow=frozenset({"charge.success"}), include_customer_email=True)
    payload = {
        "event": "charge.success",
        "data": {
            "amount": 250000,
            "currency": "NGN",
            "reference": "ref_9",
            "channel": "card",
            "customer": {"email": "a@b.co"},
        },
    }
    alert = paystack_alert(payload, allow)
    assert alert is not None
    assert alert.fields["Amount"] == "NGN 2,500.00"
    assert alert.fields["Customer"] == "a@b.co"
    assert alert.dedupe_key == "paystack:charge.success:ref_9"
    assert paystack_alert({"event": "invoice.create", "data": {}}, allow) is None


def test_shopify_order_summary_hides_email_by_default():
    payload = {
        "id": 10,
        "name": "#1001",
        "currency": "NGN",
        "total_price": "15000.00",
        "financial_status": "paid",
        "email": "buyer@shop.test",
        "line_items": [{"title": "Beaded panel"}],
    }
    hidden = shopify_alert("orders/paid", payload, SourceFilter(True, frozenset({"orders/paid"})))
    assert hidden is not None
    assert "Customer" not in hidden.fields
    assert hidden.fields["Total"] == "NGN 15000.00"
    shown = shopify_alert(
        "orders/paid",
        payload,
        SourceFilter(True, frozenset({"orders/paid"}), include_customer_email=True),
    )
    assert shown.fields["Customer"] == "buyer@shop.test"
    assert shopify_alert("products/update", payload, SourceFilter(True, frozenset({"orders/paid"}))) is None


def test_dedupe_blocks_the_second_delivery(tmp_path: Path):
    store = DedupeStore(tmp_path / "dedupe.json", ttl_seconds=100)
    assert store.allow("paystack:charge.success:ref_1") is True
    assert store.allow("paystack:charge.success:ref_1") is False
    assert store.allow(None) is True
    reloaded = DedupeStore(tmp_path / "dedupe.json", ttl_seconds=100)
    assert reloaded.allow("paystack:charge.success:ref_1") is False


def test_trc20_map_and_alchemy_ignores_unlisted_addresses():
    parsed = _trc20_map([{"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": "5000000"}])
    assert parsed["TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"] == "5000000"
    wallet = WalletSpec(
        id="ops",
        label="Ops",
        enabled=True,
        provider="tron",
        chain="tron",
        address="TXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        watch=frozenset({"transfers"}),
        min_change=Decimal("1"),
    )
    wallet_file = WalletFile(poll_seconds=60, wallets=(wallet,))
    alerts = alchemy_alerts(
        {
            "event": {
                "network": "ETH_MAINNET",
                "activity": [
                    {"fromAddress": "0xother", "toAddress": "0xnope", "value": 1, "asset": "ETH", "hash": "0xabc"}
                ],
            }
        },
        wallet_file,
    )
    assert alerts == []


def test_alchemy_and_moralis_signatures():
    body = b'{"ok":true}'
    key = "alchemy-signing-key"
    header = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    assert verify_alchemy(body, header, key)
    secret = "streams-secret"
    digest = keccak.new(digest_bits=256)
    digest.update(body + secret.encode())
    assert verify_moralis(body, "0x" + digest.hexdigest(), secret)
    assert not verify_moralis(body, "0x" + digest.hexdigest(), "wrong")


def test_paystack_webhook_accepts_a_signed_body_and_rejects_a_forged_one(tmp_path: Path):
    body = json.dumps(
        {"event": "charge.success", "data": {"amount": 10000, "currency": "NGN", "reference": "ref_http"}}
    ).encode()
    secret = "sk_test_http"
    signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()

    class Settings:
        paystack_secret_key = secret
        paystack_webhook_secret = ""
        paystack_enforce_ip = False
        shopify_webhook_secret = "unused"
        alchemy_signing_key = ""
        moralis_streams_secret = ""

    received: list[Alert] = []

    async def collect(alert: Alert) -> None:
        received.append(alert)

    bus = EventBus()
    bus.subscribe(collect)
    app = HttpApp(
        settings=Settings(),  # type: ignore[arg-type]
        bus=bus,
        paystack_filter=SourceFilter(True, frozenset({"charge.success"})),
        shopify_filter=SourceFilter(True, frozenset()),
        wallet_file=WalletFile(60, ()),
        status={"bot_ready": False},
    ).build()

    async def scenario() -> None:
        async with TestClient(TestServer(app)) as client:
            bad = await client.post("/webhooks/paystack", data=body, headers={"x-paystack-signature": "nope"})
            assert bad.status == 401
            good = await client.post("/webhooks/paystack", data=body, headers={"x-paystack-signature": signature})
            assert good.status == 200
            health = await client.get("/health")
            payload = await health.json()
            assert payload["ok"] is True
            assert payload["last_paystack_event"] == "charge.success"

    asyncio.run(scenario())
    assert received[0].source == "paystack"
    assert received[0].fields["Reference"] == "ref_http"


def test_dedupe_ttl_expires(tmp_path: Path):
    store = DedupeStore(tmp_path / "dedupe.json", ttl_seconds=1)
    assert store.allow("k") is True
    store._seen["k"] = time.time() - 5
    assert store.allow("k") is True
