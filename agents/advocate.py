"""The board's Advocate: the strongest honest case for going on, built on the evidence."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "advocate"


class Output(AgentOutput):
    case: str = Field("", description="the strongest HONEST case for proceeding, 4-6 sentences, built on the evidence")
    strongest_points: list[str] = Field(default_factory=list, description="up to 4 points, each tied to evidence or marked as assumption")
    weakest_point_admitted: str = Field("", description="the weakest part of your own case")


def run(run, dossier: dict, opponent_case: str | None = None) -> Output:
    context = {"dossier": dossier}
    if opponent_case:
        context["critic_case_to_rebut"] = opponent_case
    return run_agent(run, ROLE, f"advocate_phase{dossier['phase']}" + ("_rebuttal" if opponent_case else ""),
                     Output, context, max_tokens=800)
