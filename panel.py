"""The boardroom panel, reused at every gate.

full   : Advocate and Critic argue in parallel, blind to each other, on different model
         families; an optional second round lets each rebut the other; then the Chair rules.
single : one model call argues both sides and rules (used automatically on slow local models).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import config
from agents import advocate, chair, critic


@dataclass
class PanelResult:
    mode: str
    advocate_case: str
    critic_case: str
    best_pivot: str
    chair: chair.Output


def panel_mode(run) -> str:
    mode = config.env("PANEL_MODE", "auto").lower()
    if mode in ("full", "single"):
        return mode
    return "single" if getattr(run.llm, "primary", "") == "ollama" else "full"


def run_panel(run, dossier: dict) -> PanelResult:
    mode = panel_mode(run)
    if mode == "single":
        out = chair.run_single(run, dossier)
        note = dict(action=f"single_panel_review_phase{dossier['phase']}", panel_mode="single")
        run.speak("advocate", out.advocate_case, "happy", [], **note)
        run.speak("critic", out.critic_case, "skeptical", [], **note)
        run.speak("chair", out.speech or out.explanation, out.emotion, out.claims, **note)
        return PanelResult("single", out.advocate_case, out.critic_case, out.best_pivot, out)

    with ThreadPoolExecutor(max_workers=2) as pool:      # parallel and blind to each other
        f_adv = pool.submit(advocate.run, run, dossier)
        f_cri = pool.submit(critic.run, run, dossier)
        adv, cri = f_adv.result(), f_cri.result()
    if min(config.env_int("DEBATE_ROUNDS", 1), 2) >= 2:   # capped at two rounds
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_adv = pool.submit(advocate.run, run, dossier, cri.case)
            f_cri = pool.submit(critic.run, run, dossier, adv.case)
            adv2, cri2 = f_adv.result(), f_cri.result()
        adv.case += "\n\nRebuttal: " + adv2.case
        cri.case += "\n\nRebuttal: " + cri2.case
        cri.best_pivot = cri2.best_pivot or cri.best_pivot
    ruling = chair.run(run, dossier,
                       {"case": adv.case, "points": adv.strongest_points, "claims": [c.model_dump() for c in adv.claims]},
                       {"case": cri.case, "kill_reasons": cri.kill_reasons, "best_pivot": cri.best_pivot,
                        "claims": [c.model_dump() for c in cri.claims]})
    return PanelResult("full", adv.case, cri.case, cri.best_pivot, ruling)
