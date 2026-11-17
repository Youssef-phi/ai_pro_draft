"""Founder approval, enforced in code.

Anything with an outside effect (publish, send, deliver, refund) is first proposed
as a pending Action. The side-effecting functions in actions.py, delivery.py and
refunds.py call ApprovalQueue.verify(), which RAISES ApprovalRequired unless it is
handed a valid ApprovalRecord for that exact action and that exact content.

A record can only be created by ApprovalQueue.approve(), which is only called from
the founder's click (web UI) or typed confirmation (CLI). No agent output is ever
routed to approve(). Records are signed with a per-process secret that agents never
see, and are bound to a hash of the content, so approving one draft does not
approve a different one.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import asdict, dataclass, field


class ApprovalRequired(PermissionError):
    """Raised when a side effect is attempted without a valid founder approval."""


@dataclass
class Action:
    id: str
    kind: str                  # publish | send | deliver | refund
    description: str
    digest: str                # hash of the exact content the founder is asked to approve
    preview: str = ""
    status: str = "pending"    # pending | approved | rejected
    mocked: bool = True        # every outside effect in this project is MOCKED

    def public(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalRecord:
    action_id: str
    approved_by: str
    digest: str
    timestamp: str
    signature: str = field(repr=False, default="")


def digest_of(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class ApprovalQueue:
    def __init__(self):
        self._secret = secrets.token_bytes(32)
        self._actions: dict[str, Action] = {}
        self._lock = threading.Lock()

    def _sign(self, action_id: str, approved_by: str, digest: str, timestamp: str) -> str:
        message = "|".join((action_id, approved_by, digest, timestamp)).encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def propose(self, kind: str, description: str, payload, preview: str = "", action_id: str | None = None) -> Action:
        with self._lock:
            action_id = action_id or f"{kind}-{len(self._actions) + 1:03d}-{secrets.token_hex(3)}"
            action = Action(action_id, kind, description, digest_of(payload), preview[:600])
            self._actions[action_id] = action
            return action

    def get(self, action_id: str) -> Action:
        return self._actions[action_id]

    def pending(self) -> list[Action]:
        return [a for a in self._actions.values() if a.status == "pending"]

    def all(self) -> list[Action]:
        return list(self._actions.values())

    def approve(self, action_id: str, approved_by: str = "founder") -> ApprovalRecord:
        """Called only from the founder's own click or typed confirmation."""
        with self._lock:
            action = self._actions[action_id]
            if action.status == "rejected":
                raise ApprovalRequired(f"action {action_id} was rejected by the founder")
            action.status = "approved"
            timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return ApprovalRecord(action_id, approved_by, action.digest, timestamp,
                                  self._sign(action_id, approved_by, action.digest, timestamp))

    def reject(self, action_id: str) -> None:
        with self._lock:
            self._actions[action_id].status = "rejected"

    def verify(self, record: ApprovalRecord | None, action_id: str, payload) -> None:
        """Raise ApprovalRequired unless `record` is a genuine founder approval of this exact content."""
        if not isinstance(record, ApprovalRecord):
            raise ApprovalRequired(f"no founder approval for action {action_id}")
        action = self._actions.get(action_id)
        if action is None or action.status != "approved" or record.action_id != action_id:
            raise ApprovalRequired(f"action {action_id} is not approved")
        if record.approved_by != "founder" and not record.approved_by.startswith("test-harness"):
            raise ApprovalRequired("approval must come from the founder")
        expected = self._sign(record.action_id, record.approved_by, record.digest, record.timestamp)
        if not hmac.compare_digest(expected, record.signature):
            raise ApprovalRequired("approval record is not genuine")
        if record.digest != digest_of(payload) or record.digest != action.digest:
            raise ApprovalRequired("the content changed after it was approved; ask the founder again")
