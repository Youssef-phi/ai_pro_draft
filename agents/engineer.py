"""Phase 3 (Build): specify a small digital MVP and its user docs. Code renders and tests it."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "engineer"


class Output(AgentOutput):
    product_name: str = Field("", description="a plain, original product name (no existing brand names)")
    product_type: str = Field("", description="one of: checklist, guide, template_pack, planner")
    summary: str = Field("", description="what the buyer gets, in two sentences")
    modules: list[dict] = Field(default_factory=list, description=(
        '3-5 modules of the product: [{"title": str, "items": [5-8 concrete, useful, specific steps or entries]}]. '
        "This IS the product content, so make each item genuinely usable"))
    user_docs: list[str] = Field(default_factory=list, description="4-6 numbered steps: how a buyer uses the product")
    test_cases: list[str] = Field(default_factory=list, description="3-5 things a human should check before shipping")
    out_of_scope: list[str] = Field(default_factory=list, description="what this MVP deliberately leaves out")


def run(run, brief: dict, business: dict) -> Output:
    return run_agent(run, ROLE, "build_the_product", Output, {"founder_brief": brief, "business": business},
                     max_tokens=2400)
