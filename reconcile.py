"""MOCKED reconciliation: match orders, payments, fees, refunds and payouts, and report mismatches."""
from __future__ import annotations

from payments import Store

MOCKED = True


def reconcile(store: Store) -> dict:
    mismatches: list[str] = []
    paid_orders = {p["order_id"] for p in store.payments.values()}

    for order_id, order in store.orders.items():
        if order["status"] in ("paid", "refunded") and order_id not in paid_orders:
            mismatches.append(f"order {order_id} is marked {order['status']} but has no payment")
    for payment_id, payment in store.payments.items():
        order = store.orders.get(payment["order_id"])
        if order is None:
            mismatches.append(f"payment {payment_id} has no order")
        elif payment["amount_cents"] != order["amount_cents"]:
            mismatches.append(f"payment {payment_id} amount {payment['amount_cents']} != order amount {order['amount_cents']}")
    for refund_id, refund in store.refunds.items():
        order = store.orders.get(refund["order_id"])
        if order is None or order["status"] != "refunded":
            mismatches.append(f"refund {refund_id} does not match a refunded order")
        if store.access.get(refund["order_id"], {}).get("active"):
            mismatches.append(f"refund {refund_id}: buyer still has access")
    for order_id, order in store.orders.items():
        if order["status"] == "paid" and not store.access.get(order_id, {}).get("active"):
            mismatches.append(f"order {order_id} is paid but was not delivered")

    gross = sum(p["amount_cents"] for p in store.payments.values())
    fees = sum(p["fee_cents"] for p in store.payments.values())
    refunded = sum(r["amount_cents"] for r in store.refunds.values())
    expected = gross - fees - refunded
    paid_out = sum(p["amount_cents"] for p in store.payouts)
    if expected != paid_out:
        mismatches.append(f"payouts total {paid_out} != expected {expected} (payments {gross} - fees {fees} - refunds {refunded})")

    return {"orders": len(store.orders), "payments": len(store.payments), "refunds": len(store.refunds),
            "gross_cents": gross, "fees_cents": fees, "refunded_cents": refunded,
            "expected_payout_cents": expected, "paid_out_cents": paid_out,
            "matched": not mismatches, "mismatches": mismatches, "mocked": True}
