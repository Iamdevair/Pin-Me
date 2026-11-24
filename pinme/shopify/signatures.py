"""Shopify signs the raw body with HMAC-SHA256, base64, in X-Shopify-Hmac-Sha256.

The key is:
- the app Client secret, for subscriptions created by your custom or public app
- the signing secret Shopify shows under Settings → Notifications → Webhooks,
  for subscriptions created in the admin UI

Put whichever one matches how you subscribed into SHOPIFY_WEBHOOK_SECRET.
Respond with a 2xx within 5 seconds or Shopify retries, then deletes the
subscription after 8 consecutive failures (Admin API subscriptions).
"""

from __future__ import annotations

import base64
import hashlib
import hmac


def verify_shopify(raw: bytes, header: str | None, secret: str) -> bool:
    if not header or not secret:
        return False
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, header.strip())
