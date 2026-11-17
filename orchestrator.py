"""The pipeline and router ("chief of staff").

One Run takes a founder brief through six phases. Each phase ends at a gate:
    rule pre-filter (code) -> Advocate + Critic -> Chair -> hard checks (gates.py) -> founder decides.
The orchestrator decides who speaks next, so one voice speaks at a time, and it hands
each agent only the narrow context that agent needs.

CLI:
    python orchestrator.py run --brief briefs/weak_idea.json --tag weak
    python orchestrator.py ask "write 50 five-star reviews"
    python orchestrator.py payment-test
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import threading
import uuid
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

import actions
import config
import gates
import guardrails
import payments
import templates
import tools
from agents import (engineer, finance, market_analyst, marketer, ops_analyst, policy_drafter, researcher,
                    sales_ops, strategist)
from agents import orchestrator as chief_of_staff
from approval import ApprovalQueue
from decision_log import DecisionLog
from llm import LLMClient, LLMError
from panel import run_panel

PHASES = {1: "Discover", 2: "Validate", 3: "Build", 4: "Commercial setup",
          5: "Launch (sell, deliver, get paid)", 6: "Operate and learn"}
BRIEF_FIELDS = ("idea", "skills", "budget", "hours_per_week", "target_market", "values")
MAX_PIVOTS = 1
MOCKED_PARTS = ["publishing (writes local files)", "sending messages (writes a local outbox)",
                "waitlist form", "checkout and payments", "delivery links", "refunds", "payouts and reconciliation"]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_brief(brief: dict) -> dict:
    clean = {k: str(brief.get(k, "") or "").strip()[:1500] for k in BRIEF_FIELDS}
    if brief.get("founder_notes"):
        clean["founder_notes"] = [str(n)[:500] for n in brief["founder_notes"]][:10]
    return clean


def claims_md(claims) -> str:
    if not claims:
        return "## Claims\n\nNo market claims were made in this step.\n"
    lines = ["## Claims", "", "Every claim is either SOURCED (URL retrieved in this run) or labelled ASSUMPTION.", ""]
    for c in claims:
        lines.append(f"- **SOURCED** {c.text} ([source]({c.source_url}))" if c.label == "SOURCED"
                     else f"- **ASSUMPTION** {c.text}")
    return "\n".join(lines) + "\n"


def bullets(items) -> str:
    return "\n".join(f"- {str(i).strip()}" for i in items if str(i).strip()) or "- (none)"


class _TagCheck(HTMLParser):
    VOID = {"meta", "input", "br", "hr", "img", "link"}

    def __init__(self):
        super().__init__()
        self.stack, self.ok = [], True

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack.pop() != tag:
            self.ok = False


def mvp_checks(spec, html_text: str) -> list[dict]:
    """Automated checks on the generated MVP (the Phase 3 'tests pass' gate)."""
    parser = _TagCheck()
    parser.feed(html_text)
    modules = [m for m in spec.modules if isinstance(m, dict)]
    item_counts = [len([i for i in (m.get("items") or []) if str(i).strip()]) for m in modules]
    text = " ".join([spec.product_name, spec.summary] + [str(m) for m in modules] + spec.user_docs)
    excluded = guardrails.check_excluded(text)
    forbidden = guardrails.scan_output(text)
    results = [
        ("has_product_name", bool(spec.product_name.strip()), spec.product_name or "missing"),
        ("at_least_3_modules", len(modules) >= 3, f"{len(modules)} modules"),
        ("each_module_has_3_items", bool(item_counts) and min(item_counts) >= 3, f"items per module: {item_counts}"),
        ("user_docs_have_3_steps", len(spec.user_docs) >= 3, f"{len(spec.user_docs)} steps"),
        ("html_is_well_formed", parser.ok and not parser.stack, "all tags balanced" if parser.ok else "unbalanced tags"),
        ("every_module_rendered", all(str(m.get("title", "")).strip()[:20] in _unescape(html_text) for m in modules),
         "module titles found in the page"),
        ("no_excluded_category_content", not excluded, ", ".join(v.rule for v in excluded) or "clean"),
        ("no_forbidden_claims", not forbidden, ", ".join(v.rule for v in forbidden) or "clean"),
    ]
    return [{"check": n, "passed": bool(p), "detail": d} for n, p, d in results]


def _unescape(text: str) -> str:
    import html
    return html.unescape(text)


class Run:
    def __init__(self, brief: dict, founder, llm=None, research=None, out_dir: Path | str | None = None,
                 log_path: Path | str | None = None, tag: str = "", run_id: str | None = None, on_event=None):
        self.id = run_id or uuid.uuid4().hex[:8]
        self.brief = normalize_brief(brief)
        self.idea = self.brief["idea"]
        self.founder = founder
        self.on_event = on_event
        self.events: list[dict] = []
        self._lock = threading.Lock()
        base = config.ROOT / "runs" / self.id
        self.out_dir = Path(out_dir) if out_dir else base / "outputs"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log = DecisionLog(log_path or base / "decision_log.json")
        self.tag = re.sub(r"[^a-z0-9]+", "", tag.lower())
        self.llm = llm or LLMClient(notify=self.notice)
        self.research = research or tools.research
        self.approvals = ApprovalQueue()
        self.store = payments.Store()
        self.known_urls = {tools.normalize_url(u) for u in re.findall(r"https?://[^\s)\"'<>]+", json.dumps(self.brief))}
        self.ctx: dict = {}
        self.usage = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "models": set()}
        self.status, self.final = "created", None

    # ---- events, speech, files ------------------------------------------------
    def emit(self, type_: str, **data) -> dict:
        with self._lock:
            event = {"i": len(self.events), "type": type_, "ts": now(), **data}
            self.events.append(event)
        if self.on_event:
            self.on_event(event)
        return event

    def notice(self, level: str, message: str) -> None:
        self.emit("notice", level=level, message=message)

    def speak(self, agent: str, speech: str, emotion: str, claims, **extra) -> None:
        """One agent speaks. Events are queued in order, so the room hears one voice at a time."""
        self.emit("speech", agent=agent, speech=speech, emotion=emotion,
                  claims=[c.model_dump() for c in claims], **extra)

    def add_usage(self, result) -> None:
        with self._lock:
            self.usage["calls"] += 1
            self.usage["tokens_in"] += result.tokens_in
            self.usage["tokens_out"] += result.tokens_out
            self.usage["cost"] += result.cost
            self.usage["models"].add(f"{result.provider}:{result.model}")

    def path(self, phase: int, step: int | None, name: str, ext: str) -> Path:
        kind = "gate" if step is None else f"step{step}"
        suffix = f"_{self.tag}" if self.tag else ""
        return self.out_dir / f"phase{phase}_{kind}_{name}{suffix}.{ext}"

    def write(self, phase: int, step: int | None, name: str, ext: str, content: str) -> Path:
        path = self.path(phase, step, name, ext)
        path.write_text(content, encoding="utf-8")
        self.emit("artifact", phase=phase, file=path.name)
        return path

    # ---- founder channel ------------------------------------------------------
    def add_note(self, text: str) -> dict:
        """A free-text request from the founder. Checked by the rule pre-filter before anything else."""
        check = guardrails.prefilter(text)
        if check.blocked:
            self.log.append(agent="guardrail", action="refuse_founder_request", sources=[], model=None, cost=0,
                            approved_by=None, outcome="refused", rules=[v.rule for v in check.violations],
                            run_id=self.id)
            result = {"accepted": False, "message": check.recommendation, "rules": [v.rule for v in check.violations]}
        else:
            self.brief.setdefault("founder_notes", []).append(text.strip()[:500])
            self.log.append(agent="founder", action="add_note", sources=[], model=None, cost=0,
                            approved_by="founder", run_id=self.id)
            result = {"accepted": True, "message": "Noted. The next agents will see this.", "rules": []}
        self.emit("note_result", text=text[:300], **result)
        return result

    def ask_approval(self, agent: str, action) -> object | None:
        """Show a pending action to the founder. Returns an ApprovalRecord, or None if rejected."""
        self.emit("action_pending", action=action.public(), agent=agent)
        answer = self.founder.ask({"kind": "action", "action": action.public(), "agent": agent})
        approved = str(answer.get("decision", "")).lower() == "approve"
        record = self.approvals.approve(action.id, approved_by="founder") if approved else None
        if not approved:
            self.approvals.reject(action.id)
        self.log.append(agent=agent, action=f"{action.kind}_{'approved' if approved else 'rejected'}", sources=[],
                        model=None, cost=0, approved_by="founder" if approved else None, action_id=action.id,
                        description=action.description, mocked=True, run_id=self.id,
                        outcome="approved" if approved else "rejected_by_founder")
        self.emit("action_resolved", action=action.public())
        return record

    def gated_publish(self, agent: str, description: str, content: str, destination: Path) -> bool:
        action = self.approvals.propose("publish", description, content, preview=re.sub(r"<[^>]+>", " ", content))
        record = self.ask_approval(agent, action)
        if record is None:
            return False
        actions.publish(self.approvals, action, record, content, destination)   # raises without a valid record
        self.emit("artifact", file=destination.name, mocked=True)
        return True

    # ---- main loop --------------------------------------------------------------
    def execute(self) -> str:
        try:
            self._execute()
        except LLMError as exc:
            self.status = "error"
            self.emit("error", message=str(exc))
            self.log.append(agent="orchestrator", action="run_error", sources=[], model=None, cost=0,
                            approved_by=None, error=str(exc)[:300], run_id=self.id)
        return self.status

    def _execute(self) -> None:
        self.status = "running"
        describe = getattr(self.llm, "describe", lambda: {})()
        self.emit("run_started", run_id=self.id, brief=self.brief, thresholds=gates.thresholds(), llm=describe,
                  mocked=MOCKED_PARTS, phases=PHASES)

        # [0] Rule pre-filter: code only, before any model call.
        check = guardrails.prefilter(" \n".join(str(v) for v in self.brief.values()))
        if check.blocked:
            self._prefilter_stop(check)
            return

        phase, attempts, pivots = 1, defaultdict(int), 0
        while phase <= 6:
            attempts[phase] += 1
            self.emit("phase_started", phase=phase, name=PHASES[phase], attempt=attempts[phase])
            evidence, produced, claims = getattr(self, f"phase{phase}")()
            result, pan = self.gate(phase, evidence, produced, claims, attempts[phase])
            final, pivot_idea = self.founder_gate_decision(phase, result, pan)
            if final == "go":
                phase += 1
            elif final == "repeat":
                self.ctx.pop(f"phase{phase}_done", None)
            elif final == "pivot":
                blocked = guardrails.prefilter(pivot_idea)
                if pivots >= MAX_PIVOTS or not pivot_idea.strip() or blocked.blocked:
                    why = ("The pivot idea is not allowed: " + blocked.recommendation if blocked.blocked else
                           "A pivot was already tried in this run." if pivots >= MAX_PIVOTS else "No pivot idea was given.")
                    self.finish("stop", why + " Stopping here; start a new run with a new brief.")
                    return
                pivots += 1
                self.idea, self.ctx, phase = pivot_idea.strip(), {}, 1
                attempts.clear()
                self.notice("info", f"Pivot accepted. Restarting at Phase 1 with: {self.idea}")
            else:
                self.finish("stop", f"Stopped at the Phase {phase} gate. Nothing was launched.")
                return
        self.finish("completed", "All six phases passed their gates. Every outside effect remained MOCKED.")

    def _prefilter_stop(self, check) -> None:
        rules = [v.rule for v in check.violations]
        body = [f"# Phase 0 gate: rule pre-filter", "", "**Outcome: STOP**", "",
                "The brief was checked by code before any model was called.", "",
                f"- Kind: `{check.kind}`", f"- Rules triggered: {', '.join(f'`{r}`' for r in rules)}", "",
                "| Rule | Matched text | Why |", "|---|---|---|"]
        body += [f"| {v.rule} | {v.match.replace('|', '/')} | {v.reason} |" for v in check.violations]
        body += ["", "## Recommendation", "", check.recommendation, "",
                 "No agent ran, no model was called and nothing was produced or published.", ""]
        self.write(0, None, "prefilter", "md", "\n".join(body))
        self.log.append(agent="gate", action="rule_prefilter", sources=[], model=None, cost=0, approved_by=None,
                        outcome="stop", rules=rules, kind=check.kind, run_id=self.id)
        self.speak("chair", check.recommendation, "stern", [], action="rule_prefilter")
        self.emit("gate", phase=0, name="Rule pre-filter", outcome="stop", chair_verdict="stop", checks=[],
                  reasons=[v.reason for v in check.violations], explanation=check.recommendation,
                  needs_decision=False)
        self.finish("stop", check.recommendation)

    def finish(self, status: str, summary: str) -> None:
        self.status, self.final = status, summary
        usage = dict(self.usage, models=sorted(self.usage["models"]), cost=round(self.usage["cost"], 6))
        self.log.append(agent="orchestrator", action="run_finished", sources=[], model=None,
                        cost=0, approved_by=None, outcome=status, run_total_cost_usd=usage["cost"],
                        run_tokens=usage["tokens_in"] + usage["tokens_out"], run_llm_calls=usage["calls"],
                        run_id=self.id)
        self.emit("run_finished", status=status, summary=summary, usage=usage)

    # ---- gate -------------------------------------------------------------------
    def gate(self, phase: int, evidence: dict, produced: dict, claims: list, attempt: int):
        sourced = [c for c in claims if c.label == "SOURCED"]
        dossier = {
            "phase": phase, "phase_name": PHASES[phase], "idea": self.idea, "founder_brief": self.brief,
            "produced_in_this_phase": produced,
            "claims": [c.model_dump() for c in claims][:30],
            "claim_counts": {"sourced": len(sourced), "assumption": len(claims) - len(sourced)},
            "hard_checks_set_in_advance": gates.thresholds().get(phase, {}),
            "measured_evidence": evidence,
            "mocked": "All publishing, sending, payments, delivery and refunds are MOCKED; mocked results are not evidence of demand.",
        }
        pan = run_panel(self, dossier)
        result = gates.evaluate(phase, evidence, pan.chair.verdict, pan.chair.scores, attempt)
        self.ctx["last_gate"] = (result, pan)
        self._write_gate(phase, result, pan, None)
        self.log.append(agent="gate", action="evidence_gate", sources=sorted({c.source_url for c in sourced}),
                        model=None, cost=0, approved_by=None, outcome=result.outcome, phase=phase,
                        chair_verdict=result.chair_verdict, overridden_by_code=result.overridden_by_code,
                        checks=[c.__dict__ for c in result.checks], run_id=self.id)
        self.emit("gate", phase=phase, name=PHASES[phase], outcome=result.outcome, chair_verdict=result.chair_verdict,
                  chair_average=result.chair_average, scores=pan.chair.scores, checks=[c.__dict__ for c in result.checks],
                  reasons=result.reasons, explanation=pan.chair.explanation, warning=pan.chair.warning,
                  best_pivot=pan.best_pivot, overridden_by_code=result.overridden_by_code, needs_decision=True)
        return result, pan

    def founder_gate_decision(self, phase: int, result, pan) -> tuple[str, str]:
        answer = self.founder.ask({
            "kind": "gate", "phase": phase, "phase_name": PHASES[phase], "recommendation": result.outcome,
            "explanation": pan.chair.explanation, "warning": pan.chair.warning, "best_pivot": pan.best_pivot,
            "reasons": result.reasons, "options": ["approve", "override_go", "pivot", "stop"]})
        decision = str(answer.get("decision", "stop")).lower()
        final = {"approve": result.outcome, "override_go": "go", "pivot": "pivot"}.get(decision, "stop")
        pivot_idea = str(answer.get("pivot_idea") or "").strip() or pan.best_pivot
        override = final != result.outcome
        self.log.append(agent="gate", action="founder_gate_decision", sources=[], model=None, cost=0,
                        approved_by="founder", outcome=final, phase=phase, recommended=result.outcome,
                        founder_override=True if override else None,
                        chair_warning=pan.chair.warning if override and final == "go" else None, run_id=self.id)
        self._write_gate(phase, result, pan, (decision, final))
        self.emit("gate_decided", phase=phase, decision=decision, final=final, override=override)
        if override and final == "go":
            self.notice("warning", f"Founder overrode a {result.outcome.upper()} recommendation. "
                                   f"Logged with the Chair's warning: {pan.chair.warning}")
        return final, pivot_idea

    def _write_gate(self, phase: int, result, pan, decision) -> None:
        lines = [f"# Phase {phase} gate: {PHASES[phase]}", "",
                 f"**Outcome: {result.outcome.upper()}**", "",
                 f"- Chair's recommendation: `{result.chair_verdict}` (rubric average {result.chair_average} of 4)",
                 f"- Outcome after the hard checks in code: `{result.outcome}`"
                 + (" (made stricter by code)" if result.overridden_by_code else ""),
                 f"- Panel mode: `{pan.mode}`"]
        if decision:
            lines.append(f"- Founder decision: `{decision[0]}` -> final: `{decision[1]}`"
                         + (" (founder override, logged with the Chair's warning)" if decision[1] != result.outcome else ""))
        else:
            lines.append("- Founder decision: pending")
        lines += ["", "## Hard checks (targets fixed before the evidence came in)", "",
                  "| Check | Target | Actual | Passed |", "|---|---|---|---|"]
        lines += [f"| {c.name} | {c.target} | {c.actual} | {'yes' if c.passed else 'NO'} |" for c in result.checks]
        if result.reasons:
            lines += ["", "## Why the gate did not pass", "", bullets(result.reasons)]
        lines += ["", "## Chair's rubric (0-4 each)", "", "| Criterion | Score |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in pan.chair.scores.items()]
        lines += ["", "## Chair's explanation", "", pan.chair.explanation or "(none given)", "",
                  "## If the founder overrides", "", pan.chair.warning or "(no warning given)", "",
                  "## Advocate", "", pan.advocate_case or "(none)", "",
                  "## Critic", "", pan.critic_case or "(none)", "",
                  "## Best pivot", "", pan.best_pivot or "(none proposed)", "",
                  claims_md(pan.chair.claims)]
        self.path(phase, None, "decision", "md").write_text("\n".join(lines), encoding="utf-8")

    # ---- phases: each returns (evidence for gates.py, summary for the board, claims) ----
    def phase1(self):
        kick = chief_of_staff.run(self, self.brief, self.idea)
        queries = [q for q in kick.search_queries if q.strip()][:3] or [
            self.idea[:90], tools.keywords(self.idea) + " alternatives", tools.keywords(self.idea) + " market"]
        pack = self.research(queries)
        self.known_urls |= {tools.normalize_url(p["url"]) for p in pack}
        self.log.append(agent="researcher", action="web_research", sources=[p["url"] for p in pack], model=None,
                        cost=0, approved_by=None, queries=queries, run_id=self.id)
        if not pack:
            self.notice("warning", "Web research returned nothing. Every market claim will be labelled ASSUMPTION.")
        r = researcher.run(self, self.brief, self.idea, pack)
        m = market_analyst.run(self, self.brief, r.sharpened_idea or self.idea, r.target_customer, pack)

        opp_rows = "\n".join(f"| {o.get('name', '')} | {o.get('score', '')} | {str(o.get('description', '')).replace('|', '/')} | "
                             f"{str(o.get('why', '')).replace('|', '/')} |" for o in r.opportunities if isinstance(o, dict))
        self.write(1, 1, "opportunities", "md", "\n".join([
            "# Phase 1, step 1: opportunities", "", f"**Starting idea:** {self.idea}", "",
            f"**Sharpened idea:** {r.sharpened_idea}", "", f"**First customer:** {r.target_customer}", "",
            f"**Problem today:** {r.problem}", "", "## Idea scored against alternatives", "",
            "| Opportunity | Score (0-10) | Description | Why |", "|---|---|---|---|", opp_rows, "",
            f"**Recommended:** {r.recommended}", "", "## Evidence gaps", "", bullets(r.evidence_gaps), "",
            "## Research sources retrieved in this run", "",
            bullets(f"[{p['title']}]({p['url']}) ({p['source']})" for p in pack), "", claims_md(r.claims)]))
        comp = "\n".join(f"- {c.get('name', '')}: {c.get('note', '')}"
                         + (f" ([source]({c['source_url']}))" if tools.normalize_url(str(c.get('source_url') or '')) in self.known_urls else "")
                         for c in m.competitors if isinstance(c, dict)) or "- (none found in the evidence)"
        self.write(1, 2, "market", "md", "\n".join([
            "# Phase 1, step 2: market definition", "", m.market_definition, "", "## Segments", "", bullets(m.segments), "",
            "## Existing alternatives", "", comp, "", "## Demand signals (for and against)", "", bullets(m.demand_signals), "",
            claims_md(m.claims)]))
        self.write(1, 3, "mom_test_interviews", "md", "\n".join([
            "# Phase 1, step 3: Mom Test interview plan", "",
            "The system cannot talk to customers. This is a script for the founder to run. "
            "No interviews have been simulated, and nothing here counts as evidence until the founder "
            "pastes in real notes.", "", "## Plan", "", m.interview_plan, "", "## Questions", "",
            "\n".join(f"{i}. {q}" for i, q in enumerate(m.mom_test_questions, 1)), ""]))
        claims = self._dedupe(r.claims + m.claims)
        self.ctx["discovery"] = {"sharpened_idea": r.sharpened_idea or self.idea, "target_customer": r.target_customer,
                                 "problem": r.problem, "recommended": r.recommended,
                                 "market": m.market_definition, "competitors": m.competitors[:6]}
        self.ctx["claims"] = claims
        sourced = len({c.text for c in claims if c.label == "SOURCED"})
        evidence = {"sourced_claims": sourced, "assumption_claims": len(claims) - sourced,
                    "research_sources_found": len(pack)}
        produced = dict(self.ctx["discovery"], opportunities=r.opportunities, demand_signals=m.demand_signals,
                        evidence_gaps=r.evidence_gaps)
        return evidence, produced, claims

    def phase2(self):
        t = gates.thresholds()[2]
        target, days = t["waitlist_target"], t["waitlist_days"]
        if "strategy" not in self.ctx:
            s = strategist.run(self, self.brief, self.ctx["discovery"], target, days)
            canvas = "\n".join(f"| {k.replace('_', ' ').title()} | {str(s.lean_canvas.get(k, '')).replace('|', '/')} |"
                               for k in strategist.CANVAS_BLOCKS)
            self.write(2, 1, "lean_canvas", "md", "\n".join([
                "# Phase 2, step 1: Lean Canvas", "", "| Block | Content |", "|---|---|", canvas, "", claims_md(s.claims)]))
            landing = templates.render_landing(s, target, days)
            self.write(2, 2, "landing_page_draft", "html", landing)
            self.write(2, 3, "waitlist_plan", "md", "\n".join([
                "# Phase 2, step 3: demand test plan", "",
                f"**Target fixed in advance (in code): {target} waitlist sign-ups in {days} days.**", "",
                "The gate compares the founder's real count with this target. Fewer than the target is a failed "
                "test: under 25% recommends STOP, under 50% recommends PIVOT, under 100% recommends REPEAT.", "",
                "## Where to share the page", "", s.waitlist_plan, "",
                "The waitlist form in the draft page is **MOCKED** and collects nothing. "
                "The system never generates sign-ups; only the founder reports them.", ""]))
            self.emit("threshold", phase=2, text=f"Target set in advance: {target} waitlist sign-ups in {days} days.")
            self.gated_publish("strategist", "Publish the demand-test landing page (MOCKED: writes a local file only)",
                               landing, self.path(2, 4, "landing_page_published_mocked", "html"))
            self.ctx["strategy"] = {"lean_canvas": s.lean_canvas, "headline": s.landing_headline}
            self.ctx["claims"] = self._dedupe(self.ctx.get("claims", []) + s.claims)
        answer = self.founder.ask({
            "kind": "evidence", "phase": 2,
            "question": f"How many REAL waitlist sign-ups did the landing page get? The target set in advance is "
                        f"{target} in {days} days. Leave it empty if the test has not run yet.",
            "fields": ["waitlist_signups", "interview_notes"]})
        raw = str(answer.get("waitlist_signups", "")).strip()
        signups = int(raw) if raw.isdigit() else None
        notes = str(answer.get("interview_notes") or "").strip()[:2000]
        self.log.append(agent="founder", action="report_demand_evidence", sources=[], model=None, cost=0,
                        approved_by="founder", waitlist_signups=signups, waitlist_target=target,
                        real_interview_notes_given=bool(notes), run_id=self.id)
        self.write(2, 5, "demand_result", "md", "\n".join([
            "# Phase 2, step 5: demand test result (reported by the founder)", "",
            f"- Target set in advance: **{target} sign-ups in {days} days**",
            f"- Founder-reported sign-ups: **{signups if signups is not None else 'not reported yet'}**",
            f"- Real interview notes supplied: {'yes' if notes else 'no'}", "",
            "These numbers were typed in by the founder. The system did not generate or adjust them.", ""]))
        self.ctx["demand"] = {"waitlist_signups": signups, "waitlist_target": target, "days": days,
                              "real_interview_notes": notes or None}
        evidence = {"waitlist_signups": signups, "waitlist_target": target,
                    "real_interview_notes": notes or "none supplied"}
        return evidence, dict(self.ctx["strategy"], demand=self.ctx["demand"]), self.ctx.get("claims", [])

    def phase3(self):
        e = engineer.run(self, self.brief, {**self.ctx["discovery"], **self.ctx.get("strategy", {})})
        page = templates.render_mvp(e)
        checks = mvp_checks(e, page)
        self.write(3, 1, "mvp", "html", page)
        self.write(3, 2, "user_docs", "md", "\n".join([
            f"# {e.product_name}: user guide", "", e.summary, "", "## How to use it", "",
            "\n".join(f"{i}. {s}" for i, s in enumerate(e.user_docs, 1)), "",
            "## Not included in this MVP", "", bullets(e.out_of_scope), ""]))
        passed = sum(c["passed"] for c in checks)
        self.write(3, 3, "test_report", "md", "\n".join([
            "# Phase 3, step 3: MVP test report", "", f"**{passed} of {len(checks)} automated checks passed.**", "",
            "| Check | Result | Detail |", "|---|---|---|",
            *[f"| {c['check']} | {'PASS' if c['passed'] else 'FAIL'} | {str(c['detail']).replace('|', '/')} |" for c in checks],
            "", "## For a human to check before shipping", "", bullets(e.test_cases), ""]))
        self.log.append(agent="engineer", action="run_mvp_checks", sources=[], model=None, cost=0, approved_by=None,
                        tests_passed=passed, tests_total=len(checks), run_id=self.id)
        self.ctx["product"] = {"id": re.sub(r"[^a-z0-9]+", "-", e.product_name.lower()).strip("-") or "product",
                               "name": e.product_name, "type": e.product_type, "summary": e.summary,
                               "modules": [str(m.get("title", "")) for m in e.modules if isinstance(m, dict)]}
        evidence = {"tests_passed": passed, "tests_total": len(checks)}
        return evidence, dict(self.ctx["product"], failed_checks=[c for c in checks if not c["passed"]]), e.claims

    def phase4(self):
        product = self.ctx["product"]
        f = finance.run(self, self.brief, product, self.ctx["discovery"].get("competitors", []))
        p = policy_drafter.run(self, self.brief, product, f.price_usd)
        self.write(4, 1, "pricing", "md", "\n".join([
            "# Phase 4, step 1: pricing", "", f"**Recommended price: ${f.price_usd:,.2f}** ({f.pricing_model})", "",
            "## Why", "", f.rationale, "", "## Other options considered", "", bullets(f.options_considered), "",
            "## Break-even against the founder's budget", "", f.break_even, "",
            "No payment system is set up. This is a price recommendation, not a revenue forecast.", "",
            claims_md(f.claims)]))
        label = policy_drafter.DRAFT_LABEL
        policies = "\n".join([
            "# Phase 4, step 2: draft policies", "", f"> **{label}**", "",
            "## Terms of use", "", f"> {label}", "", p.terms, "",
            "## Privacy policy", "", f"> {label}", "", p.privacy, "",
            "## Refund policy", "", f"> {label}", "", p.refund_policy, ""])
        self.write(4, 2, "policies_draft", "md", policies)
        self.ctx["price_usd"] = float(f.price_usd or 0)
        evidence = {"price_usd": self.ctx["price_usd"], "policies_labelled_draft": policies.count(label) >= 4}
        produced = {"price_usd": f.price_usd, "pricing_model": f.pricing_model, "rationale": f.rationale,
                    "policies": "terms, privacy and refund drafts written, each labelled DRAFT"}
        return evidence, produced, self._dedupe(f.claims + p.claims)

    def phase5(self):
        product, price = self.ctx["product"], self.ctx.get("price_usd", 0.0)
        m = marketer.run(self, self.brief, product, price)
        store_page = templates.render_store(m, price, product["name"])
        posts = "\n".join(["# Phase 5, step 2: launch posts (drafts)", "",
                           "Drafts only. Nothing is posted anywhere; publishing is MOCKED and needs founder approval.", ""]
                          + [f"## {p.get('channel', 'Post')}\n\n{p.get('text', '')}\n" for p in m.launch_posts if isinstance(p, dict)])
        self.write(5, 1, "store_page_draft", "html", store_page)
        self.write(5, 2, "launch_posts_draft", "md", posts)
        published = [
            self.gated_publish("marketer", "Publish the store page (MOCKED: writes a local file only)", store_page,
                               self.path(5, 3, "store_page_published_mocked", "html")),
            self.gated_publish("marketer", "Publish the launch posts (MOCKED: writes a local file only)", posts,
                               self.path(5, 4, "launch_posts_published_mocked", "md")),
        ]
        s = sales_ops.run(self, product)
        message = {"to": "(buyer placeholder)", "subject": s.delivery_subject, "body": s.delivery_body}
        send_action = self.approvals.propose("send", "Send one test delivery message (MOCKED: written to a local outbox only)",
                                             message, preview=f"{s.delivery_subject}\n{s.delivery_body}")
        record = self.ask_approval("sales_ops", send_action)
        if record is not None:
            actions.send(self.approvals, send_action, record, message, self.path(5, 5, "outbox_mocked", "md"))
            self.emit("artifact", file=self.path(5, 5, "outbox_mocked", "md").name, mocked=True)
        price_cents = int(round(price * 100))
        results = sales_ops.run_sale_to_cash_checks(self.store, self.approvals, product["id"], price_cents,
                                                    approve=lambda action: self.ask_approval("sales_ops", action))
        log_path = self.out_dir / "payment_test_log.md"
        log_path.write_text(sales_ops.checks_markdown(results, "the founder", product["id"], price_cents), encoding="utf-8")
        self.emit("artifact", phase=5, file=log_path.name, mocked=True)
        passed = sum(r["passed"] for r in results)
        self.log.append(agent="sales_ops", action="sale_to_cash_checks", sources=[], model=None, cost=0,
                        approved_by=None, mocked=True, tests_passed=passed, tests_total=len(results), run_id=self.id)
        evidence = {"sale_tests_passed": passed, "sale_tests_total": len(results),
                    "store_and_posts_published_mocked": sum(published)}
        produced = {"store_title": m.store_title, "launch_post_channels": [p.get("channel") for p in m.launch_posts if isinstance(p, dict)],
                    "sale_to_cash_checks": results, "note": "all sales, payments and deliveries here are MOCKED tests"}
        return evidence, produced, m.claims

    def phase6(self):
        claims = self.ctx.get("claims", [])
        real = {"sourced_market_claims": len([c for c in claims if c.label == "SOURCED"]),
                "assumption_claims": len([c for c in claims if c.label == "ASSUMPTION"]),
                "demand_test": self.ctx.get("demand"), "product": self.ctx.get("product"),
                "price_usd": self.ctx.get("price_usd"),
                "real_sales": 0, "mocked": MOCKED_PARTS}
        o = ops_analyst.run(self, self.brief, real)
        faq = "\n".join(f"**{f.get('q', '')}**\n\n{f.get('a', '')}\n" for f in o.support_faq if isinstance(f, dict))
        self.write(6, 1, "support_faq", "md", "# Phase 6, step 1: support answers (drafts)\n\n" + faq)
        self.write(6, 2, "metrics", "md", "# Phase 6, step 2: metrics to track\n\n" + bullets(o.metrics_to_track) + "\n")
        self.write(6, 3, "persevere_or_pivot_memo", "md", "\n".join([
            "# Phase 6, step 3: persevere-or-pivot memo", "", f"**Recommendation: {o.recommendation.upper() or 'NOT GIVEN'}**", "",
            o.memo, "", "## Real evidence this memo is based on", "", "```json", json.dumps(real, indent=1, default=str), "```", "",
            claims_md(o.claims)]))
        return {"memo_written": bool(o.memo.strip())}, {"recommendation": o.recommendation, "memo": o.memo, **real}, o.claims

    @staticmethod
    def _dedupe(claims: list) -> list:
        seen, out = set(), []
        for c in claims:
            key = c.text.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(c)
        return out


# ---- CLI ----------------------------------------------------------------------
class CLIFounder:
    """The founder answers on the keyboard. Nothing proceeds without a typed answer."""

    def ask(self, request: dict) -> dict:
        kind = request["kind"]
        if kind == "action":
            a = request["action"]
            print(f"\n--- PENDING ACTION [{'MOCKED' if a['mocked'] else 'LIVE'}] {a['kind'].upper()}: {a['description']}")
            if a.get("preview"):
                print("    preview:", a["preview"][:300].replace("\n", " "))
            return {"decision": "approve" if input("    Approve? [y/N] ").strip().lower() in ("y", "yes") else "reject"}
        if kind == "evidence":
            print(f"\n--- FOUNDER INPUT: {request['question']}")
            return {"waitlist_signups": input("    Real sign-ups (number, or Enter if none yet): ").strip(),
                    "interview_notes": input("    Real interview notes (or Enter to skip): ").strip()}
        print(f"\n=== PHASE {request['phase']} GATE ({request['phase_name']}): recommendation {request['recommendation'].upper()}")
        print("   ", request["explanation"])
        for reason in request["reasons"]:
            print("    -", reason)
        if request["best_pivot"]:
            print("    Best pivot:", request["best_pivot"])
        while True:
            choice = input("    [a]pprove recommendation / [o]verride and go / [p]ivot / [s]top: ").strip().lower()[:1]
            if choice in "aops" and choice:
                break
        answer = {"decision": {"a": "approve", "o": "override_go", "p": "pivot", "s": "stop"}[choice]}
        if choice == "p":
            answer["pivot_idea"] = input("    Pivot idea (Enter to use the board's suggestion): ").strip()
        return answer


def _print_event(event: dict) -> None:
    t = event["type"]
    if t == "speech":
        sourced = sum(1 for c in event["claims"] if c["label"] == "SOURCED")
        print(f"\n[{event['agent']} | {event['emotion']}] {event['speech']}"
              + (f"  ({sourced} sourced, {len(event['claims']) - sourced} assumption)" if event["claims"] else ""))
    elif t == "phase_started":
        print(f"\n########## Phase {event['phase']}: {event['name']} (attempt {event['attempt']})")
    elif t == "notice":
        print(f"\n! {event['level'].upper()}: {event['message']}")
    elif t == "artifact":
        print(f"    wrote {event['file']}")
    elif t == "run_finished":
        u = event["usage"]
        print(f"\n===== RUN {event['status'].upper()}: {event['summary']}")
        print(f"      Cost of this run: ${u['cost']:.4f} ({u['tokens_in'] + u['tokens_out']} tokens, "
              f"{u['calls']} model calls, models: {', '.join(u['models']) or 'none'})")
    elif t == "error":
        print(f"\nERROR: {event['message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VentureBoard pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run a founder brief through the pipeline (you are the founder)")
    run_p.add_argument("--brief", required=True, help="path to a brief JSON file")
    run_p.add_argument("--tag", default="", help="suffix for output file names, e.g. weak")
    run_p.add_argument("--out", default=str(config.ROOT / "outputs"))
    run_p.add_argument("--log", default=str(config.ROOT / "decision_log.json"))
    ask_p = sub.add_parser("ask", help="send one founder request through the rule pre-filter")
    ask_p.add_argument("text")
    pay_p = sub.add_parser("payment-test", help="run the MOCKED sale-to-cash checks and write outputs/payment_test_log.md")
    pay_p.add_argument("--approver", default="founder", choices=["founder", "test-harness"],
                       help="founder = you confirm each step on the keyboard; test-harness = automatic, labelled as such")
    args = parser.parse_args(argv)

    if args.command == "ask":
        check = guardrails.prefilter(args.text)
        print("REFUSED: " + check.recommendation if check.blocked else "ALLOWED: no rule was triggered.")
        return 0

    if args.command == "payment-test":
        queue, store, founder = ApprovalQueue(), payments.Store(), CLIFounder()
        log = DecisionLog(config.ROOT / "decision_log.json")

        def approve(action):
            if args.approver == "test-harness":
                return queue.approve(action.id, approved_by="test-harness (automated, not a founder decision)")
            if founder.ask({"kind": "action", "action": action.public()})["decision"] == "approve":
                return queue.approve(action.id, approved_by="founder")
            queue.reject(action.id)
            return None

        results = sales_ops.run_sale_to_cash_checks(store, queue, "demo-product", 1900, approve)
        who = "the founder (typed confirmation)" if args.approver == "founder" else \
            "the automated test harness (these are not founder decisions)"
        out = config.ROOT / "outputs" / "payment_test_log.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(sales_ops.checks_markdown(results, who, "demo-product", 1900), encoding="utf-8")
        passed = sum(r["passed"] for r in results)
        log.append(agent="sales_ops", action="sale_to_cash_checks", sources=[], model=None, cost=0,
                   approved_by="founder" if args.approver == "founder" else None, mocked=True,
                   tests_passed=passed, tests_total=len(results), approver=args.approver)
        print(out.read_text())
        return 0 if passed == len(results) else 1

    brief = json.loads(Path(args.brief).read_text(encoding="utf-8"))
    run = Run(brief, CLIFounder(), out_dir=args.out, log_path=args.log, tag=args.tag, on_event=_print_event)
    print(f"Run {run.id}. You are the founder: nothing is published, sent or delivered without your answer. "
          f"All outside effects are MOCKED.")
    status = run.execute()
    return 0 if status in ("completed", "stop") else 1


if __name__ == "__main__":
    sys.exit(main())
