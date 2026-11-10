"""Judge v2 (checklist jury), the statistics behind the reports, and plan-quality scoring."""
import json

import pytest

from eval.gate import check_plans
from eval.judge import ITEMS, JuryJudge, VerdictCache, _majority, _yes, appears_in
from eval.plans import CHECKS, score
from eval.stats import cohen_kappa, flip_rate, fmt_rate, wilson
from ingest.osm import normalize

KB = {"names": [normalize("Mansa Devi Temple"), normalize("Hotel Golden")],
      "text": " " + normalize("near the Neel Parvat") + " "}
ANSWER = "Visit Mansa Devi Temple by cable car, then stay at Hotel Golden or Hotel Fakeview."


class ScriptedLLM:
    """Returns a scripted JSON verdict per (model, call number for that model)."""

    def __init__(self, script):
        self.script, self.seen, self.calls = script, {}, 0

    def json(self, model, messages, default=None, max_tokens=600, temperature=0.0):
        self.calls += 1
        n = self.seen.get(model, 0)
        self.seen[model] = n + 1
        verdicts = self.script[model]
        return verdicts[n % len(verdicts)]


def v(on_topic="yes", concrete="yes", declines="no", specifics="no", places=()):
    return {"reasoning": "x", "on_topic": on_topic, "concrete": concrete, "declines": declines,
            "specifics": specifics, "named_places": list(places)}


# ---------- voting ----------
def test_yes_no_parsing_and_majority():
    assert _yes("Yes.") is True and _yes(" no ") is False and _yes("maybe") is None
    assert _majority([True, True, False]) is True
    assert _majority([True, False]) is None  # a tie is no verdict
    assert _majority([None, None]) is None


def test_jury_majority_beats_one_outlier_and_reports_agreement():
    llm = ScriptedLLM({
        "a": [v(specifics="yes")], "b": [v()], "c": [v()],
    })
    out = JuryJudge(llm, ["a", "b", "c"], samples=3)("Q?", ANSWER, KB)
    assert out["items"]["specifics"] is False  # juror a is outvoted 2 to 1
    assert out["agreement"]["specifics"] == pytest.approx(6 / 9)
    assert out["agreement"]["on_topic"] == 1.0
    assert out["answers_question"] is True and llm.calls == 9


def test_within_juror_samples_are_majority_voted():
    llm = ScriptedLLM({"a": [v(declines="yes"), v(), v()], "b": [v()], "c": [v()]})
    out = JuryJudge(llm, ["a", "b", "c"], samples=3)("Q?", ANSWER, KB)
    assert out["votes"]["declines"] == {"a": False, "b": False, "c": False}


# ---------- code checks on the judge ----------
def test_extracted_names_must_appear_in_the_answer_and_are_checked_against_the_kb():
    llm = ScriptedLLM({m: [v(places=["Mansa Devi Temple", "Hotel Fakeview", "Taj Palace"])]
                       for m in "abc"})
    out = JuryJudge(llm, ["a", "b", "c"], samples=1)("Q?", ANSWER, KB)
    assert out["named_places"] == ["Mansa Devi Temple", "Hotel Fakeview"]  # Taj Palace dropped
    assert out["ungrounded_places"] == ["Hotel Fakeview"]


def test_invents_needs_a_specific_or_an_ungrounded_place_and_no_decline():
    def run(**kw):
        llm = ScriptedLLM({m: [v(**kw)] for m in "abc"})
        return JuryJudge(llm, ["a", "b", "c"], samples=1)("Q?", "Nothing named here.", KB)
    assert run(specifics="yes")["invents"] is True
    assert run(specifics="yes", declines="yes")["invents"] is False
    assert run()["invents"] is False


def test_appears_in_tolerates_small_spelling_differences():
    assert appears_in("Mansa Devi Temple", ANSWER)
    assert appears_in("Mansa Devi Tempel", ANSWER)
    assert not appears_in("Chandi Devi Temple", ANSWER)


# ---------- cache ----------
def test_cache_makes_reruns_identical_and_free(tmp_path):
    cache = VerdictCache(tmp_path / "c.sqlite")
    first = ScriptedLLM({m: [v(specifics="yes")] for m in "abc"})
    a = JuryJudge(first, ["a", "b", "c"], samples=2, cache=cache)("Q?", ANSWER, KB)
    second = ScriptedLLM({m: [v(specifics="no")] for m in "abc"})  # would disagree if asked
    b = JuryJudge(second, ["a", "b", "c"], samples=2, cache=cache)("Q?", ANSWER, KB)
    assert second.calls == 0 and a["items"] == b["items"]


def test_failed_calls_are_not_cached(tmp_path):
    cache = VerdictCache(tmp_path / "c.sqlite")
    broken = ScriptedLLM({m: [{}] for m in "abc"})
    JuryJudge(broken, ["a", "b", "c"], samples=1, cache=cache)("Q?", ANSWER, KB)
    ok = ScriptedLLM({m: [v()] for m in "abc"})
    JuryJudge(ok, ["a", "b", "c"], samples=1, cache=cache)("Q?", ANSWER, KB)
    assert ok.calls == 3


# ---------- statistics ----------
def test_wilson_interval_is_sane_at_the_edges():
    lo, hi = wilson(0, 20)
    assert lo == 0.0 and 0.1 < hi < 0.2
    lo, hi = wilson(20, 20)
    assert hi == 1.0 and 0.8 < lo < 0.9
    assert wilson(0, 0) == (0.0, 1.0)
    assert fmt_rate(17, 20) == "85% (64-95%)"


def test_cohen_kappa_corrects_for_chance():
    human = [True] * 9 + [False]
    always_yes = [True] * 10
    assert cohen_kappa(always_yes, human) == pytest.approx(0.0)  # 90% agreement, kappa 0
    assert cohen_kappa(human, human) == pytest.approx(1.0)
    assert cohen_kappa([], []) is None
    with pytest.raises(ValueError):
        cohen_kappa([True], [True, False])


def test_flip_rate_counts_items_that_ever_change():
    assert flip_rate([[True, False, True], [True, True, True], [True, False, True]]) == 1 / 3
    assert flip_rate([[True], [True]]) == 0.0


# ---------- plan scoring ----------
def _run(**over):
    ents = {"a1": {"destination_id": "destination_nainital", "name": "Snow View"},
            "m1": {"destination_id": "destination_nainital", "name": "Chandni Chowk",
                   "description": "pure vegetarian"},
            "s1": {"destination_id": "destination_nainital", "name": "Hotel"},
            "m2": {"destination_id": "destination_almora", "name": "Courtyard Bar"}}
    run = {"reached": "approve", "first_option": ["destination_nainital"], "plan_attempts": 1,
           "plan": {"days": [
               {"day": 1, "destination": "destination_nainital", "stops": ["a1"], "meals": ["m1"],
                "stay": "s1"},
               {"day": 2, "destination": "destination_nainital", "stops": [], "meals": [],
                "stay": None}]},
           "entities": ents, "warnings": [], "cost": {"total_inr": [5000, 9000]}}
    run.update(over)
    return run


def test_plan_score_all_good():
    sc = {"expect": {"days": 2, "towns": ["destination_nainital"], "veg": True, "budget": 6000}}
    s = score(sc, _run())
    assert all(s[c] for c in ["completes", "day_count", "towns_covered", "named_first",
                              "meals_in_town", "stays_nightly", "veg_respected",
                              "budget_honest", "valid_first_try", "no_fallback"])
    assert s["health_noted"] is None  # not applicable
    assert set(s) == set(CHECKS)


def test_plan_score_catches_each_problem():
    bad_days = [{"day": 1, "destination": "destination_nainital", "stops": [],
                 "meals": ["m2"], "stay": None},
                {"day": 2, "destination": "destination_nainital", "stops": [], "meals": [],
                 "stay": None}]
    sc = {"expect": {"days": 3, "towns": ["destination_nainital", "destination_almora"],
                     "veg": True, "budget": 1000, "health": True}}
    s = score(sc, _run(plan={"days": bad_days}, plan_attempts=3,
                       warnings=["The AI planner could not produce a valid plan, so a simple "
                                 "automatic plan was used."]))
    for c in ["day_count", "towns_covered", "named_first", "meals_in_town", "stays_nightly",
              "veg_respected", "budget_honest", "health_noted", "valid_first_try",
              "no_fallback"]:
        assert s[c] is False, c


def test_budget_over_is_fine_when_the_plan_says_so():
    sc = {"expect": {"budget": 1000}}
    s = score(sc, _run(warnings=["Estimated cost starts at ₹5,000, above your budget of ₹1,000."]))
    assert s["budget_honest"] is True


def test_unfinished_plan_only_scores_completion():
    s = score({"expect": {"days": 2}}, {"reached": "error: boom"})
    assert s["completes"] is False and s["day_count"] is None


def test_plan_gate_flags_low_rates():
    rows = [{"score": {"meals_in_town": True}}, {"score": {"meals_in_town": False}}]
    assert any("meals_in_town = 50%" in f for f in check_plans(rows))
    assert check_plans([{"score": {"meals_in_town": True}}]) == []


def test_checklist_items_are_stable():
    # Changing these changes what the cache and the human labels mean.
    assert ITEMS == ("on_topic", "concrete", "declines", "specifics")
    assert json.dumps(ITEMS)


# ---------- failures are visible, never silent ----------
def test_failed_jury_calls_mark_the_verdict_incomplete():
    llm = ScriptedLLM({"a": [{}], "b": [v()], "c": [v()]})
    out = JuryJudge(llm, ["a", "b", "c"], samples=2)("Q?", ANSWER, KB)
    assert out["complete"] is False and out["failed_calls"] == 2
    assert out["items"]["on_topic"] is True  # the two working jurors still decide


def test_gate_fails_on_incomplete_judgements_and_answer_errors():
    from eval.gate import check
    good = {"hit": "100%", "answers": "100%", "declines": "100%", "invents": "0%",
            "ungrounded": "0%"}
    assert check(good) == []
    msgs = " ".join(check({**good, "judge_incomplete": 2, "answer_errors": 1}))
    assert "2 judgements are missing jury votes" in msgs and "1 answers failed" in msgs


def test_llm_retries_rate_limits_then_succeeds(monkeypatch):
    import httpx
    import openai

    from app.rag.llm import LLM

    monkeypatch.setattr("time.sleep", lambda s: None)
    req = httpx.Request("POST", "https://x")
    busy = openai.RateLimitError("busy", response=httpx.Response(429, request=req), body=None)

    class Msg:
        content = '{"ok": true}'

    class Resp:
        choices = [type("C", (), {"message": Msg()})()]
        usage = None

    class Completions:
        def __init__(self):
            self.n = 0

        def create(self, **kw):
            self.n += 1
            if self.n < 3:
                raise busy
            return Resp()

    comp = Completions()
    client = type("Cl", (), {"chat": type("Ch", (), {"completions": comp})()})()
    llm = LLM(client, retries=3)
    assert llm.json("m", [{"role": "user", "content": "x"}]) == {"ok": True}
    assert llm.retried == 2 and llm.calls == 1
    comp.n = 0
    assert LLM(client, retries=0).json("m", [], default={"d": 1}) == {"d": 1}  # fail fast
