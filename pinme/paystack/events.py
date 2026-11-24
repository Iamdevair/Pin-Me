"""Event names Paystack documents, kept here so the catalog sits next to the module.

Subscription itself is config/events.yaml. An allow-listed event that is not
in KNOWN_EVENTS still produces a generic alert.
"""

from __future__ import annotations

# charge.failed is in Paystack's events catalog even when older guides
# emphasize charge.success. Keep both.
KNOWN_EVENTS: dict[str, str] = {
    "charge.success": "A charge succeeded",
    "charge.failed": "A charge failed",
    "charge.dispute.create": "A dispute was opened",
    "charge.dispute.remind": "A dispute reminder",
    "charge.dispute.resolve": "A dispute was resolved",
    "transfer.success": "A transfer succeeded",
    "transfer.failed": "A transfer failed",
    "transfer.reversed": "A transfer was reversed",
    "refund.processed": "A refund was processed",
    "refund.failed": "A refund failed",
    "refund.pending": "A refund is pending",
    "refund.processing": "A refund is processing",
    "invoice.create": "A subscription invoice was created",
    "invoice.update": "A subscription invoice changed",
    "invoice.payment_failed": "A subscription invoice payment failed",
    "subscription.create": "A subscription was created",
    "subscription.disable": "A subscription was disabled",
    "subscription.not_renew": "A subscription will not renew",
    "subscription.expiring_cards": "A subscription card is expiring",
    "customeridentification.success": "Customer identification succeeded",
    "customeridentification.failed": "Customer identification failed",
    "dedicatedaccount.assign.success": "A dedicated NUBAN was assigned",
    "dedicatedaccount.assign.failed": "Dedicated account assignment failed",
    "paymentrequest.pending": "A payment request is pending",
    "paymentrequest.success": "A payment request was paid",
}

# Published webhook source IPs, same for test and live.
# Only checked when PAYSTACK_ENFORCE_IP=true. Leave it off behind a proxy.
PAYSTACK_IPS = frozenset({"52.31.139.75", "52.49.173.169", "52.214.14.220"})
