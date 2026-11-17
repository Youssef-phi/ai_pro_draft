"""Shared agent runner.

Every agent call goes through run_agent(), which:
  1. builds the prompt from prompts/_shared_rules.md + prompts/<role>.md + the output schema,
  2. gives the agent ONLY the narrow context passed in (no shared transcript),
  3. validates the reply against the agent's Pydantic model,
  4. re-labels claims in code: a claim is SOURCED only if its URL was really retrieved by the
     research tools (or given by the founder) in this run; everything else becomes ASSUMPTION,
  5. strips anything that breaks a must-never rule,
  6. writes one decision-log entry and emits the spoken line for the boardroom.
"""
from __future__ import annotations

from functools import lru_cache
from typing import TypeVar

from pydantic import ValidationError

import config
import guardrails
from schemas import AgentOutput, Claim, compact, schema_hint
from tools import normalize_url

T = TypeVar("T", bound=AgentOutput)


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (config.ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")


def enforce_claims(claims: list[Claim], known_urls: set[str]) -> list[Claim]:
    """Code, not the model, decides the label. Unknown or missing URL -> ASSUMPTION."""
    checked = []
    for claim in claims:
        if not claim.text.strip():
            continue
        url = normalize_url(claim.source_url or "")
        if url.startswith("http") and url in known_urls:
            checked.append(Claim(text=claim.text, source_url=url, label="SOURCED"))
        else:
            checked.append(Claim(text=claim.text, source_url=None, label="ASSUMPTION"))
    return checked


def run_agent(run, role: str, action: str, model_cls: type[T], context: dict, max_tokens: int = 1800,
              prompt_name: str | None = None, speak: bool = True) -> T:
    system = "\n\n".join((load_prompt("_shared_rules"), load_prompt(prompt_name or role), schema_hint(model_cls)))
    user = "INPUT (JSON):\n" + compact(context, 9000)
    result = run.llm.chat_json(role, system, user, max_tokens=max_tokens)

    invalid = False
    try:
        out = model_cls.model_validate(result.data)
    except ValidationError:
        invalid = True
        out = model_cls(speech="I could not produce a valid structured answer this time.", emotion="worried")

    clean, violations = guardrails.sanitize_tree(out.model_dump())
    out = model_cls.model_validate(clean)
    out.claims = enforce_claims(out.claims, run.known_urls)

    run.add_usage(result)
    run.log.append(
        agent=role, action=action,
        sources=sorted({c.source_url for c in out.claims if c.source_url}),
        model=result.model, cost=round(result.cost, 6), approved_by=None,
        provider=result.provider, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
        run_id=run.id,
        cost_estimated=True if result.cost_estimated else None,
        invalid_output=True if invalid else None,
        guardrail_removed=sorted({v.rule for v in violations}) or None,
    )
    if speak:
        run.speak(role, out.speech, out.emotion, out.claims, action=action, model=result.model)
    return out
