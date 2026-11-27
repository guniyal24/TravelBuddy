"""How do you get consistent verdicts from an LLM judge? A ladder of judge designs, each
re-run on the same answers, measuring how often the verdict changes.

    python -m eval.jury_study [--runs 5] [--limit 30] [--seed 7]

Designs, from the simplest to the app's judge (eval/judge.py, v2):

  A  1 judge, one call, free-form fields (judge v1), temperature 0
  B  1 judge, yes/no checklist, one call, temperature 0
  C  1 judge, checklist, 3 samples at temperature 0.7, majority vote  (self-consistency)
  D  2 judges of different families, 3 samples each, majority; a split is "no verdict"
  E  3 judges of different families, 3 samples each, majority        (jury, judge v2)

All designs see the same answers in the same run, and C, D and E are built from the SAME
sampled calls (a juror's 3 samples; 2 of the 3 jurors; all 3), so the comparison isolates the
design rather than luck in the calls. Nothing is cached. Results go to the "jury" section of
eval/RELIABILITY.md and the raw votes to eval/results/<date>-jury-study.json.

Measured per design:
  flip rate         share of answers whose verdict is not the same in every run (lower is
                    better; this is test-retest reliability, cf. Schroeder & Wood-Doughty 2024)
  score swing       how far the headline rate over the sample (e.g. "answers: 63%") moves
                    between runs, max minus min, in percentage points
  no verdict        share of item verdicts left unresolved (2 judges that disagree)
  calls per answer  the price of the design
And for the jury: Fleiss' kappa between the three jurors (do different models agree with
each other, not just with themselves?).

Consistency is not correctness: a judge can be stably wrong. Agreement with human labels is
measured separately (`python -m eval.reliability label`, then `agreement`).
"""
import argparse
import json
import random
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from itertools import combinations
from pathlib import Path

from dotenv import load_dotenv

from eval.judge import ITEMS, JUDGE_VERSION, JuryJudge, VerdictCache, combine, judge_v1
from eval.reliability import _latest_rows, _write_section
from eval.stats import cohen_kappa, fleiss_kappa

ROOT = Path(__file__).resolve().parent
HEADLINE = (("answers_question", "answers the question"), ("declines", "declines"),
            ("invents", "invents specifics"))
LABELS = {
    "A": "1 judge, one call, free-form (v1), temp 0",
    "B": "1 judge, checklist, one call, temp 0",
    "C": "1 judge, checklist, 3 samples, majority",
    "D": "2 judges, 3 samples each, majority",
    "E": "3 judges, 3 samples each, majority (v2)",
}
CALLS = {"A": 1, "B": 1, "C": 3, "D": 6, "E": 9}


def _short(model: str) -> str:
    return model.split("/")[-1]


def judge_once(llm, s, jury: list[str], kb: dict, row: dict) -> dict:
    """Every design's verdict on one answer, from one fresh set of calls."""
    q, a = row["query"], row["answer"]
    sampled = JuryJudge(llm, jury, 3, s.judge_temperature, VerdictCache(None)).raw_votes(q, a)
    greedy = JuryJudge(llm, jury, 1, 0.0, VerdictCache(None)).raw_votes(q, a)
    out = {"A": {"": judge_v1(llm, s.judge_model, q, a, kb)}}
    out["B"] = {_short(m): combine(greedy, [m], 1, a, kb) for m in jury}
    out["C"] = {_short(m): combine(sampled, [m], 3, a, kb) for m in jury}
    out["D"] = {"+".join(_short(m) for m in pair): combine(sampled, list(pair), 3, a, kb)
                for pair in combinations(jury, 2)}
    out["E"] = {"": combine(sampled, jury, 3, a, kb)}
    out["_jurors"] = {_short(m): {i: combine(sampled, [m], 3, a, kb)["items"][i] for i in ITEMS}
                      for m in jury}
    return out


def _verdict(v: dict, key: str):
    """'item:<name>' is a checklist item (None = unresolved); anything else a headline
    verdict. ("declines" is both, so the prefix keeps them apart.)"""
    if key.startswith("item:"):
        name = key.removeprefix("item:")
        return None if name in (v.get("unresolved") or []) else v["items"][name]
    return bool(v[key])


def _flip(runs: list[list[dict]], key: str) -> float:
    n = len(runs[0])
    return sum(len({_verdict(run[i], key) for run in runs}) > 1 for i in range(n)) / n


def _swing(runs: list[list[dict]], key: str) -> float:
    rates = [sum(bool(_verdict(v, key)) for v in run) / len(run) for run in runs]
    return 100 * (max(rates) - min(rates))


def analyse(results: list[list[dict]]) -> dict:
    """results[run][answer] = judge_once(...) output."""
    out = {}
    for design in LABELS:
        variants = results[0][0][design].keys()
        per_variant = {}
        for var in variants:
            runs = [[ans[design][var] for ans in run] for run in results]
            keys = [k for k, _ in HEADLINE] + ([] if design == "A"
                                               else [f"item:{i}" for i in ITEMS])
            per_variant[var] = {
                "flip": {k: _flip(runs, k) for k in keys},
                "swing": {k: _swing(runs, k) for k, _ in HEADLINE},
                "unresolved": (0.0 if design == "A" else statistics.mean(
                    len(v.get("unresolved") or []) / len(ITEMS) for run in runs for v in run)),
            }
        out[design] = per_variant
    jurors = list(results[0][0]["_jurors"])
    fleiss = {i: statistics.mean(
        fleiss_kappa([[ans["_jurors"][j][i] for j in jurors] for ans in run]) or 0.0
        for run in results) for i in ITEMS}
    pairs = {f"{a}+{b}": {i: statistics.mean(
        cohen_kappa([ans["_jurors"][a][i] for ans in run], [ans["_jurors"][b][i] for ans in run])
        or 0.0 for run in results) for i in ITEMS} for a, b in combinations(jurors, 2)}
    return {"designs": out, "fleiss": fleiss, "pairwise": pairs, "jurors": jurors}


def _mean(per_variant: dict, path) -> float:
    return statistics.mean(path(v) for v in per_variant.values())


def report(stats: dict, n: int, runs: int, calls: int) -> str:
    d = stats["designs"]
    lines = [f"## How many judges? ({date.today()})", "",
             f"{n} saved answers (all three systems, random sample) judged {runs} times by each "
             "design, nothing cached. C, D and E reuse the same sampled calls, so they differ "
             "only in how votes are combined. B, C and D are averaged over the three models "
             "(or the three pairs); per-model rows are below. Lower is better everywhere "
             "except kappa.", "",
             "| design | calls per answer | answers: flips | declines: flips | "
             "invents: flips | worst score swing | no verdict |", "|---|---|---|---|---|---|---|"]
    for design, label in LABELS.items():
        pv = d[design]
        flips = [f"{100 * _mean(pv, lambda v, k=k: v['flip'][k]):.0f}%" for k, _ in HEADLINE]
        swing = max(_mean(pv, lambda v, k=k: v["swing"][k]) for k, _ in HEADLINE)
        lines.append(f"| {design}. {label} | {CALLS[design]} | {' | '.join(flips)} | "
                     f"{swing:.1f} pts | {100 * _mean(pv, lambda v: v['unresolved']):.0f}% |")
    lines += ["", "Per checklist item, flip rate:", "",
              "| item | B | C | D | E |", "|---|---|---|---|---|"]
    for item in ITEMS:
        cells = [f"{100 * _mean(d[x], lambda v, i=item: v['flip'][f'item:{i}']):.0f}%"
                 for x in "BCDE"]
        lines.append(f"| {item} | {' | '.join(cells)} |")
    lines += ["", "Per model (one judge) and per pair, flip rate on any headline verdict:", "",
              "| design | variant | answers | declines | invents |", "|---|---|---|---|---|"]
    for design in "BCD":
        for var, v in d[design].items():
            lines.append(f"| {design} | {var} | "
                         + " | ".join(f"{100 * v['flip'][k]:.0f}%" for k, _ in HEADLINE) + " |")
    lines += ["", "Do the three jurors agree with each other? (kappa, averaged over runs; "
              "1 = always agree, 0 = chance)", "",
              "| item | Fleiss (all 3) | " + " | ".join(stats["pairwise"]) + " |",
              "|---|---|" + "---|" * len(stats["pairwise"])]
    for item in ITEMS:
        lines.append(f"| {item} | {stats['fleiss'][item]:.2f} | "
                     + " | ".join(f"{p[item]:.2f}" for p in stats["pairwise"].values()) + " |")
    lines += ["", f"Judge {JUDGE_VERSION}; jurors: {', '.join(stats['jurors'])}. "
              f"{calls} LLM calls in total. Consistency is not correctness: see the human "
              "agreement section."]
    return "\n".join(lines)


def main() -> None:
    from app.config import Settings
    from app.rag.factory import build_llm_clients
    from app.rag.llm import LLM
    from eval.run import kb_index

    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    s = Settings()
    chat, _ = build_llm_clients(s)
    llm = LLM(chat, retries=6)
    kb = kb_index(None)
    jury = [m.strip() for m in s.judge_jury.split(",") if m.strip()]
    rows = _latest_rows()
    random.Random(args.seed).shuffle(rows)
    rows = rows[: args.limit]
    print(f"{len(rows)} answers x {args.runs} runs x 13 calls")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for r in range(args.runs):
            results.append(list(pool.map(lambda row: judge_once(llm, s, jury, kb, row), rows)))
            print(f"  run {r + 1}/{args.runs} done ({llm.calls} calls)")
    stats = analyse(results)
    out = ROOT / "results" / f"{date.today()}-jury-study.json"
    out.write_text(json.dumps({"answers": [{k: x[k] for k in ("id", "system", "query", "answer")}
                                           for x in rows], "stats": stats,
                               "runs": results}, ensure_ascii=False, indent=1, default=str))
    body = report(stats, len(rows), args.runs, llm.calls)
    _write_section("jury", body)
    print(body)


if __name__ == "__main__":
    main()
