"""Phase 6 (Operate and learn): support answers, metrics to track, and the persevere-or-pivot memo."""
from __future__ import annotations

from pydantic import Field

from agents.base import run_agent
from schemas import AgentOutput

ROLE = "ops_analyst"


class Output(AgentOutput):
    support_faq: list[dict] = Field(default_factory=list, description='4 support answers: [{"q": str, "a": str}]')
    metrics_to_track: list[str] = Field(default_factory=list, description="5 metrics, each with how the founder measures it for free")
    recommendation: str = Field("", description="one of: persevere, pivot, stop. Base it ONLY on the real evidence given")
    memo: str = Field("", description=(
        "the persevere-or-pivot memo, 6-10 sentences: what real evidence exists, what is still an assumption, "
        "what is mocked, and what the founder should do in the next two weeks"))


def run(run, brief: dict, evidence: dict) -> Output:
    return run_agent(run, ROLE, "operate_and_learn_memo", Output,
                     {"founder_brief": brief, "real_evidence_and_status": evidence}, max_tokens=1500)
