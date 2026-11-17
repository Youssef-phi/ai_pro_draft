"""STUBBED LLM for smoke tests only.

A deterministic stand-in for a real model so the tests run with no network and no key.
It is never used to produce anything in outputs/ or decision_log.json.
"""
from __future__ import annotations

from llm import LLMResult

STUB_MODEL = "STUBBED-test-llm"
EVIDENCE = [
    {"title": "Stub source A", "url": "https://example.org/a", "snippet": "STUBBED evidence A", "source": "stub"},
    {"title": "Stub source B", "url": "https://example.org/b", "snippet": "STUBBED evidence B", "source": "stub"},
    {"title": "Stub source C", "url": "https://example.org/c", "snippet": "STUBBED evidence C", "source": "stub"},
]


def stub_research(queries):
    return [dict(item) for item in EVIDENCE]


def empty_research(queries):
    return []


class StubLLM:
    primary = "stub"

    def __init__(self, chair_verdict: str = "go", chair_score: int = 3):
        self.chair_verdict, self.chair_score, self.calls = chair_verdict, chair_score, []

    def describe(self) -> dict:
        return {"primary": "stub", "chain": ["stub"], "models": {}, "note": "STUBBED"}

    def chat_json(self, role, system, user, max_tokens=0, temperature=0.0) -> LLMResult:
        self.calls.append(role)
        data = dict(getattr(self, f"_{role}")(), **{"speech": f"STUBBED line from {role}.", "emotion": "thinking"})
        return LLMResult(data, "", STUB_MODEL, "stub", 100, 50, 0.0)

    def _orchestrator(self):
        return {"brief_summary": "STUBBED summary", "missing_information": [], "search_queries": ["q one", "q two", "q three"]}

    def _researcher(self):
        return {"sharpened_idea": "An onboarding checklist for freelance web designers", "target_customer": "freelance web designers",
                "problem": "Projects start without a clear scope", "recommended": "Onboarding checklist",
                "opportunities": [{"name": "Onboarding checklist", "description": "d", "score": 7, "why": "w"},
                                  {"name": "Proposal templates", "description": "d", "score": 5, "why": "w"},
                                  {"name": "Handover guide", "description": "d", "score": 4, "why": "w"}],
                "evidence_gaps": ["No interviews yet"],
                "claims": [{"text": "Claim A", "source_url": "https://example.org/a", "label": "SOURCED"},
                           {"text": "Claim B", "source_url": "https://example.org/b", "label": "SOURCED"},
                           {"text": "Claim C", "source_url": "https://example.org/c/", "label": "SOURCED"},
                           {"text": "Invented claim", "source_url": "https://invented.example/never-fetched", "label": "SOURCED"}]}

    def _market_analyst(self):
        return {"market_definition": "Freelance web designers", "segments": ["solo", "studios"],
                "competitors": [{"name": "Generic templates", "note": "free", "source_url": "https://example.org/a"}],
                "demand_signals": ["for: a", "against: b"], "interview_plan": "Talk to five designers",
                "mom_test_questions": ["When did this last happen?"] * 8,
                "claims": ["An unsourced market guess"]}

    def _strategist(self):
        return {"lean_canvas": {k: "x" for k in ("problem", "customer_segments", "unique_value_proposition", "solution",
                                                 "channels", "revenue_streams", "cost_structure", "key_metrics",
                                                 "unfair_advantage")},
                "landing_headline": "Start every client project with a clear scope",
                "landing_subheadline": "A checklist for freelance web designers",
                "landing_bullets": ["Scope", "Timeline", "Handover"], "landing_cta": "Join the waitlist",
                "waitlist_plan": "Share in two designer communities"}

    def _engineer(self):
        return {"product_name": "Client Onboarding Checklist", "product_type": "checklist", "summary": "A checklist pack.",
                "modules": [{"title": f"Module {i}", "items": ["Item one", "Item two", "Item three", "Item four"]} for i in (1, 2, 3)],
                "user_docs": ["Open the file", "Tick items", "Review progress", "Share with the client"],
                "test_cases": ["Open on a phone", "Tick and reload", "Read every item"], "out_of_scope": ["Client portal"]}

    def _finance(self):
        return {"price_usd": "$19", "pricing_model": "one-time purchase", "rationale": "Assumed comparable to template packs",
                "options_considered": ["$9", "$29"], "break_even": "$150 / $19 = 8 sales",
                "claims": [{"text": "Template packs often cost under $30", "source_url": None}]}

    def _policy_drafter(self):
        return {"terms": "Terms text.", "privacy": "Privacy text.", "refund_policy": "Refund text."}

    def _marketer(self):
        return {"store_title": "Client Onboarding Checklist", "store_tagline": "Start projects clearly",
                # The next line is deliberately forbidden content: the guardrail must strip it.
                "store_description": "A checklist pack for designers. Join over 5,000 happy customers today. It covers scope.",
                "store_bullets": ["Scope", "Timeline", "Content", "Handover"],
                "faq": [{"q": "What is it?", "a": "A checklist."}],
                "launch_posts": [{"channel": "Designer forum", "text": "This checklist covers client onboarding."}]}

    def _sales_ops(self):
        return {"delivery_subject": "Your checklist", "delivery_body": "Thanks. Open it here: {{ACCESS_LINK}}"}

    def _ops_analyst(self):
        return {"support_faq": [{"q": "How do I open it?", "a": "In a browser."}], "metrics_to_track": ["Sign-ups"],
                "recommendation": "persevere", "memo": "STUBBED memo."}

    def _advocate(self):
        return {"case": "STUBBED case for.", "strongest_points": ["p"], "weakest_point_admitted": "w"}

    def _critic(self):
        return {"case": "STUBBED case against.", "kill_reasons": ["r"], "best_pivot": "A proposal template pack for the same designers"}

    def _chair(self):
        keys = ("problem_severity", "market_and_demand", "competition_and_differentiation", "founder_fit",
                "feasibility_digital", "values_and_rules_fit")
        return {"scores": {k: self.chair_score for k in keys}, "verdict": self.chair_verdict,
                "explanation": "STUBBED explanation.", "warning": "STUBBED warning.",
                "advocate_case": "for", "critic_case": "against", "best_pivot": "A proposal template pack"}


class ScriptedFounder:
    """A test double for the founder's clicks. Lives in tests/ only."""

    def __init__(self, signups="150", actions="approve", gate="approve", notes=""):
        self.signups, self.actions, self.gate, self.notes, self.asked = signups, actions, gate, notes, []

    def ask(self, request: dict) -> dict:
        self.asked.append(request)
        if request["kind"] == "action":
            return {"decision": self.actions}
        if request["kind"] == "evidence":
            return {"waitlist_signups": self.signups, "interview_notes": self.notes}
        return {"decision": self.gate}
