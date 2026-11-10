from eval.gate import check

GOOD = {"hit": "100%", "answers": "100%", "declines": "100%", "invents": "0%", "ungrounded": "0%"}


def test_gate_passes_good_summary():
    assert check(GOOD) == []


def test_gate_flags_each_regression_and_missing_data():
    bad = {**GOOD, "hit": "50%", "invents": "40%", "declines": "n/a"}
    msgs = " ".join(check(bad))
    assert "hit = 50%" in msgs and "invents = 40%" in msgs and "declines: no data" in msgs
