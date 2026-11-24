# Pin Me

Pin Me is a Python Discord bot that posts alerts into one server when:

- a wallet you list changes balance, or a new transfer shows up
- Paystack sends a charge, transfer, refund, invoice, or subscription event
- Shopify sends an order, refund, or fulfillment event

Each source is its own package. Discord only knows about one object, `Alert`. A second person can change wallets, events, and channels without reading the Discord code, and can add a chain or a new source without rewriting the others.

This repository is the build scaffold: the module boundaries, the config files, the verifiers, and the milestones. It does not ship with your keys.

## Map

| You want to… | Touch only |
| --- | --- |
| Add, remove, or pause a wallet | [`config/wallets.yaml`](config/wallets.example.yaml) |
| Change how often wallets are polled | `poll_seconds` in that same file |
| Watch an ERC-20 or TRC-20 | `tokens:` under that wallet |
| Add another EVM chain that speaks JSON-RPC | [`pinme/wallets/chains.py`](pinme/wallets/chains.py), then the yaml |
| Add a non-EVM family (Solana, for example) | new file in `pinme/wallets/providers/`, register it in [`pinme/wallets/service.py`](pinme/wallets/service.py) |
| Subscribe or ignore a Paystack event | [`config/events.yaml`](config/events.example.yaml) |
| Change the sentence for a Paystack event | [`pinme/paystack/handlers.py`](pinme/paystack/handlers.py) |
| Change Paystack signature rules | [`pinme/paystack/signatures.py`](pinme/paystack/signatures.py) |
| Call the Paystack REST API | [`pinme/paystack/client.py`](pinme/paystack/client.py) |
| Subscribe or ignore a Shopify topic | [`config/events.yaml`](config/events.example.yaml) |
| Change the sentence for a Shopify topic | [`pinme/shopify/handlers.py`](pinme/shopify/handlers.py) |
| Register Shopify subscriptions from code | [`scripts/register_shopify_webhooks.py`](scripts/register_shopify_webhooks.py) |
| Pick which Discord channel receives an event | [`config/routes.yaml`](config/routes.example.yaml) |
| Change embed colors or layout | [`pinme/discord_bot/embeds.py`](pinme/discord_bot/embeds.py) |
| Add a fourth source (Flutterwave, Stripe, a bank) | new package that publishes `Alert` on the bus |

Secrets never go in the yaml. The yaml names the environment variable (`rpc_env: ETH_RPC_URL`). The value lives in `.env`.

## How a message moves

```
wallets poller ─┐
Paystack POST  ─┼─► Alert ─► dedupe ─► routes.yaml ─► Discord embed
Shopify POST   ─┘
```

One process runs all three. Paystack and Shopify need a public HTTPS URL. Wallet polling does not. See [ARCHITECTURE.md](ARCHITECTURE.md) for the boundaries and [HOSTING.md](HOSTING.md) for where to run it.

## Keys you need

Nothing here is optional forever, but you can turn a source on only when you have its key. Empty keys make that source reject webhooks (401) or skip wallets. The bot still boots.

### Discord

Create an application at <https://discord.com/developers/applications>.

| Value | Where | Env |
| --- | --- | --- |
| Bot token | Bot → Reset Token | `DISCORD_BOT_TOKEN` |
| Application id | General Information → Application ID | only used in the invite URL |
| Server id | Discord → right-click the server (Developer Mode) | `DISCORD_GUILD_ID` (optional, recommended while building) |
| Channel id | right-click the channel | `config/routes.yaml`, not env |

Do **not** enable Message Content intent. Pin Me uses slash commands (`/pin status`, `/pin wallets`, `/pin test`) and only sends messages.

Invite, after replacing `CLIENT_ID`:

```
https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=84992&scope=bot%20applications.commands
```

`84992` is View Channel, Send Messages, Embed Links, and Read Message History.

### Paystack

Dashboard: <https://dashboard.paystack.com/v2/developers>. Test and live are separate keys. The API host is the same (`https://api.paystack.co`); the key prefix selects the mode (`sk_test_` / `sk_live_`).

| Value | Prefix | Used for | Env |
| --- | --- | --- | --- |
| Secret key | `sk_test_` / `sk_live_` | REST calls, and the legacy webhook header | `PAYSTACK_SECRET_KEY` |
| Public key | `pk_test_` / `pk_live_` | Your frontend checkout only. The bot does not need it | `PAYSTACK_PUBLIC_KEY` |
| Webhook signing secret | `whsec_` | The new `Paystack-Signature` header | `PAYSTACK_WEBHOOK_SECRET` |
| Restricted key | `rk_` | Not used. Create one later if you want a least-privilege REST key | — |

Paystack is mid-migration on webhook signatures (late 2026):

- **Legacy:** header `x-paystack-signature`, HMAC-SHA512 of the raw body, key = secret key.
- **Current:** header `Paystack-Signature: t=<unix>,v1=<key id>:<hex>`, HMAC-SHA512 of `{t}.{raw body}`, key = `whsec_...`, reject if `t` is more than 5 minutes off.

Pin Me accepts either. Set both secrets during rotation. Docs: <https://paystack.com/docs/payments/webhooks/>.

Webhook URL to paste in the dashboard (Developers → API configuration):

```
https://YOUR_HOST/webhooks/paystack
```

Their source IPs are `52.31.139.75`, `52.49.173.169`, `52.214.14.220`. Leave `PAYSTACK_ENFORCE_IP=false` if you sit behind Cloudflare, Railway, or Caddy, because the socket IP will not be Paystack's. Live retries run for about 72 hours, so a bad signature or a down host does not lose the event immediately, but you should still alarm on `/health`.

Events you can turn on without code changes are listed in [`config/events.example.yaml`](config/events.example.yaml). Amounts arrive in subunit (kobo). The handler divides by 100.

### Shopify

For a single store, create a **custom app** in the admin: Settings → Apps and sales channels → Develop apps.

| Value | Where | Env |
| --- | --- | --- |
| Shop domain | `your-store.myshopify.com` | `SHOPIFY_SHOP` |
| Admin API access token | API credentials, shown once (`shpat_...`) | `SHOPIFY_ADMIN_TOKEN` |
| Client secret (API secret key) | API credentials | `SHOPIFY_WEBHOOK_SECRET` if you subscribe via the Admin API |
| Notification signing secret | Settings → Notifications → Webhooks | `SHOPIFY_WEBHOOK_SECRET` if you subscribe in that screen instead |

Use the secret that matches **how the subscription was created**. They are not interchangeable. Verification is base64 HMAC-SHA256 of the raw body, header `X-Shopify-Hmac-Sha256`. Docs: <https://shopify.dev/docs/apps/build/webhooks>.

Shopify gives the endpoint 5 seconds and expects a 2xx. After 8 consecutive failures it can delete an Admin API subscription. The handler verifies, queues, and returns 200 before Discord is called.

Useful headers: `X-Shopify-Topic`, `X-Shopify-Shop-Domain`, `X-Shopify-Webhook-Id` (dedupe), `X-Shopify-Event-Id`, `X-Shopify-API-Version`.

Default API version in this repo is `2026-10`. Bump `SHOPIFY_API_VERSION` when you upgrade the app.

Subscribe either in the admin UI, or:

```bash
python scripts/register_shopify_webhooks.py
```

That script reads the allow list from `config/events.yaml` and registers `{PUBLIC_BASE_URL}/webhooks/shopify`.

Customer email is off unless `include_customer_email: true` under `shopify:` in the events file. Shipping addresses are never posted.

### Wallets

Polling is the default. It is enough for a handful of addresses and stays inside free tiers. Push (Alchemy Notify, Moralis Streams) is optional and off until you set `webhook_providers.*.enabled: true`.

| Provider | What you get on the free tier | Env |
| --- | --- | --- |
| Any EVM JSON-RPC (Alchemy, Infura, Ankr, a private node) | `eth_getBalance` and ERC-20 `balanceOf` | `ETH_RPC_URL`, `BASE_RPC_URL`, … |
| Etherscan API v2 | Transfer list across the Etherscan-family chains. One key, `chainid` selects the chain | `ETHERSCAN_API_KEY` |
| TronGrid | TRX balance, TRC-20 balances, TRC-20 history. Header `TRON-PRO-API-KEY` | `TRONGRID_API_KEY` |
| Alchemy Address Activity | Push, no polling. Signing key in the webhook details | `ALCHEMY_WEBHOOK_SIGNING_KEY` |
| Moralis Streams | Push. Streams secret, **not** the API key. Header `x-signature` | `MORALIS_STREAMS_SECRET` |

Chains wired today: Ethereum, Sepolia, Base, Polygon, BNB Smart Chain, Arbitrum, Optimism, Celo, TRON. Celo transfer history uses Celoscan's v1 API; balances still use your Celo RPC. Sepolia uses the same poller as mainnet with chain id `11155111` and `SEPOLIA_RPC_URL`.

The first successful poll stores a baseline and does **not** alert. Later polls alert when the balance moves by at least `min_change`. A gap while the process is down still shows up as a balance delta. A burst of more than 20 transfers during the gap can skip individual transaction alerts; the balance alert still fires. That limit is the `offset: 20` in the explorer call.

## Run it locally

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
cp config/wallets.example.yaml config/wallets.yaml
cp config/routes.example.yaml config/routes.yaml
cp config/events.example.yaml config/events.yaml
python -m pinme --check-config
pytest
python -m pinme
```

`--check-config` checks the yaml and prints what is still a placeholder. `--strict` exits non-zero on those warnings.

Slash commands update immediately when `DISCORD_GUILD_ID` is set. Without it, Discord can take up to an hour to show global commands.

For webhooks on a laptop, expose port 8080 with a tunnel (Cloudflare Tunnel or ngrok) and put that HTTPS origin in `PUBLIC_BASE_URL`. Paystack and Shopify reject plain HTTP.

`/pin test` sends an alert through the bus, the deduper, the router, and Discord. Use it before pointing real money at the bot.

## Layout

```
pinme/
  app.py                 process entry: HTTP + Discord + poll loop
  config.py              env only
  filters.py             event allow lists
  routing.py             channel picker
  core/                  Alert, bus, dedupe
  discord_bot/           gateway, slash commands, embeds
  wallets/               yaml, state, EVM provider, TRON provider, inbound webhooks
  paystack/              signatures, handlers, REST client, event catalog
  shopify/               signatures, handlers, Admin API client, topics
  http/server.py         /health and the four POST routes
config/                  examples, safe to commit
scripts/                 one-off registration
```

State files (`data/wallet_state.json`, `data/dedupe.json`) are created at runtime and gitignored. Delete `wallet_state.json` if you want the next poll to be a fresh baseline.

## Tests

```bash
pytest
```

The tests cover signature verification (including Paystack's replay window), kobo → naira formatting, channel routing, the balance baseline, dedupe across restart, and a signed Paystack POST through the HTTP app. They do not call Discord, Paystack, Shopify, or a chain.

## Status of the build

The modules above run. What is left is your keys, a public URL, and a host that stays up. Track that in [MILESTONES.md](MILESTONES.md). Hosting, uptime, and cost are in [HOSTING.md](HOSTING.md).

## License

MIT. See [LICENSE](LICENSE).
