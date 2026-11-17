"""MOCKED sale to cash: payment triggers delivery, duplicates are ignored, refunds revoke, books reconcile."""
import delivery
import payments
import reconcile
import refunds
import webhooks
from agents import sales_ops
from approval import ApprovalQueue


def ready_store():
    queue, store = ApprovalQueue(), payments.Store()
    action = queue.propose("deliver", "enable auto-delivery", delivery.auto_delivery_payload("p1"))
    delivery.enable_auto_delivery(store, queue, action, queue.approve(action.id), "p1")
    return queue, store


def test_payment_triggers_delivery_and_duplicate_webhook_delivers_once():
    queue, store = ready_store()
    order = payments.create_checkout(store, "p1", 1900)
    event = payments.mock_payment_event(store, order["id"])
    assert webhooks.handle_event(store, queue, event) == "delivered"
    assert webhooks.handle_event(store, queue, event) == "duplicate_ignored"
    assert webhooks.handle_event(store, queue, dict(event)) == "duplicate_ignored"
    assert len(store.deliveries) == 1 and delivery.has_access(store, order["id"])


def test_tampered_event_is_rejected():
    queue, store = ready_store()
    order = payments.create_checkout(store, "p1", 1900)
    event = dict(payments.mock_payment_event(store, order["id"]), amount_cents=1)
    assert webhooks.handle_event(store, queue, event) == "rejected_bad_signature"
    assert not store.deliveries


def test_refund_revokes_access():
    queue, store = ready_store()
    order = payments.create_checkout(store, "p1", 1900)
    webhooks.handle_event(store, queue, payments.mock_payment_event(store, order["id"]))
    action = refunds.propose_refund(queue, order["id"])
    assert refunds.refund(store, queue, action, queue.approve(action.id), order["id"]) == "access_revoked"
    assert not delivery.has_access(store, order["id"])
    assert store.orders[order["id"]]["status"] == "refunded"


def test_reconciliation_matches_then_detects_a_mismatch():
    queue, store = ready_store()
    for buyer in ("b1", "b2"):
        order = payments.create_checkout(store, "p1", 1900, buyer)
        webhooks.handle_event(store, queue, payments.mock_payment_event(store, order["id"]))
    payments.mock_payout(store)
    report = reconcile.reconcile(store)
    assert report["matched"] and report["expected_payout_cents"] == 2 * (1900 - 85)
    store.payouts[0]["amount_cents"] += 100
    assert not reconcile.reconcile(store)["matched"]


def test_full_scenario_passes_and_is_labelled_mocked():
    queue, store = ApprovalQueue(), payments.Store()
    results = sales_ops.run_sale_to_cash_checks(store, queue, "p1", 1900,
                                                approve=lambda a: queue.approve(a.id, approved_by="test-harness"))
    assert results and all(r["passed"] for r in results), results
    text = sales_ops.checks_markdown(results, "the automated test harness", "p1", 1900)
    assert "MOCKED" in text and "FAIL" not in text


def test_scenario_stops_when_delivery_is_not_approved():
    queue, store = ApprovalQueue(), payments.Store()
    results = sales_ops.run_sale_to_cash_checks(store, queue, "p1", 1900, approve=lambda a: None)
    assert not store.deliveries
    assert results[-1]["check"] == "auto_delivery_enabled" and not results[-1]["passed"]
