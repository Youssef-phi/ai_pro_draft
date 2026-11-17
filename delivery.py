"""MOCKED automatic delivery.

Delivery is automatic per order, but the RULE that turns it on is a founder decision:
the founder approves "enable auto-delivery for product X" once, and every deliver()
call checks that standing approval. Without it, deliver() raises ApprovalRequired.
The "access link" is a mock string; nothing is e-mailed or hosted.
"""
from __future__ import annotations

from approval import Action, ApprovalQueue, ApprovalRecord, ApprovalRequired
from payments import Store

MOCKED = True


def auto_delivery_payload(product_id: str) -> dict:
    return {"rule": "auto_delivery", "product_id": product_id}


def enable_auto_delivery(store: Store, queue: ApprovalQueue, action: Action, record: ApprovalRecord | None,
                         product_id: str) -> None:
    """Store the founder's standing approval for auto-delivery of one product."""
    queue.verify(record, action.id, auto_delivery_payload(product_id))
    store.auto_delivery[product_id] = (action, record)


def deliver(store: Store, queue: ApprovalQueue, order_id: str) -> dict:
    """MOCKED delivery of a paid order. Raises ApprovalRequired if the founder never enabled auto-delivery."""
    order = store.orders[order_id]
    if order["status"] != "paid":
        raise ValueError(f"order {order_id} is not paid")
    if order["product_id"] not in store.auto_delivery:
        raise ApprovalRequired(f"auto-delivery for {order['product_id']} has not been approved by the founder")
    action, record = store.auto_delivery[order["product_id"]]
    queue.verify(record, action.id, auto_delivery_payload(order["product_id"]))
    if order_id in store.access and store.access[order_id]["active"]:
        return store.access[order_id]          # already delivered: never deliver twice
    grant = {"order_id": order_id, "link": f"https://example.invalid/mock-download/{order_id}", "active": True,
             "mocked": True}
    store.access[order_id] = grant
    store.deliveries.append({"order_id": order_id, "link": grant["link"]})
    return grant


def revoke(store: Store, order_id: str) -> None:
    if order_id in store.access:
        store.access[order_id]["active"] = False


def has_access(store: Store, order_id: str) -> bool:
    return bool(store.access.get(order_id, {}).get("active"))
