"""Gates: evidence thresholds fixed in code BEFORE the evidence comes in.

The Chair (an LLM) only recommends. This file can make the outcome stricter, never
softer: a GO can be turned into repeat, pivot or stop, but a stop is never turned
into a go. The founder then approves or overrides, and that is logged.

Outcomes, mildest to strictest: go < repeat < pivot < stop.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import config

SEVERITY = {"go": 0, "repeat": 1, "pivot": 2, "stop": 3}
RUBRIC = (
    "problem_severity",          # evidence-backed
    "market_and_demand",
    "competition_and_differentiation",
    "founder_fit",               # skills, budget, time
    "feasibility_digital",       # as a digital product in the timeframe
    "values_and_rules_fit",
)


def thresholds() -> dict:
    """Shown to the founder at the start of every run, before any evidence exists."""
    return {
        1: {"min_sourced_claims": config.env_int("MIN_SOURCED_CLAIMS", 3)},
        2: {"waitlist_target": config.env_int("WAITLIST_TARGET", 100),
            "waitlist_days": config.env_int("WAITLIST_DAYS", 14)},
        3: {"mvp_tests_must_pass": True},
        4: {"price_set": True, "policies_labelled_draft": True},
        5: {"sale_to_cash_tests_must_pass": True},
        6: {"memo_written": True},
        "chair_average_for_go": 2.5,
    }


@dataclass
class Check:
    name: str
    target: str
    actual: str
    passed: bool


@dataclass
class GateResult:
    phase: int
    chair_verdict: str
    chair_average: float
    outcome: str
    overridden_by_code: bool
    checks: list[Check] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _stricter(a: str, b: str) -> str:
    return a if SEVERITY[a] >= SEVERITY[b] else b


def evaluate(phase: int, evidence: dict, chair_verdict: str, chair_scores: dict | None, attempt: int = 1) -> GateResult:
    """Combine the Chair's recommendation with the hard checks for this phase."""
    t = thresholds()
    verdict = chair_verdict if chair_verdict in SEVERITY else "repeat"
    scores = [max(0, min(4, int(v))) for v in (chair_scores or {}).values() if isinstance(v, (int, float))]
    average = round(sum(scores) / len(scores), 2) if scores else 0.0
    required, checks, reasons = "go", [], []

    def check(name: str, target, actual, passed: bool, on_fail: str, why: str) -> None:
        nonlocal required
        checks.append(Check(name, str(target), str(actual), passed))
        if not passed:
            required = _stricter(required, on_fail)
            reasons.append(why)

    # The Chair's own scores must support a GO (assumption-only cases score low).
    if scores:
        floor = "stop" if average < 1.5 else "pivot" if average < 2.0 else "repeat" if average < t["chair_average_for_go"] else "go"
        check("chair_rubric_average", f">= {t['chair_average_for_go']} of 4", average, floor == "go", floor,
              f"The Chair's rubric average is {average} of 4, below the {t['chair_average_for_go']} needed for GO.")
    else:
        check("chair_rubric_average", f">= {t['chair_average_for_go']} of 4", "no scores", False, "repeat",
              "The Chair returned no usable scores.")

    if phase == 1:
        need, got = t[1]["min_sourced_claims"], int(evidence.get("sourced_claims", 0))
        check("sourced_market_claims", f">= {need}", got, got >= need, "repeat",
              f"Only {got} market claim(s) have a source URL; {need} are required. The rest are assumptions.")
    elif phase == 2:
        target, got = t[2]["waitlist_target"], evidence.get("waitlist_signups")
        if got is None:
            check("waitlist_signups", f">= {target} in {t[2]['waitlist_days']} days", "not reported", False, "repeat",
                  "No demand result has been reported yet. Run the landing-page test and report the real number.")
        else:
            got = int(got)
            ratio = got / target if target else 0
            on_fail = "repeat" if ratio >= 0.5 else "pivot" if ratio >= 0.25 else "stop"
            check("waitlist_signups", f">= {target} in {t[2]['waitlist_days']} days", got, got >= target, on_fail,
                  f"The demand test got {got} sign-ups against a target of {target} set in advance "
                  f"({ratio:.0%}). The target was missed; this is not evidence of demand.")
    elif phase == 3:
        passed, total = int(evidence.get("tests_passed", 0)), int(evidence.get("tests_total", 0))
        check("mvp_tests", "all pass", f"{passed}/{total}", total > 0 and passed == total, "repeat",
              f"MVP checks: {passed} of {total} passed.")
    elif phase == 4:
        check("price_set", "a price above 0", evidence.get("price_usd"), float(evidence.get("price_usd") or 0) > 0,
              "repeat", "No usable price was set.")
        check("policies_labelled_draft", "DRAFT label on every policy", evidence.get("policies_labelled_draft"),
              bool(evidence.get("policies_labelled_draft")), "repeat", "A policy is missing its DRAFT label.")
    elif phase == 5:
        passed, total = int(evidence.get("sale_tests_passed", 0)), int(evidence.get("sale_tests_total", 0))
        check("sale_to_cash_tests (MOCKED)", "all pass", f"{passed}/{total}", total > 0 and passed == total, "repeat",
              f"Mocked sale-to-cash checks: {passed} of {total} passed.")
    elif phase == 6:
        check("memo_written", "persevere-or-pivot memo exists", evidence.get("memo_written"),
              bool(evidence.get("memo_written")), "repeat", "The persevere-or-pivot memo is missing.")

    # A second failed attempt at the same phase is not repeated again.
    if required == "repeat" and attempt >= 2:
        required = "stop"
        reasons.append("This phase already had a repeat and still fails its checks.")

    outcome = _stricter(verdict, required)
    return GateResult(phase, verdict, average, outcome, outcome != verdict, checks, reasons)
