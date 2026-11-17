"""Phase 2 (Validate): Lean Canvas, then the copy for a demand-test landing page."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "strategist"
CANVAS_BLOCKS = ("problem", "customer_segments", "unique_value_proposition", "solution", "channels",
                 "revenue_streams", "cost_structure", "key_metrics", "unfair_advantage")


class Output(AgentOutput):
    lean_canvas: dict = Field(default_factory=dict, description=(
        "object with these keys, each a short string: " + ", ".join(CANVAS_BLOCKS)))
    landing_headline: str = Field("", description="landing page headline, honest, under 12 words")
    landing_subheadline: str = Field("", description="one sentence saying who it is for and what it does")
    landing_bullets: list[str] = Field(default_factory=list, description="3 concrete benefits; no numbers you cannot source, no testimonials, no urgency")
    landing_cta: str = Field("", description='button text for joining the waitlist, e.g. "Join the waitlist"')
    waitlist_plan: str = Field("", description="where the founder could share the page to reach the target customer, within their budget and time")


def run(run, brief: dict, discovery: dict, waitlist_target: int, waitlist_days: int) -> Output:
    return run_agent(run, ROLE, "design_the_business", Output,
                     {"founder_brief": brief, "discovery": discovery,
                      "demand_test": {"waitlist_target": waitlist_target, "days": waitlist_days,
                                      "note": "target is fixed in code before the test runs"}})
