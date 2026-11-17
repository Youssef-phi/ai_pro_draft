"""Nothing goes out without founder approval: the side-effecting functions raise."""
import dataclasses

import pytest

import actions
import delivery
import payments
import refunds
import webhooks
from approval import ApprovalQueue, ApprovalRecord, ApprovalRequired
from orchestrator import Run
from stub_llm import ScriptedFounder, StubLLM, stub_research


def test_publish_raises_without_approval(tmp_path):
    queue = ApprovalQueue()
    action = queue.propose("publish", "landing page", "<html><body>hi</body></html>")
    with pytest.raises(ApprovalRequired):
        actions.publish(queue, action, None, "<html><body>hi</body></html>", tmp_path / "page.html")
    assert not (tmp_path / "page.html").exists()


def test_send_raises_without_approval(tmp_path):
    queue = ApprovalQueue()
    message = {"to": "x", "subject": "s", "body": "b"}
    action = queue.propose("send", "email", message)
    with pytest.raises(ApprovalRequired):
        actions.send(queue, action, None, message, tmp_path / "outbox.md")
    assert not (tmp_path / "outbox.md").exists()


def test_deliver_and_refund_raise_without_approval():
    queue, store = ApprovalQueue(), payments.Store()
    order = payments.create_checkout(store, "p1", 1900)
    with pytest.raises(ApprovalRequired):
        webhooks.handle_event(store, queue, payments.mock_payment_event(store, order["id"]))
    assert not delivery.has_access(store, order["id"])
    action = refunds.propose_refund(queue, order["id"])
    with pytest.raises(ApprovalRequired):
        refunds.refund(store, queue, action, None, order["id"])


def test_forged_changed_or_rejected_approvals_are_refused(tmp_path):
    queue = ApprovalQueue()
    action = queue.propose("publish", "page", "original")
    forged = ApprovalRecord(action.id, "founder", action.digest, "2026-11-17T00:00:00Z", "not-a-real-signature")
    with pytest.raises(ApprovalRequired):
        actions.publish(queue, action, forged, "original", tmp_path / "a.md")

    record = queue.approve(action.id)
    with pytest.raises(ApprovalRequired):                 # content changed after approval
        actions.publish(queue, action, record, "something else", tmp_path / "a.md")
    with pytest.raises(ApprovalRequired):                 # approval for a different action
        other = queue.propose("publish", "page 2", "original")
        actions.publish(queue, other, record, "original", tmp_path / "a.md")
    with pytest.raises(ApprovalRequired):                 # not the founder
        actions.publish(queue, action, dataclasses.replace(record, approved_by="agent"), "original", tmp_path / "a.md")
    assert actions.publish(queue, action, record, "original", tmp_path / "a.md").exists()

    rejected = queue.propose("publish", "page 3", "x")
    queue.reject(rejected.id)
    with pytest.raises(ApprovalRequired):
        queue.approve(rejected.id)


def test_pipeline_publishes_nothing_when_founder_rejects(tmp_path):
    brief = {"idea": "An onboarding checklist for freelance web designers"}
    run = Run(brief, ScriptedFounder(actions="reject"), llm=StubLLM(), research=stub_research,
              out_dir=tmp_path / "outputs", log_path=tmp_path / "log.json")
    run.execute()
    names = {p.name for p in (tmp_path / "outputs").iterdir()}
    assert not any("published" in n or "outbox" in n for n in names), names
    assert all(a.status == "rejected" for a in run.approvals.all())
    assert not run.store.deliveries


def test_every_approved_action_is_logged_as_founder(tmp_path):
    run = Run({"idea": "An onboarding checklist for freelance web designers"}, ScriptedFounder(), llm=StubLLM(),
              research=stub_research, out_dir=tmp_path / "outputs", log_path=tmp_path / "log.json")
    run.execute()
    approved = [e for e in run.log.read() if e["action"].endswith("_approved")]
    assert len(approved) >= 5 and all(e["approved_by"] == "founder" and e["mocked"] for e in approved)
