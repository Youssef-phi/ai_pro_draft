"""Phase 5 (Launch): store page copy and launch posts. Drafts only; publishing needs founder approval."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "marketer"


class Output(AgentOutput):
    store_title: str = Field("", description="store page title")
    store_tagline: str = Field("", description="one honest sentence")
    store_description: str = Field("", description="3-5 sentences on what the buyer gets and who it is for")
    store_bullets: list[str] = Field(default_factory=list, description="4 concrete things included")
    faq: list[dict] = Field(default_factory=list, description='3 entries: [{"q": str, "a": str}]')
    launch_posts: list[dict] = Field(default_factory=list, description=(
        '2-3 draft launch posts written in the product\'s own voice, never as the founder or a customer: '
        '[{"channel": str, "text": str}]'))


def run(run, brief: dict, product: dict, price_usd: float) -> Output:
    return run_agent(run, ROLE, "open_the_store", Output,
                     {"founder_brief": brief, "product": product, "price_usd": price_usd}, max_tokens=1500)
