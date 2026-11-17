"""MOCKED checkout and payment events. No real or sandbox payment provider is used.

No money exists here: an "order" and a "payment" are rows in an in-memory ledger.
No card numbers, passwords or personal data are accepted or stored; a buyer is an
opaque label such as "test-buyer-1".
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
from dataclasses import dataclass, field

MOCKED = True
MOCK_WEBHOOK_SECRET = b"mock-webhook-secret-not-a-real-credential"
MOCK_FEE_RATE, MOCK_FEE_FIXED_CENTS = 0.029, 30     # an illustrative fee shape, MOCKED


@dataclass
class Store:
    """The mock ledger for one run."""
    orders: dict = field(default_factory=dict)        # order_id -> {product_id, buyer, amount_cents, status}
    payments: dict = field(default_factory=dict)      # payment_id -> {order_id, amount_cents, fee_cents}
    refunds: dict = field(default_factory=dict)       # refund_id -> {order_id, amount_cents}
    payouts: list = field(default_factory=list)       # [{amount_cents, payment_ids, refund_ids}]
    access: dict = field(default_factory=dict)        # order_id -> {link, active}
    processed_events: set = field(default_factory=set)  # idempotency keys already handled
    deliveries: list = field(default_factory=list)    # one row per delivery actually performed
    auto_delivery: dict = field(default_factory=dict)  # product_id -> (action, approval record)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1), repr=False)

    def next_id(self, prefix: str) -> str:
        return f"{prefix}_mock_{next(self._ids):04d}"


def sign(event: dict) -> str:
    body = json.dumps({k: v for k, v in event.items() if k != "signature"}, sort_keys=True).encode()
    return hmac.new(MOCK_WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()


def create_checkout(store: Store, product_id: str, price_cents: int, buyer: str = "test-buyer-1") -> dict:
    """MOCKED checkout: creates an order awaiting payment."""
    order_id = store.next_id("order")
    store.orders[order_id] = {"id": order_id, "product_id": product_id, "buyer": buyer,
                              "amount_cents": int(price_cents), "status": "awaiting_payment", "mocked": True}
    return store.orders[order_id]


def mock_payment_event(store: Store, order_id: str) -> dict:
    """Build the MOCKED 'payment succeeded' webhook event for an order. The event id is the idempotency key."""
    amount = store.orders[order_id]["amount_cents"]
    event = {"id": store.next_id("evt"), "type": "payment.succeeded", "order_id": order_id,
             "payment_id": store.next_id("pay"), "amount_cents": amount,
             "fee_cents": round(amount * MOCK_FEE_RATE) + MOCK_FEE_FIXED_CENTS, "mocked": True}
    event["signature"] = sign(event)
    return event


def mock_refund_event(store: Store, order_id: str) -> dict:
    event = {"id": store.next_id("evt"), "type": "refund.succeeded", "order_id": order_id,
             "refund_id": store.next_id("ref"), "amount_cents": store.orders[order_id]["amount_cents"], "mocked": True}
    event["signature"] = sign(event)
    return event


def mock_payout(store: Store) -> dict:
    """MOCKED payout: what a provider would pay out = payments - fees - refunds not yet paid out."""
    paid = {pid for p in store.payouts for pid in p["payment_ids"]}
    refunded = {rid for p in store.payouts for rid in p["refund_ids"]}
    new_payments = {pid: p for pid, p in store.payments.items() if pid not in paid}
    new_refunds = {rid: r for rid, r in store.refunds.items() if rid not in refunded}
    amount = (sum(p["amount_cents"] - p["fee_cents"] for p in new_payments.values())
              - sum(r["amount_cents"] for r in new_refunds.values()))
    payout = {"id": store.next_id("payout"), "amount_cents": amount, "payment_ids": sorted(new_payments),
              "refund_ids": sorted(new_refunds), "mocked": True}
    store.payouts.append(payout)
    return payout
