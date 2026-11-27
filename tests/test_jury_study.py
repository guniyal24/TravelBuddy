"""The judge-design study: designs share calls, flips and swings are counted correctly."""
import itertools
from types import SimpleNamespace

from eval.judge import ITEMS
from eval.jury_study import analyse, judge_once, report
from eval.stats import fleiss_kappa

JURY = ["fam/steady", "fam/flaky", "fam/contrary"]
ROW = {"query": "Best temple in Haridwar?", "answer": "Visit Har Ki Pauri."}
KB = {"names": ["har ki pauri"], "text": " har ki pauri "}


class FakeLLM:
    """steady: always yes; contrary: always no; flaky: alternates on every call."""
    def __init__(self):
        self.calls, self._flip = 0, itertools.cycle([True, False])

    def json(self, model, messages, default=None, **kw):
        self.calls += 1
        if "steady" in model or "Llama" in model:
            yes = True
        elif "contrary" in model:
            yes = False
        else:
            yes = next(self._flip)
        word = "yes" if yes else "no"
        return {**{i: word for i in ITEMS}, "named_places": ["Har Ki Pauri"],
                "answers_question": yes, "declines": False, "invents_specifics": False}


def settings():
    return SimpleNamespace(judge_temperature=0.7, judge_model="meta/Llama-judge")


def test_one_answer_uses_13_calls_and_every_design():
    llm = FakeLLM()
    out = judge_once(llm, settings(), JURY, KB, ROW)
    assert llm.calls == 13  # 9 sampled jury calls + 3 greedy + 1 v1
    assert set(out) == {"A", "B", "C", "D", "E", "_jurors"}
    assert set(out["D"]) == {"steady+flaky", "steady+contrary", "flaky+contrary"}
    # steady vs contrary is a 1-1 split between judges: no verdict (the fake answers
    # "declines" with the same False for both, so that item is agreed)
    assert set(out["D"]["steady+contrary"]["unresolved"]) == set(ITEMS) - {"declines"}
    assert out["C"]["steady"]["items"]["on_topic"] is True


def test_flip_rate_and_swing_pick_up_an_unstable_judge():
    llm = FakeLLM()
    results = [[judge_once(llm, settings(), JURY, KB, ROW) for _ in range(2)] for _ in range(3)]
    stats = analyse(results)
    steady = stats["designs"]["C"]["steady"]
    assert steady["flip"]["item:on_topic"] == 0 and steady["swing"]["declines"] == 0
    assert stats["designs"]["E"][""]["unresolved"] >= 0
    text = report(stats, n=2, runs=3, calls=llm.calls)
    assert "| A. 1 judge, one call" in text and "Fleiss" in text


def test_fleiss_kappa_extremes():
    assert fleiss_kappa([[True] * 3, [False] * 3]) == 1.0
    assert fleiss_kappa([[True, False]] * 4) < 0
    assert fleiss_kappa([]) is None and fleiss_kappa([[True]]) is None
