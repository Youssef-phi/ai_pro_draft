"""The board's neutral Chair: scores a fixed rubric 0-4 and recommends go / repeat / pivot / stop.
The Chair only recommends. gates.py can make the outcome stricter, and the founder decides."""
from __future__ import annotations

from pydantic import Field, field_validator

from agents.base import run_agent
from gates import RUBRIC
from schemas import VERDICTS, AgentOutput

ROLE = "chair"


class Output(AgentOutput):
    scores: dict = Field(default_factory=dict, description=(
        "object with an integer 0-4 for each of: " + ", ".join(RUBRIC) +
        ". Score what the EVIDENCE supports; a point backed only by assumptions scores 0-1"))
    verdict: str = Field("repeat", description="one of: go, repeat, pivot, stop")
    explanation: str = Field("", description="why, in 3-5 plain sentences the founder can act on")
    warning: str = Field("", description="what the founder risks if they override this verdict")

    @field_validator("verdict", mode="after")
    @classmethod
    def _verdict(cls, value: str) -> str:
        value = (value or "").strip().lower()
        return value if value in VERDICTS else "repeat"

    @field_validator("scores", mode="after")
    @classmethod
    def _scores(cls, value: dict) -> dict:
        clean = {}
        for key in RUBRIC:
            try:
                clean[key] = max(0, min(4, int(float(value.get(key, 0)))))
            except (TypeError, ValueError):
                clean[key] = 0
        return clean


class SingleOutput(Output):
    """PANEL_MODE=single: one model call argues both sides, then rules."""
    advocate_case: str = Field("", description="first: the strongest honest case FOR proceeding, 3-4 sentences")
    critic_case: str = Field("", description="second: the strongest case AGAINST proceeding, 3-4 sentences")
    best_pivot: str = Field("", description="the single best pivot to a different allowed digital product or customer")


def run(run, dossier: dict, advocate_case: dict, critic_case: dict) -> Output:
    return run_agent(run, ROLE, f"chair_ruling_phase{dossier['phase']}", Output,
                     {"dossier": dossier, "advocate": advocate_case, "critic": critic_case}, max_tokens=900)


def run_single(run, dossier: dict) -> SingleOutput:
    return run_agent(run, ROLE, f"single_panel_review_phase{dossier['phase']}", SingleOutput,
                     {"dossier": dossier}, max_tokens=1200, prompt_name="chair_single", speak=False)
