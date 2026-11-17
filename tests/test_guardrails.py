"""Trick prompts from evals/ must be refused or stopped; ordinary requests must pass."""
import json
from pathlib import Path

import pytest

import guardrails

EVALS = json.loads((Path(__file__).resolve().parent.parent / "evals" / "trick_prompts.json").read_text())


@pytest.mark.parametrize("case", EVALS["must_refuse"], ids=lambda c: c["prompt"][:40])
def test_must_never_requests_are_refused(case):
    result = guardrails.prefilter(case["prompt"])
    assert result.blocked and result.kind == "must_never"
    assert case["rule"] in [v.rule for v in result.violations]


@pytest.mark.parametrize("case", EVALS["must_stop_excluded_product"], ids=lambda c: c["prompt"][:40])
def test_excluded_products_are_stopped(case):
    result = guardrails.prefilter(case["prompt"])
    assert result.blocked and result.kind == "excluded_product"
    assert case["rule"] in [v.rule for v in result.violations]
    assert "pivot" in result.recommendation.lower()


@pytest.mark.parametrize("prompt", EVALS["must_allow"])
def test_ordinary_requests_pass(prompt):
    assert not guardrails.prefilter(prompt).blocked


@pytest.mark.parametrize("text", EVALS["forbidden_in_agent_output"])
def test_forbidden_agent_output_is_removed(text):
    clean, violations = guardrails.sanitize("This is a fine sentence. " + text + " And another fine one.")
    assert violations
    assert not guardrails.scan_output(clean)
    assert "fine sentence" in clean


@pytest.mark.parametrize("text", EVALS["allowed_in_agent_output"])
def test_honest_agent_output_is_kept(text):
    clean, violations = guardrails.sanitize(text)
    assert clean == text and not violations
