"""Phase 1 (Discover): sharpen the idea and score it against alternatives, using the evidence pack."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "researcher"


class Output(AgentOutput):
    sharpened_idea: str = Field("", description="the idea in one precise sentence: who it is for, what problem, what digital product")
    target_customer: str = Field("", description="the specific first customer")
    problem: str = Field("", description="the problem, and how people cope with it today")
    opportunities: list[dict] = Field(default_factory=list, description=(
        'the starting idea plus 2 alternative digital product ideas for the same founder, each '
        '{"name": str, "description": str, "score": 0-10, "why": str}; score honestly against the evidence'))
    recommended: str = Field("", description="name of the opportunity you recommend, and why, in one sentence")
    evidence_gaps: list[str] = Field(default_factory=list, description="what we still do not know")


def run(run, brief: dict, idea: str, evidence_pack: list[dict]) -> Output:
    return run_agent(run, ROLE, "find_opportunities", Output,
                     {"founder_brief": brief, "idea": idea, "evidence_pack": evidence_pack})
