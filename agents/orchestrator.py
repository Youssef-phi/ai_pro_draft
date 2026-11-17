"""Chief of staff. The routing itself is code (orchestrator.py at the repo root); this agent
restates the brief, flags what is missing, and writes the research queries for Phase 1."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "orchestrator"


class Output(AgentOutput):
    brief_summary: str = Field("", description="the founder's brief restated in 2-3 plain sentences")
    missing_information: list[str] = Field(default_factory=list, description="brief fields that are empty or vague")
    search_queries: list[str] = Field(default_factory=list, description=(
        "exactly 3 short web search queries (3-7 words each) to find evidence about the problem, "
        "the existing alternatives and the market"))


def run(run, brief: dict, idea: str) -> Output:
    return run_agent(run, ROLE, "kickoff_and_plan_research", Output, {"founder_brief": brief, "idea": idea},
                     max_tokens=500)
