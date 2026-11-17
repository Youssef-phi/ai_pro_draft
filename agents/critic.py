"""The board's Critic: the strongest reasons NOT to go on, plus the best pivot."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "critic"


class Output(AgentOutput):
    case: str = Field("", description="the strongest reasons NOT to proceed, 4-6 sentences. Finding kill reasons is your job")
    kill_reasons: list[str] = Field(default_factory=list, description="up to 4 reasons, most serious first")
    best_pivot: str = Field("", description="the single best pivot: a different allowed DIGITAL product or customer, in one sentence")


def run(run, dossier: dict, opponent_case: str | None = None) -> Output:
    context = {"dossier": dossier}
    if opponent_case:
        context["advocate_case_to_rebut"] = opponent_case
    return run_agent(run, ROLE, f"critic_phase{dossier['phase']}" + ("_rebuttal" if opponent_case else ""),
                     Output, context, max_tokens=800)
