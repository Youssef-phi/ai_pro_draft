"""Phase 1 (Discover): define the market and write the Mom Test interview plan."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "market_analyst"


class Output(AgentOutput):
    market_definition: str = Field("", description="who is in the market and who is not, in plain words")
    segments: list[str] = Field(default_factory=list, description="2-3 customer segments, the first one to target first")
    competitors: list[dict] = Field(default_factory=list, description=(
        'existing alternatives: [{"name": str, "note": str, "source_url": URL from the evidence or null}]'))
    demand_signals: list[str] = Field(default_factory=list, description="signals for AND against real demand found in the evidence")
    interview_plan: str = Field("", description="who to interview, how many (at least 5), and where to find them")
    mom_test_questions: list[str] = Field(default_factory=list, description=(
        "8 Mom Test questions: about past behaviour and real costs, never 'would you buy this?'"))


def run(run, brief: dict, sharpened_idea: str, target_customer: str, evidence_pack: list[dict]) -> Output:
    return run_agent(run, ROLE, "define_market_and_interview_plan", Output,
                     {"founder_brief": brief, "sharpened_idea": sharpened_idea,
                      "target_customer": target_customer, "evidence_pack": evidence_pack})
