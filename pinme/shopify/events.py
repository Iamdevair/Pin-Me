"""Topic strings Shopify puts in the X-Shopify-Topic header.

The allow list is config/events.yaml. This map is the wording for the
topics a store usually cares about. Any other allowed topic still alerts.
"""

from __future__ import annotations

# REST-style topic → short label. GraphQL enum is the same string uppercased
# with "/" replaced by "_", e.g. orders/create → ORDERS_CREATE.
TOPIC_LABELS: dict[str, str] = {
    "orders/create": "New order",
    "orders/paid": "Order paid",
    "orders/cancelled": "Order cancelled",
    "orders/updated": "Order updated",
    "orders/fulfilled": "Order fulfilled",
    "refunds/create": "Refund created",
    "fulfillments/create": "Fulfillment created",
    "fulfillments/update": "Fulfillment updated",
    "products/create": "Product created",
    "products/update": "Product updated",
    "inventory_levels/update": "Inventory changed",
    "customers/create": "Customer created",
    "customers/update": "Customer updated",
    "checkouts/create": "Checkout started",
    "app/uninstalled": "App uninstalled",
}


def graphql_topic(topic: str) -> str:
    return topic.strip().upper().replace("/", "_")
