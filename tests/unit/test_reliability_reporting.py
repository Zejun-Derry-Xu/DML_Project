from scripts.report_reliability import asserted, score_claims


def test_false_is_a_claim_but_intent_and_human_defaults_are_not():
    assert asserted("stained", False)
    assert not asserted("stained", None)
    assert not asserted("intent", "unclear")
    assert not asserted("wants_human", False)
    assert asserted("intent", "return")


def test_common_claims_do_not_credit_new_field_support():
    rows = [
        {
            "actual": {"used": False, "stained": False, "intent": "return"},
            "expected": {"used": None, "stained": False, "intent": "unclear"},
        }
    ]
    scored = score_claims(rows, {"used", "intent"})
    assert scored == {"unsupported": 2, "asserted": 2, "rate": 1.0}
