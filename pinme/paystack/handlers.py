"""Turn a verified Paystack body into an Alert.

Add wording for an event by adding a function and a line in BUILDERS.
If you only add the event name to config/events.yaml, generic_alert still
posts the amount, reference, and status when those fields exist.
Amounts on Paystack are in the subunit (kobo for NGN, cent for USD).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from pinme.core.alerts import Alert
from pinme.filters import SourceFilter

Builder = Callable[[str, dict, bool], Alert]


def to_alert(payload: dict, source_filter: SourceFilter) -> Alert | None:
    event = str(payload.get("event") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not event or not source_filter.accepts(event):
        return None
    builder = BUILDERS.get(event, generic_alert)
    return builder(event, data, source_filter.include_customer_email)


def generic_alert(event: str, data: dict, include_email: bool) -> Alert:
    amount = _money(data)
    fields = _base_fields(data, include_email)
    if amount:
        fields["Amount"] = amount
    title = event.replace(".", " ").replace("_", " ")
    body = "Paystack sent this event."
    severity = "info"
    if event.endswith(".failed") or event.endswith("_failed"):
        severity = "critical"
    elif event.endswith(".success") or event.endswith(".processed"):
        severity = "success"
    return Alert(
        source="paystack",
        event=event,
        title=f"Paystack · {title}",
        body=body,
        severity=severity,
        fields=fields,
        dedupe_key=_dedupe(event, data),
    )


def charge_success(event: str, data: dict, include_email: bool) -> Alert:
    alert = generic_alert(event, data, include_email)
    alert.title = f"Payment received {_money(data) or ''}".strip()
    alert.body = "A Paystack charge succeeded."
    alert.severity = "success"
    channel = data.get("channel")
    if channel:
        alert.fields["Channel"] = str(channel)
    return alert


def charge_failed(event: str, data: dict, include_email: bool) -> Alert:
    alert = generic_alert(event, data, include_email)
    alert.title = f"Payment failed {_money(data) or ''}".strip()
    alert.body = str(data.get("gateway_response") or "A Paystack charge failed.")
    alert.severity = "critical"
    return alert


def transfer_success(event: str, data: dict, include_email: bool) -> Alert:
    alert = generic_alert(event, data, include_email)
    alert.title = f"Transfer sent {_money(data) or ''}".strip()
    alert.body = "A Paystack transfer succeeded."
    alert.severity = "warning"
    recipient = data.get("recipient") if isinstance(data.get("recipient"), dict) else {}
    details = recipient.get("details") if isinstance(recipient.get("details"), dict) else {}
    label = details.get("account_name") or recipient.get("name")
    if label:
        alert.fields["Recipient"] = str(label)
    return alert


def transfer_failed(event: str, data: dict, include_email: bool) -> Alert:
    alert = generic_alert(event, data, include_email)
    alert.title = f"Transfer failed {_money(data) or ''}".strip()
    alert.body = str(data.get("reason") or "A Paystack transfer failed.")
    alert.severity = "critical"
    return alert


BUILDERS: dict[str, Builder] = {
    "charge.success": charge_success,
    "charge.failed": charge_failed,
    "transfer.success": transfer_success,
    "transfer.failed": transfer_failed,
    "transfer.reversed": transfer_failed,
}


def _money(data: dict) -> str:
    amount = data.get("amount")
    if amount is None:
        amount = data.get("requested_amount")
    if amount is None:
        return ""
    try:
        major = (Decimal(str(amount)) / Decimal(100)).quantize(Decimal("0.01"))
    except Exception:
        return str(amount)
    currency = str(data.get("currency") or "NGN")
    return f"{currency} {major:,.2f}"


def _reference(data: dict) -> str:
    for key in ("reference", "transfer_code", "id"):
        if data.get(key):
            return str(data[key])
    return ""


def _base_fields(data: dict, include_email: bool) -> dict[str, str]:
    fields: dict[str, str] = {}
    reference = _reference(data)
    if reference:
        fields["Reference"] = reference
    status = data.get("status")
    if status:
        fields["Status"] = str(status)
    if include_email:
        customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
        email = customer.get("email") or data.get("customer_email")
        if email:
            fields["Customer"] = str(email)
    return fields


def _dedupe(event: str, data: dict) -> str:
    return f"paystack:{event}:{_reference(data) or data.get('customer_code') or 'noref'}"
