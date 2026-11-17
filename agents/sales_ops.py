"""Phase 5 (Sell, deliver, get paid): drafts the delivery message, then runs the MOCKED
sale-to-cash checks. The checks are plain code (no model): checkout -> payment event ->
automatic delivery, duplicate webhook, refund -> access revoked, reconciliation.
"""
from __future__ import annotations

from typing import Callable

from pydantic import Field

import delivery
import payments
import reconcile
import refunds
import webhooks
from agents.base import run_agent
from approval import ApprovalQueue, ApprovalRequired
from schemas import AgentOutput

ROLE = "sales_ops"


class Output(AgentOutput):
    delivery_subject: str = Field("", description="subject line of the delivery message a buyer receives")
    delivery_body: str = Field("", description="short delivery message: thanks, how to open the product, how to get help. "
                                              "Use the placeholder {{ACCESS_LINK}} for the link")


def run(run, product: dict) -> Output:
    return run_agent(run, ROLE, "draft_delivery_message", Output, {"product": product}, max_tokens=500)


def run_sale_to_cash_checks(store: payments.Store, queue: ApprovalQueue, product_id: str, price_cents: int,
                            approve: Callable[[object], object | None]) -> list[dict]:
    """Run the MOCKED sale-to-cash scenario. `approve(action)` asks whoever is in charge
    (the founder in a real run) and returns an ApprovalRecord, or None if they reject."""
    results: list[dict] = []

    def record(name: str, passed: bool, detail: str) -> None:
        results.append({"check": name, "passed": bool(passed), "detail": detail})

    # 0. Without approval, delivery must refuse.
    order0 = payments.create_checkout(store, product_id, price_cents, "test-buyer-0")
    event0 = payments.mock_payment_event(store, order0["id"])
    try:
        webhooks.handle_event(store, queue, event0)
        record("delivery_blocked_without_approval", False, "delivery ran without founder approval")
    except ApprovalRequired as exc:
        record("delivery_blocked_without_approval", True, f"refused as expected: {exc}")

    # Founder turns on auto-delivery for this product.
    action = queue.propose("deliver", f"Enable MOCKED auto-delivery for product '{product_id}' after each mock payment",
                           delivery.auto_delivery_payload(product_id))
    approval = approve(action)
    if approval is None:
        record("auto_delivery_enabled", False, "the founder rejected auto-delivery, so the remaining checks did not run")
        return results
    delivery.enable_auto_delivery(store, queue, action, approval, product_id)
    record("auto_delivery_enabled", True, f"approved by {approval.approved_by}")

    # 1. Payment triggers delivery (replaying the held event from step 0 now succeeds, once).
    outcome = webhooks.handle_event(store, queue, event0)
    record("payment_triggers_delivery", outcome == "delivered" and delivery.has_access(store, order0["id"]),
           f"webhook outcome: {outcome}; access link: {store.access.get(order0['id'], {}).get('link')}")

    # 2. Idempotency: the same event again must not deliver twice.
    before = len(store.deliveries)
    outcome = webhooks.handle_event(store, queue, event0)
    record("duplicate_webhook_single_delivery", outcome == "duplicate_ignored" and len(store.deliveries) == before,
           f"replayed event {event0['id']}: {outcome}; deliveries stayed at {before}")

    # 3. A tampered event is rejected.
    order1 = payments.create_checkout(store, product_id, price_cents, "test-buyer-1")
    forged = dict(payments.mock_payment_event(store, order1["id"]), amount_cents=1)
    outcome = webhooks.handle_event(store, queue, forged)
    record("bad_signature_rejected", outcome == "rejected_bad_signature" and not delivery.has_access(store, order1["id"]),
           f"tampered event: {outcome}")

    # 4. Refund needs approval, then revokes access.
    refund_action = refunds.propose_refund(queue, order0["id"])
    try:
        refunds.refund(store, queue, refund_action, None, order0["id"])
        record("refund_blocked_without_approval", False, "refund ran without founder approval")
    except ApprovalRequired as exc:
        record("refund_blocked_without_approval", True, f"refused as expected: {exc}")
    refund_approval = approve(refund_action)
    if refund_approval is None:
        record("refund_revokes_access", False, "the founder rejected the test refund, so this check did not run")
    else:
        outcome = refunds.refund(store, queue, refund_action, refund_approval, order0["id"])
        record("refund_revokes_access", outcome == "access_revoked" and not delivery.has_access(store, order0["id"]),
               f"refund outcome: {outcome}; buyer still has access: {delivery.has_access(store, order0['id'])}")

    # 5. Reconciliation matches orders, payments, fees, refunds and payouts (after a second, kept sale).
    webhooks.handle_event(store, queue, payments.mock_payment_event(store, order1["id"]))
    payments.mock_payout(store)
    report = reconcile.reconcile(store)
    record("reconciliation_matches", report["matched"],
           f"gross {report['gross_cents']}c - fees {report['fees_cents']}c - refunds {report['refunded_cents']}c = "
           f"expected payout {report['expected_payout_cents']}c; paid out {report['paid_out_cents']}c; "
           f"mismatches: {report['mismatches'] or 'none'}")

    # 6. Reconciliation notices a problem when one is injected.
    store.payouts.append({"id": "payout_mock_injected_error", "amount_cents": 5, "payment_ids": [], "refund_ids": [],
                          "mocked": True})
    broken = reconcile.reconcile(store)
    store.payouts.pop()
    record("reconciliation_detects_mismatch", not broken["matched"],
           f"injected a 5c payout error; reported: {broken['mismatches']}")
    return results


def checks_markdown(results: list[dict], approver: str, product_id: str, price_cents: int) -> str:
    lines = [
        "# Payment and delivery test log (MOCKED)",
        "",
        "Everything in this log is **MOCKED**. No payment provider, real or sandbox, was contacted. "
        "No money moved and nothing was delivered to anyone.",
        "",
        f"- Product id: `{product_id}`",
        f"- Mock price: {price_cents} cents",
        f"- Approvals in this run were given by: **{approver}**",
        "",
        "| # | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        detail = str(r["detail"]).replace("|", "/")
        lines.append(f"| {i} | {r['check']} | {'PASS' if r['passed'] else 'FAIL'} | {detail} |")
    passed = sum(r["passed"] for r in results)
    lines += ["", f"**{passed} of {len(results)} checks passed.**", ""]
    return "\n".join(lines)
