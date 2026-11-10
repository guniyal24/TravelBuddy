from eval.run import in_kb, pct, summarize
from ingest.osm import normalize

KB = {"names": [normalize(n) for n in ["Mansa Devi Temple", "Hotel Ganga Kinare", "Bhatt ki Churkani"]],
      "text": " " + normalize("Chandi Devi sits on the Neel Parvat near Kankhal") + " "}


def test_in_kb_exact_fuzzy_and_containment():
    assert in_kb("Mansa Devi Temple", KB)
    assert in_kb("Ganga Kinare", KB)          # noise word removed
    assert in_kb("Bhat ki Churkani", KB)       # small typo
    assert not in_kb("Taj Hotel Rishikesh Palace", KB)


def test_place_mentioned_only_in_a_description_counts_as_grounded():
    assert in_kb("Neel Parvat", KB) and in_kb("Kankhal", KB)
    assert not in_kb("Maestro Galleria", KB)


def row(kind, hit=False, declines=False, invents=False, ung=None, answers=True):
    return {"kind": kind, "hit": hit, "has_context": True, "llm_calls": 2, "latency_s": 1.0,
            "judge": {"declines": declines, "invents": invents, "answers_question": answers,
                      "ungrounded_places": ung or []}}


def test_summarize_metrics():
    rows = [row("answerable", hit=True), row("answerable", hit=False, ung=["X"]),
            row("unanswerable", declines=True), row("unanswerable", invents=True)]
    s = summarize(rows)
    assert s["hit"] == "50%" and s["ungrounded"] == "50%"
    assert s["declines"] == "50%" and s["invents"] == "50%"
    assert pct([]) == "n/a"
