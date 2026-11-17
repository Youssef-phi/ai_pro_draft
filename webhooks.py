"""MOCKED webhook handler: payment events trigger delivery, refund events revoke access.

Idempotency: every event id is remembered. Replaying the same event does nothing
the second time, so a buyer is never delivered to (or refunded) twice.
"""
from __future__ import annotations

import hmac

import delivery
from approval import ApprovalQueue
from payments import Store, sign

MOCKED = True


def handle_event(store: Store, queue: ApprovalQueue, event: dict) -> str:
    """Returns: delivered | access_revoked | duplicate_ignored | rejected_bad_signature | ignored."""
    if not hmac.compare_digest(sign(event), str(event.get("signature", ""))):
        return "rejected_bad_signature"
    if event["id"] in store.processed_events:
        return "duplicate_ignored"

    if event["type"] == "payment.succeeded":
        order = store.orders[event["order_id"]]
        order["status"] = "paid"
        store.payments[event["payment_id"]] = {"order_id": order["id"], "amount_cents": event["amount_cents"],
                                               "fee_cents": event["fee_cents"]}
        delivery.deliver(store, queue, order["id"])     # raises if auto-delivery was never approved
        store.processed_events.add(event["id"])         # only marked done once delivery succeeded
        return "delivered"

    if event["type"] == "refund.succeeded":
        order = store.orders[event["order_id"]]
        order["status"] = "refunded"
        store.refunds[event["refund_id"]] = {"order_id": order["id"], "amount_cents": event["amount_cents"]}
        delivery.revoke(store, order["id"])
        store.processed_events.add(event["id"])
        return "access_revoked"

    return "ignored"
