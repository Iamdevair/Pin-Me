# Architecture

Pin Me is one long-running Python process. It is not a set of serverless functions. Discord's gateway wants a persistent connection, and Paystack and Shopify want an HTTPS endpoint that answers in a few seconds. One process can do both without a queue service.

## Boundaries

```
                    ┌──────────────── config/wallets.yaml
                    │
   JSON-RPC / TronGrid
        │
        ▼
 pinme.wallets.service ──poll──► pinme.wallets.providers.*
                                        │
 Paystack POST ─► paystack.signatures ─► paystack.handlers
 Shopify POST  ─► shopify.signatures  ─► shopify.handlers
 Alchemy/Moralis ► wallets.providers.inbound
                                        │
                                        ▼
                              pinme.core.alerts.Alert
                                        │
                                        ▼
                              pinme.core.bus.EventBus
                                        │
                                        ▼
                              pinme.core.dedupe
                                        │
                                        ▼
                              pinme.routing  (config/routes.yaml)
                                        │
                                        ▼
                              discord_bot.notifier ──► embed in a channel
```

Rules that keep the modules swappable:

1. A provider returns `list[Alert]`. It does not import `discord`.
2. A handler does not know channel ids. Routing is data.
3. Secrets stay in the environment. Yaml only stores public addresses, event names, and channel ids.
4. Webhook handlers verify the raw body, then return HTTP 200 before any Discord call. The notifier has its own task and a short queue.
5. An event that is not on the allow list still returns 200. Otherwise Paystack retries for up to ~72 hours and Shopify eventually deletes the subscription.
6. Fail closed. Missing secret, bad signature, disabled provider → 401 or 404, never a Discord post.

## Why polling for wallets, webhooks for Paystack and Shopify

Paystack and Shopify already push, and they sign the body. There is nothing to poll that is better.

Wallets are the opposite. A balance is a point in time. `eth_getBalance` on a free RPC, once a minute, for under twenty addresses, is boring and cheap. You do not need Alchemy Notify ($0 at small scale, but another webhook to keep alive) or Moralis Streams (paid once you leave the small free allowance) to know that a wallet moved.

Push is in the tree anyway, behind `webhook_providers`, for the day a wallet is too active for a 60 second poll. Both paths emit the same `transfer.in` / `transfer.out` alerts, so Discord does not care which one you use.

Balance alerts and transfer alerts are separate watches. You can run balances with only an RPC URL, and turn on `transfers` later when you have an Etherscan or TronGrid key.

## Process lifecycle

`python -m pinme` does this:

1. Load `.env` and the three yaml files. Placeholder channel ids are skipped, not fatal, so the example files load.
2. Bind `0.0.0.0:$PORT` (`PORT` defaults to 8080, which is what Railway, Render, and Fly set).
3. Start the wallet loop and the Discord send loop as tasks.
4. Log the bot in. `setup_hook` syncs `/pin` commands. `on_ready` releases the send loop, so an alert that arrives during login waits instead of failing.
5. On SIGTERM, close Discord, cancel the tasks, and shut the HTTP runner. Docker and systemd should send SIGTERM.

State is a JSON file, written atomically (temp file, then rename). It is not a database on purpose. Two processes must not share one state file. Run a single replica.

## What "easy to hand to another dev" means in this tree

- `config/*.example.yaml` is the contract. The comments in those files are the operator manual for day-to-day edits.
- `python -m pinme --check-config` is the smoke test a new person runs before they have a token.
- Each package's `__init__.py` says what that package is allowed to do.
- Adding an event to an allow list uses the generic alert if nobody wrote a custom sentence. Custom sentences are optional.
- Adding an EVM chain is a row in `chains.py` (chain id, symbol, decimals, which explorer style).
- Adding a source is a new package plus one `bus.subscribe` is not even required: publish on the existing bus from the HTTP layer or from a poller. The notifier is already subscribed.

## Explicit non-goals for this scaffold

- No database, no users, no multi-tenant stores. One Paystack account, one Shopify shop, one Discord server.
- No message-content commands. Slash commands only, so privileged intents stay off.
- No card data, BVN, or shipping address in Discord. Handlers pick fields.
- No guarantee of exactly-once chain history across downtime longer than the explorer page (20 rows). Balance diff covers the money; transaction rows can skip. See milestone M5.
- The in-memory Discord queue is lost if the process dies after Paystack got a 200. Paystack will not retry a 200. Milestone M6 persists the outbound queue if that risk starts to matter. For a shop's own server, a missed Discord post is visible and rare; a crashed process usually dies before the 200, and Paystack retries.

## HTTP surface

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | `{"ok": true, "bot_ready": bool, ...}`. Point an uptime monitor here |
| POST | `/webhooks/paystack` | Either signature scheme |
| POST | `/webhooks/shopify` | HMAC SHA256, base64 |
| POST | `/webhooks/wallets/alchemy` | 404 until enabled in the wallet yaml |
| POST | `/webhooks/wallets/moralis` | 404 until enabled. Confirmed-only deliveries (`confirmed: false` is ignored) |

## Discord surface

| Command | What it does |
| --- | --- |
| `/pin status` | Ready flag, wallet count, last Paystack and Shopify event, last poll error |
| `/pin wallets` | The yaml, including disabled rows |
| `/pin test` | Publishes a real `Alert` so you can see routing |

Channel matching order is in [`pinme/routing.py`](pinme/routing.py): exact source and event, then any-source with that event, then source wildcard, then global wildcard, then `default_channel_id`.
