"""Normalize a Shopify webhook body.

Order payloads use decimal strings (total_price), not subunits.
Customer email is omitted unless the events file turns it on.
We do not paste shipping addresses into Discord.
"""

from __future__ import annotations

from pinme.core.alerts import Alert
from pinme.filters import SourceFilter
from pinme.shopify.events import TOPIC_LABELS


def to_alert(
    topic: str,
    payload: dict,
    source_filter: SourceFilter,
    *,
    webhook_id: str = "",
    shop_domain: str = "",
) -> Alert | None:
    if not topic or not source_filter.accepts(topic):
        return None
    label = TOPIC_LABELS.get(topic, topic)
    fields: dict[str, str] = {}
    if shop_domain:
        fields["Shop"] = shop_domain
    title, body, severity = _summarize(topic, label, payload, fields, source_filter.include_customer_email)
    dedupe = webhook_id or _fallback_id(topic, payload)
    return Alert(
        source="shopify",
        event=topic,
        title=title,
        body=body,
        severity=severity,
        fields=fields,
        dedupe_key=f"shopify:{topic}:{dedupe}",
    )


def _summarize(topic: str, label: str, payload: dict, fields: dict[str, str], include_email: bool) -> tuple[str, str, str]:
    if topic.startswith("orders/") or topic == "orders/paid":
        return _order(topic, label, payload, fields, include_email)
    if topic.startswith("refunds/"):
        return _refund(label, payload, fields)
    if topic.startswith("fulfillments/"):
        return _fulfillment(label, payload, fields)
    if topic.startswith("products/"):
        title = payload.get("title") or payload.get("id") or label
        fields["Product"] = str(title)
        status = payload.get("status")
        if status:
            fields["Status"] = str(status)
        return f"{label}: {title}", "A product webhook arrived.", "info"
    if topic == "app/uninstalled":
        return "Shopify app uninstalled", "The custom app was uninstalled. Webhooks will stop.", "critical"
    name = payload.get("name") or payload.get("title") or payload.get("id") or ""
    if name:
        fields["Id"] = str(name)
    return f"Shopify · {label}", "Shopify sent this topic.", "info"


def _order(topic: str, label: str, payload: dict, fields: dict[str, str], include_email: bool) -> tuple[str, str, str]:
    name = str(payload.get("name") or payload.get("order_number") or payload.get("id") or "order")
    currency = str(payload.get("currency") or payload.get("presentment_currency") or "")
    total = payload.get("total_price") or payload.get("current_total_price") or ""
    if total:
        fields["Total"] = f"{currency} {total}".strip()
    financial = payload.get("financial_status")
    if financial:
        fields["Payment"] = str(financial)
    items = payload.get("line_items")
    if isinstance(items, list):
        fields["Items"] = str(len(items))
        preview = ", ".join(str(item.get("title") or "") for item in items[:3] if isinstance(item, dict))
        if preview:
            fields["Lines"] = preview
    if include_email and payload.get("email"):
        fields["Customer"] = str(payload["email"])
    fields["Order"] = name
    severity = "success" if topic in {"orders/paid", "orders/create"} else "warning" if "cancel" in topic else "info"
    if topic == "orders/cancelled":
        severity = "critical"
    return f"{label} {name} {fields.get('Total', '')}".strip(), f"Shopify {label.lower()}.", severity


def _refund(label: str, payload: dict, fields: dict[str, str]) -> tuple[str, str, str]:
    transactions = payload.get("transactions") if isinstance(payload.get("transactions"), list) else []
    if transactions and isinstance(transactions[0], dict):
        amount = transactions[0].get("amount")
        currency = transactions[0].get("currency") or ""
        if amount:
            fields["Amount"] = f"{currency} {amount}".strip()
    order_id = payload.get("order_id")
    if order_id:
        fields["Order id"] = str(order_id)
    return f"{label} {fields.get('Amount', '')}".strip(), "Shopify created a refund.", "critical"


def _fulfillment(label: str, payload: dict, fields: dict[str, str]) -> tuple[str, str, str]:
    tracking = payload.get("tracking_number") or payload.get("tracking_numbers")
    if isinstance(tracking, list):
        tracking = ", ".join(str(item) for item in tracking[:3])
    if tracking:
        fields["Tracking"] = str(tracking)
    status = payload.get("status")
    if status:
        fields["Status"] = str(status)
    name = payload.get("name") or payload.get("order_id") or ""
    if name:
        fields["Order"] = str(name)
    return f"{label} {name}".strip(), "Shopify fulfillment update.", "success"


def _fallback_id(topic: str, payload: dict) -> str:
    for key in ("id", "admin_graphql_api_id", "order_id", "name"):
        if payload.get(key):
            return f"{topic}:{payload[key]}"
    return topic
