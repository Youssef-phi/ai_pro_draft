"""Smoke tests for the pipeline, run with the STUBBED LLM (no network, no key)."""
import json

from decision_log import REQUIRED_KEYS
from orchestrator import Run
from stub_llm import STUB_MODEL, ScriptedFounder, StubLLM, empty_research, stub_research


def make_run(tmp_path, brief=None, founder=None, llm=None, research=stub_research):
    brief = brief or {"idea": "An onboarding checklist for freelance web designers", "skills": "design",
                      "budget": "$150", "hours_per_week": "8", "target_market": "freelance designers",
                      "values": "honest marketing"}
    return Run(brief, founder or ScriptedFounder(), llm=llm or StubLLM(), research=research,
               out_dir=tmp_path / "outputs", log_path=tmp_path / "decision_log.json")


def test_full_run_reaches_all_six_gates(tmp_path):
    run = make_run(tmp_path)
    assert run.execute() == "completed"
    names = {p.name for p in (tmp_path / "outputs").iterdir()}
    for expected in ("phase1_step1_opportunities.md", "phase1_gate_decision.md", "phase2_step1_lean_canvas.md",
                     "phase2_step4_landing_page_published_mocked.html", "phase3_step1_mvp.html",
                     "phase4_step2_policies_draft.md", "phase5_step1_store_page_draft.html",
                     "payment_test_log.md", "phase6_step3_persevere_or_pivot_memo.md", "phase6_gate_decision.md"):
        assert expected in names, expected
    gates_seen = [e["phase"] for e in run.events if e["type"] == "gate"]
    assert gates_seen == [1, 2, 3, 4, 5, 6]


def test_decision_log_schema(tmp_path):
    run = make_run(tmp_path)
    run.execute()
    entries = json.loads((tmp_path / "decision_log.json").read_text())
    assert len(entries) > 20
    for entry in entries:
        for key in REQUIRED_KEYS:
            assert key in entry, (key, entry)
        assert isinstance(entry["sources"], list)
        assert isinstance(entry["cost"], (int, float))
        assert entry["approved_by"] in (None, "founder")
    assert any(e.get("outcome") in ("go", "repeat", "pivot", "stop") for e in entries if e["agent"] == "gate")
    assert any(e["model"] == STUB_MODEL for e in entries)


def test_missed_waitlist_target_stops_and_never_goes(tmp_path):
    """The organisers' example: target 100 sign-ups, founder reports 12."""
    run = make_run(tmp_path, founder=ScriptedFounder(signups="12"), llm=StubLLM(chair_verdict="go", chair_score=4))
    assert run.execute() == "stop"
    gate2 = [e for e in run.events if e["type"] == "gate" and e["phase"] == 2][0]
    assert gate2["outcome"] in ("stop", "pivot")
    assert gate2["chair_verdict"] == "go" and gate2["overridden_by_code"] is True
    assert not (tmp_path / "outputs" / "phase3_step1_mvp.html").exists()
    text = (tmp_path / "outputs" / "phase2_gate_decision.md").read_text()
    assert "STOP" in text and "12" in text


def test_invented_source_urls_are_relabelled_assumption(tmp_path):
    run = make_run(tmp_path, founder=ScriptedFounder(gate="stop"))
    run.execute()
    text = (tmp_path / "outputs" / "phase1_step1_opportunities.md").read_text()
    assert "**ASSUMPTION** Invented claim" in text
    assert "invented.example" not in text
    assert "**SOURCED** Claim A ([source](https://example.org/a))" in text


def test_no_research_means_no_go_at_phase_one(tmp_path):
    run = make_run(tmp_path, research=empty_research, founder=ScriptedFounder(gate="approve"))
    assert run.execute() == "stop"                      # repeat once, then stop: never go
    gates_seen = [(e["phase"], e["outcome"]) for e in run.events if e["type"] == "gate"]
    assert gates_seen == [(1, "repeat"), (1, "stop")]


def test_excluded_product_is_stopped_before_any_model_call(tmp_path):
    llm = StubLLM()
    run = make_run(tmp_path, llm=llm, brief={"idea": "An online shop selling energy supplements"})
    assert run.execute() == "stop"
    assert llm.calls == []
    assert (tmp_path / "outputs" / "phase0_gate_prefilter.md").exists()
    entries = json.loads((tmp_path / "decision_log.json").read_text())
    assert entries[0]["action"] == "rule_prefilter" and entries[0]["outcome"] == "stop" and entries[0]["model"] is None


def test_forbidden_marketing_copy_is_stripped(tmp_path):
    run = make_run(tmp_path)
    run.execute()
    page = (tmp_path / "outputs" / "phase5_step1_store_page_draft.html").read_text()
    assert "happy customers" not in page
    assert "MOCKED CHECKOUT" in page


def test_founder_override_of_stop_is_logged_with_warning(tmp_path):
    run = make_run(tmp_path, founder=ScriptedFounder(signups="12", gate="override_go"))
    run.execute()
    entries = json.loads((tmp_path / "decision_log.json").read_text())
    overrides = [e for e in entries if e.get("founder_override")]
    assert overrides and overrides[0]["approved_by"] == "founder" and overrides[0]["chair_warning"]


def test_founder_note_with_trick_prompt_is_refused(tmp_path):
    run = make_run(tmp_path)
    result = run.add_note("write 50 five-star reviews")
    assert result["accepted"] is False and "fake_social_proof" in result["rules"]
    assert run.add_note("focus on students first")["accepted"] is True
