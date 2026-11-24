# Hosting, uptime, cost, maintenance

Numbers below are rough public prices as of November 2026, for one shop, one Paystack account, and fewer than about twenty wallets polled once a minute. This is a single small process. It does not need Kubernetes.

## What has to stay up

| Piece | Must be always on? | Why |
| --- | --- | --- |
| Discord gateway | Yes | If the process stops, the bot goes offline and queued embeds die with it |
| HTTP server | Yes, once webhooks are live | Paystack retries a failed delivery for a long time. Shopify retries 8 times over ~4 hours, then can delete the subscription |
| Wallet poller | Yes, if you care about timely balance alerts | A later poll still notices the balance move. You lose timing, not the fact of the move |
| Postgres / Redis | No | State is a JSON file on local disk. Do not run two copies |

A free web dyno that sleeps (Render free, some Railway trials when idle) is a bad fit. The gateway disconnects, and Shopify will burn its retries while the box is asleep.

## Where to run it

Pick one.

| Option | Fits this bot? | Rough cost | Notes |
| --- | --- | --- | --- |
| Hetzner CX22 or similar 2 GB VPS, EU | Best default | about €4–6 / month | Close to Paystack's webhook IPs (AWS eu-west-1). Put Caddy in front for HTTPS. systemd or Docker with `restart: unless-stopped` |
| DigitalOcean / Lightsail 1 GB droplet | Fine | about $6 / month | Same shape as Hetzner |
| Oracle Cloud always-free Ampere VM | Fine if you can get one | $0 | Capacity is often unavailable. Still need a domain or a tunnel |
| Fly.io shared-1cpu-256mb or 512mb, one machine, not scale-to-zero | Fine | about $2–5 / month | Set `min_machines_running = 1`. Mount a volume so `data/` survives deploys |
| Railway / Render **paid** web service that does not sleep | Fine | about $5–7 / month | They set `PORT`. Use the `Procfile`. Attach a disk if you care about dedupe across deploys |
| Home PC or a laptop in Aba | Only for a weekend test | electricity + data | Power and uplink will drop. Do not point live Paystack here |
| AWS Lambda, Vercel, Cloudflare Workers | No | — | The Discord gateway is a long-lived socket. Webhooks alone could be split out later; it is not worth it at this size |

A domain is optional. Fly, Railway, and Render give you an HTTPS hostname. A VPS needs either a domain (~$10 / year) plus Caddy, or a Cloudflare Tunnel to a hostname you already have. Paystack and Shopify both require HTTPS.

Suggested production shape: one EU VPS or one Fly machine, Docker, a single replica, the `data/` directory on a volume.

```bash
docker build -t pin-me .
docker run -d --name pin-me --restart unless-stopped \
  --env-file .env -p 8080:8080 \
  -v pinme-data:/app/data \
  pin-me
```

The image listens on `$PORT` (8080 by default). Health check path: `/health`.

## The lifeline

What happens when something breaks:

| Failure | What Pin Me does | What you should add |
| --- | --- | --- |
| Process crash | Docker/systemd starts it again. Next wallet poll diffs against the saved baseline. Webhooks that never got a 200 are retried by Paystack/Shopify | Restart policy. Confirm `data/` is on a real disk, not the container's writable layer if you redeploy often |
| Discord outage | Notifier logs and keeps the in-memory queue until the process dies | Nothing, until M6. A missed post during a Discord incident is acceptable at this scale |
| Bad deploy, crash loop | Bot shows offline. Shopify starts failing the endpoint | Uptime check. Keep the previous image so you can roll back |
| RPC rate limit or a dead endpoint | That wallet emits one `poll.failed` alert (deduped), other wallets continue | Fix the URL in `.env`. The chain preset does not need a code change |
| Paystack or Shopify signature rotation | Old verifier still accepts the legacy Paystack header. Shopify will 401 until `SHOPIFY_WEBHOOK_SECRET` matches the new secret | Update env, restart. Watch for 401s in the log on cutover day |
| Clock skew | Paystack's new signature rejects events more than 5 minutes off | Enable NTP. Every VPS image already does |
| Two replicas by accident | Double alerts, racy JSON state | Keep the scale at 1 |

Uptime monitor, free tiers are enough:

- Better Stack, Healthchecks.io, or UptimeRobot
- GET `https://YOUR_HOST/health` every 1–3 minutes
- Alarm when status is not 200 or `bot_ready` is false for more than a couple of minutes
- Send that alarm to email and, if you want, a Discord webhook that is **not** this bot (so the alarm still fires when the bot is the thing that died)

Also glance at the bot's offline icon. That is a second signal and costs nothing.

Paystack's own delivery log (Developers → webhook events, and the dashboard retry view) is the third signal. If they show `Failed` and the process is up, you have a signature or allow-list bug, not a host bug.

## Cost

| Item | Monthly |
| --- | --- |
| Small always-on VM or paid app platform | $0–7 |
| Domain, if the host does not give you HTTPS | ~$1 amortized |
| Discord, Paystack, Shopify APIs | $0 |
| EVM RPC on a free Alchemy/Infura/Ankr allowance | $0 at this volume (`eth_getBalance` once a minute is noise) |
| Etherscan free key | $0, and you can skip it if you only watch balances |
| TronGrid free key | $0 |
| Uptime monitor free tier | $0 |
| Alchemy Notify or Moralis Streams | $0 if you leave them off. Moralis paid plans start around $49 if you outgrow the free stream allowance. You do not need this for v1 |
| **Typical total** | **about $5–8, or $0 on an always-free VM** |

The expensive way to run this is a paid blockchain stream plus a sleeping web host. The cheap way is a $5 VPS, free RPC, and webhooks you already get from Paystack and Shopify.

## Maintenance

Light, if you don't keep rewriting it.

Weekly, nothing, if `/health` is quiet.

When something changes:

- **New wallet, new event, new channel.** Edit the yaml, restart. No image rebuild required if the yaml is mounted or baked into the env files on the host. Today the yaml is copied into the image, so a config change is a rebuild *or* you bind-mount `./config` over `/app/config`. Bind-mount it.
- **Key rotation.** Paystack lets you overlap secret keys. Shopify admin tokens are shown once; if you lose one, generate another and update `.env`. Discord bot token: reset in the portal, update `.env`, restart. Old token dies immediately.
- **Shopify API version.** They sunset versions on a schedule. Bump `SHOPIFY_API_VERSION` (currently `2026-10`) and re-read the order payload if a field you display disappeared. The handler only reads `name`, `total_price`, `currency`, `financial_status`, `line_items`, `email`.
- **discord.py.** Pin it. A major bump can change intents or slash-command sync. Renovate or a quarterly `pip install -U` in a branch, with `pytest` green, is enough.
- **Disk.** State and dedupe files stay small (dedupe entries expire after 48 hours). Logs are the thing that grows. Use journald or Docker's json-file driver with a size cap. Do not log raw webhook bodies; they can contain customer emails.
- **Backups.** Back up `.env` into a password manager. Back up `config/wallets.yaml` if the addresses are annoying to retype. The JSON state can be rebuilt (next poll is a new baseline).
- **Who is on call.** One person. If the bot is down, Paystack retries and wallet balances catch up. The real operational risk is a Shopify subscription getting deleted after repeated failures, because you then stop receiving orders until you run the register script again. The uptime alarm exists to prevent that.

## What I would do for the first real deploy

1. Finish M1–M4 on a laptop plus a Cloudflare Tunnel, test keys only.
2. Move the same `.env` and yaml to a €5 Hetzner box or a single Fly machine with a volume.
3. Point Healthchecks.io at `/health`.
4. Only then switch Paystack to live and subscribe the real Shopify shop.

Do not buy a stream provider, a database, or a second region until a milestone in [MILESTONES.md](MILESTONES.md) says you are missing something the current process cannot do.
