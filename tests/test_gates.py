"""The gate: thresholds in code can block a GO, and never soften a STOP."""
import gates

GOOD = {k: 4 for k in gates.RUBRIC}


def test_12_of_100_signups_is_stop_or_pivot_never_go():
    result = gates.evaluate(2, {"waitlist_signups": 12}, "go", GOOD)
    assert result.outcome in ("stop", "pivot") and result.outcome != "go"
    assert result.overridden_by_code


def test_waitlist_bands():
    assert gates.evaluate(2, {"waitlist_signups": 100}, "go", GOOD).outcome == "go"
    assert gates.evaluate(2, {"waitlist_signups": 60}, "go", GOOD).outcome == "repeat"
    assert gates.evaluate(2, {"waitlist_signups": 30}, "go", GOOD).outcome == "pivot"
    assert gates.evaluate(2, {"waitlist_signups": 0}, "go", GOOD).outcome == "stop"
    assert gates.evaluate(2, {"waitlist_signups": None}, "go", GOOD).outcome == "repeat"


def test_too_few_sourced_claims_blocks_go():
    assert gates.evaluate(1, {"sourced_claims": 1}, "go", GOOD).outcome == "repeat"
    assert gates.evaluate(1, {"sourced_claims": 1}, "go", GOOD, attempt=2).outcome == "stop"
    assert gates.evaluate(1, {"sourced_claims": 3}, "go", GOOD).outcome == "go"


def test_code_never_softens_the_chair():
    assert gates.evaluate(1, {"sourced_claims": 9}, "stop", GOOD).outcome == "stop"
    assert gates.evaluate(2, {"waitlist_signups": 500}, "pivot", GOOD).outcome == "pivot"


def test_low_rubric_scores_block_go():
    weak = {k: 1 for k in gates.RUBRIC}
    assert gates.evaluate(1, {"sourced_claims": 5}, "go", weak).outcome == "stop"
    assert gates.evaluate(1, {"sourced_claims": 5}, "go", {}).outcome == "repeat"


def test_failed_mvp_or_payment_checks_block_go():
    assert gates.evaluate(3, {"tests_passed": 7, "tests_total": 8}, "go", GOOD).outcome == "repeat"
    assert gates.evaluate(5, {"sale_tests_passed": 8, "sale_tests_total": 9}, "go", GOOD).outcome == "repeat"
    assert gates.evaluate(5, {"sale_tests_passed": 9, "sale_tests_total": 9}, "go", GOOD).outcome == "go"
