"""Side-effecting actions: publish() and send(). Both are MOCKED and both refuse to
run without a valid founder approval record (see approval.py).

MOCKED means nothing leaves this machine: "publish" writes an HTML/Markdown file
into the run's outputs folder, and "send" appends the message to a local outbox log.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from approval import Action, ApprovalQueue, ApprovalRecord

MOCK_BANNER_HTML = ('<div style="background:#fde68a;color:#111;padding:8px 12px;font:600 13px system-ui;'
                    'text-align:center">MOCKED PUBLISH: this page was written to a local file. '
                    'Nothing was posted online.</div>')


def publish(queue: ApprovalQueue, action: Action, record: ApprovalRecord | None, content: str,
            destination: Path) -> Path:
    """MOCKED publish: write `content` to a local file. Raises ApprovalRequired without approval."""
    queue.verify(record, action.id, content)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix == ".html":
        content = content.replace("<body>", "<body>" + MOCK_BANNER_HTML, 1)
    else:
        content = "> MOCKED PUBLISH: written to a local file only. Nothing was posted online.\n\n" + content
    destination.write_text(content, encoding="utf-8")
    return destination


def send(queue: ApprovalQueue, action: Action, record: ApprovalRecord | None, message: dict,
         outbox: Path) -> Path:
    """MOCKED send: append the message to a local outbox log. Raises ApprovalRequired without approval."""
    queue.verify(record, action.id, message)
    outbox.parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with outbox.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## MOCKED SEND at {stamp} (nothing was actually sent)\n\n"
                 f"- To: {message.get('to', '(recipient placeholder)')}\n"
                 f"- Subject: {message.get('subject', '')}\n\n{message.get('body', '')}\n")
    return outbox
