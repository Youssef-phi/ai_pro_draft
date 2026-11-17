"""Phase 4 (Commercial setup): DRAFT terms, privacy and refund policy. Not legal advice."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "policy_drafter"
DRAFT_LABEL = "DRAFT, not legal advice; have a lawyer review."


class Output(AgentOutput):
    terms: str = Field("", description="short plain-language terms of use for this digital product (6-10 sentences)")
    privacy: str = Field("", description="short plain-language privacy policy: what is collected, why, how to delete it")
    refund_policy: str = Field("", description="short refund policy: window, how to ask, that a refund ends access")


def run(run, brief: dict, product: dict, price_usd: float) -> Output:
    return run_agent(run, ROLE, "draft_policies", Output,
                     {"founder_brief": brief, "product": product, "price_usd": price_usd}, max_tokens=1400)
