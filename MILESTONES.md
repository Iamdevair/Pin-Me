# Build tracker

Check these off in order. The code for M0–M4 is in the repo. The unchecked work is configuration, a host, and a soak test against your real accounts. Do not skip the test-mode events and jump to live keys.

## M0 — Skeleton

- [x] Public repo, module per source, yaml for wallets / events / channels
- [x] `Alert` bus, dedupe, route resolver
- [x] `.env.example` listing every key, with no secrets committed
- [x] `pytest` covering signatures, routing, baseline, and a signed webhook

## M1 — Discord

- [ ] Create the application, invite the bot, set `DISCORD_BOT_TOKEN` and `DISCORD_GUILD_ID`
- [ ] Put a real channel id in `config/routes.yaml`
- [ ] `python -m pinme` stays online
- [ ] `/pin status` responds
- [ ] `/pin test` posts an embed in the right channel

## M2 — One wallet

- [ ] Copy `config/wallets.example.yaml` to `config/wallets.yaml`
- [ ] Set one real address, `enabled: true`, and its RPC URL
- [ ] First poll logs a baseline and does not alert
- [ ] Send a small amount in or out. A balance alert arrives within `poll_seconds`
- [ ] Restart the process. It does not re-alert the same balance
- [ ] Optional: set `ETHERSCAN_API_KEY` or `TRONGRID_API_KEY` and add `transfers` to `watch`

## M3 — Paystack test mode

- [ ] Use `sk_test_` and, if the dashboard has issued one, `whsec_`
- [ ] Expose `/webhooks/paystack` over HTTPS
- [ ] Paste the URL in the Paystack dashboard
- [ ] Run a test charge. `charge.success` posts amount in NGN, not kobo
- [ ] Replay the same event from the dashboard. Dedupe drops the second post
- [ ] Send an unsigned POST. It returns 401 and nothing hits Discord

## M4 — Shopify development store or a cheap test order

- [ ] Custom app token and the matching webhook secret
- [ ] Allow list reviewed in `config/events.yaml` (product updates stay off unless you want the noise)
- [ ] Subscribe with the admin UI or `python scripts/register_shopify_webhooks.py`
- [ ] Place a test order. `orders/create` or `orders/paid` posts order name and total
- [ ] Confirm the embed has no email and no address
- [ ] Kill the process, let Shopify retry, bring it back, confirm you get one alert not eight

## M5 — Soak and the gaps we already know about

- [ ] Leave it up for 48 hours on test traffic
- [ ] Confirm a poll failure alerts once, not every minute (`poll.failed` dedupe)
- [ ] If you need every transaction during downtime, replace the "last 20" explorer window with a stored block cursor in `pinme/wallets/providers/evm.py`
- [ ] Decide whether Alchemy or Moralis push is worth it. Leave it off if polling is enough

## M6 — Production cutover

- [ ] Host from [HOSTING.md](HOSTING.md) with restart-on-failure
- [ ] Uptime monitor on `/health`, alarm into Discord or email
- [ ] Swap Paystack to `sk_live_` and the live webhook secret
- [ ] Swap Shopify to the real shop only after the test shop passed M4
- [ ] Write down who rotates keys, and where `.env` is backed up (a password manager, not git)
- [ ] Optional, only if a lost Discord post would hurt: persist the notifier queue before returning HTTP 200

## M7 — Handoff

- [ ] A second person clones the repo, runs `--check-config`, and adds a wallet by editing yaml only
- [ ] They can say which file to open for a Paystack wording change without asking
- [ ] Pin dependency versions if the host is going to sit untouched for months (`pip freeze` into a lock file when you first deploy)

When a box needs a code change, keep the change inside the package named in the [README map](README.md#map).
