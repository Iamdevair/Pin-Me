"""Both Paystack signature schemes.

New (preferred), header `Paystack-Signature`:
    t=<unix seconds>,v1=<key id>:<hex hmac sha512>
    HMAC-SHA512 of `{t}.{raw body}` using the webhook signing secret (whsec_...).
    Reject when `t` is more than 5 minutes off, to stop replays.

Legacy, header `x-paystack-signature`:
    hex HMAC-SHA512 of the raw body, keyed with the secret key (sk_...).
    Paystack still sends this until you delete the old path. Keep both
    verifiers during rotation. Either match is enough.

Always hash the raw bytes. Re-serializing JSON will not match.
"""

from __future__ import annotations

import hashlib
import hmac
import time

TOLERANCE_SECONDS = 300


def verify_paystack(
    raw: bytes,
    *,
    legacy_header: str | None,
    v2_header: str | None,
    secret_key: str,
    webhook_secret: str,
    now: int | None = None,
) -> bool:
    if v2_header and webhook_secret and _verify_v2(raw, v2_header, webhook_secret, now=now):
        return True
    if legacy_header and secret_key and _verify_legacy(raw, legacy_header, secret_key):
        return True
    return False


def _verify_legacy(raw: bytes, header: str, secret_key: str) -> bool:
    expected = hmac.new(secret_key.encode(), raw, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, header.strip().lower())


def _verify_v2(raw: bytes, header: str, webhook_secret: str, now: int | None) -> bool:
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key, value = key.strip(), value.strip()
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                return False
        elif key == "v1" and ":" in value:
            signatures.append(value.split(":", 1)[1].strip().lower())
    if timestamp is None or not signatures:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > TOLERANCE_SECONDS:
        return False
    mac = hmac.new(
        webhook_secret.encode(),
        str(timestamp).encode() + b"." + raw,
        hashlib.sha512,
    ).hexdigest()
    return any(hmac.compare_digest(mac, signature) for signature in signatures)
