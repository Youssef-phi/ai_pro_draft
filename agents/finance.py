"""Phase 4 (Commercial setup): set the price. No payments are set up anywhere."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "finance"


class Output(AgentOutput):
    price_usd: float = Field(0.0, description="the recommended launch price in USD, a number only")
    pricing_model: str = Field("", description="one of: one-time purchase, pay-what-you-want with a minimum, subscription")
    rationale: str = Field("", description="why this price: alternatives' prices from the evidence (cite) or stated assumptions")
    options_considered: list[str] = Field(default_factory=list, description="2-3 other price points and why they were not chosen")
    break_even: str = Field("", description="how many sales cover the founder's stated budget, shown as arithmetic; no revenue forecast")


def run(run, brief: dict, product: dict, competitors: list) -> Output:
    return run_agent(run, ROLE, "set_the_price", Output,
                     {"founder_brief": brief, "product": product, "competitors": competitors}, max_tokens=900)
