"""MOCKED refunds. A refund is never issued by the system on its own: refund() raises
ApprovalRequired unless the founder approved that exact refund. No money moves; the
mock refund event revokes the buyer's access through the webhook handler.
"""
from __future__ import annotations

import webhooks
from approval import Action, ApprovalQueue, ApprovalRecord
from payments import Store, mock_refund_event

MOCKED = True


def refund_payload(order_id: str) -> dict:
    return {"refund_order": order_id}


def propose_refund(queue: ApprovalQueue, order_id: str) -> Action:
    return queue.propose("refund", f"MOCKED refund of order {order_id} (revokes access; no money moves)",
                         refund_payload(order_id))


def refund(store: Store, queue: ApprovalQueue, action: Action, record: ApprovalRecord | None, order_id: str) -> str:
    queue.verify(record, action.id, refund_payload(order_id))
    if store.orders[order_id]["status"] != "paid":
        raise ValueError(f"order {order_id} is not in a refundable state")
    return webhooks.handle_event(store, queue, mock_refund_event(store, order_id))
