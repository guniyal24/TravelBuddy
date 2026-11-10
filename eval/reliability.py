"""How much can the judge be trusted? Three commands, results in eval/RELIABILITY.md.

  python -m eval.reliability flip [--runs 5] [--limit 30]
      Re-judge the same saved answers several times, uncached, with the v1 judge and the v2
      jury. Reports the flip rate: the share of answers whose verdict is not the same on every
      run. A reliable judge is close to 0%.

  python -m eval.reliability label [--n 80]
      Label answers yourself in the terminal (y / n per checklist question; s skips, q quits).
      Answers are drawn from every system's latest results, so the labels contain good and bad
      answers. Saved to eval/labels/labels.yaml, which is committed as the human gold set.

  python -m eval.reliability agreement
      Compares each judge with your labels: Cohen's kappa (chance-corrected, the right measure;
      percent agreement can look high while the judge disagrees with you a lot) and plain
      agreement, per metric.
"""
import argparse
import hashlib
import json
import random
import re
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

from eval.judge import CHECKLIST, ITEMS, JUDGE_VERSION, JuryJudge, VerdictCache, judge_v1
from eval.stats import cohen_kappa, flip_rate

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
LABELS = ROOT / "labels" / "labels.yaml"
REPORT = ROOT / "RELIABILITY.md"
# Metrics compared between judges and humans. v1 has no checklist, so its fields map onto them.
METRICS = {
    "answers": ("answers the question", lambda v: v["answers_question"]),
    "declines": ("declines", lambda v: v["declines"]),
    "specifics": ("states specifics as fact", None),
}


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _latest_rows() -> list[dict]:
    rows = []
    for system in ("self_rag", "baseline", "no_rag"):
        files = sorted(RESULTS.glob(f"*-{system}.json"))
        if files:
            for r in json.loads(files[-1].read_text()):
                if not r["answer"].startswith("[error"):
                    rows.append({**r, "system": system})
    return rows


def _setup():
    from app.config import Settings
    from app.db.graph import GraphStore
    from app.rag.factory import build_llm_clients
    from app.rag.llm import LLM
    from eval.run import kb_index

    load_dotenv()
    s = Settings()
    store = GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database)
    chat, _ = build_llm_clients(s)
    jury = [m.strip() for m in s.judge_jury.split(",") if m.strip()]
    return s, LLM(chat, retries=6), kb_index(store), jury


def _write_section(name: str, body: str) -> None:
    """Replace one marked section of RELIABILITY.md, keeping the others."""
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    text = REPORT.read_text() if REPORT.exists() else (
        "# Judge reliability\n\nCan the LLM judge in `eval/judge.py` be trusted? Two checks: "
        "does it give the same verdict when asked again (flip rate), and does it agree with "
        "a human (Cohen's kappa)? Regenerate with `python -m eval.reliability`.\n\n"
        "<!-- flip:start -->\n<!-- flip:end -->\n\n<!-- agreement:start -->\n"
        "<!-- agreement:end -->\n")
    block = f"{start}\n{body.strip()}\n{end}"
    if start in text:
        text = re.sub(re.escape(start) + r".*?" + re.escape(end), lambda _: block, text,
                      flags=re.DOTALL)
    else:
        text += "\n" + block + "\n"
    REPORT.write_text(text)


# ---------------------------------------------------------------- flip rate
def cmd_flip(runs: int, limit: int, seed: int) -> None:
    s, llm, kb, jury = _setup()
    rows = _latest_rows()
    random.Random(seed).shuffle(rows)
    rows = rows[:limit]
    print(f"Re-judging {len(rows)} answers x {runs} runs (v1 and v2, uncached)...")
    jj = JuryJudge(llm, jury, s.judge_samples, s.judge_temperature, VerdictCache(None))
    v1_runs, v2_runs = [], []
    for r in range(runs):
        v1_runs.append([judge_v1(llm, s.judge_model, x["query"], x["answer"], kb) for x in rows])
        v2_runs.append([jj(x["query"], x["answer"], kb) for x in rows])
        print(f"  run {r + 1}/{runs} done")

    def rate(all_runs, get):
        return flip_rate([[bool(get(v)) for v in run] for run in all_runs])

    lines = [f"## Flip rate ({date.today()})", "",
             f"The same {len(rows)} saved answers (mixed systems, random sample) judged "
             f"{runs} times, without cache. Share of answers whose verdict changed at least "
             "once. Lower is better.", "",
             "| verdict | v1: one call, temperature 0 | v2: checklist jury |", "|---|---|---|"]
    for key, label in (("answers_question", "answers the question"), ("declines", "declines"),
                       ("invents", "invents specifics")):
        lines.append(f"| {label} | {100 * rate(v1_runs, lambda v, k=key: v[k]):.0f}% | "
                     f"{100 * rate(v2_runs, lambda v, k=key: v[k]):.0f}% |")
    lines += ["", "v2 per checklist item:", "", "| item | flip rate |", "|---|---|"]
    for item in ITEMS:
        lines.append(f"| {item} | {100 * rate(v2_runs, lambda v, i=item: v['items'][i]):.0f}% |")
    lines += ["", f"Judge {JUDGE_VERSION}; jury: {', '.join(m.split('/')[-1] for m in jury)}; "
              f"{s.judge_samples} samples per juror at temperature {s.judge_temperature}. "
              f"v1: {s.judge_model.split('/')[-1]}. Cost: {llm.calls} LLM calls."]
    _write_section("flip", "\n".join(lines))
    print("\n".join(lines))


# ---------------------------------------------------------------- human labels
def _load_labels() -> list[dict]:
    if LABELS.exists():
        return yaml.safe_load(LABELS.read_text()) or []
    return []


def _save_labels(labels: list[dict]) -> None:
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    LABELS.write_text(yaml.safe_dump(labels, allow_unicode=True, sort_keys=False, width=100))


def cmd_label(n: int, seed: int) -> None:
    labels = _load_labels()
    done = {x["answer_hash"] for x in labels}
    rows = [r for r in _latest_rows() if _h(r["answer"]) not in done]
    random.Random(seed).shuffle(rows)
    todo = rows[:max(0, n - len(labels))]
    print(f"{len(labels)} labelled so far; {len(todo)} to go. y = yes, n = no, s = skip answer, "
          "q = save and quit.\n")
    for r in todo:
        print("=" * 78)
        print(f"[{len(labels) + 1}/{n}]  ({r['system']}, {r['id']})\nQUESTION: {r['query']}\n")
        print(f"ANSWER:\n{r['answer']}\n")
        entry, skip = {}, False
        for item, text in CHECKLIST.items():
            while True:
                a = input(f"{item}: {text} [y/n/s/q] ").strip().lower()
                if a in ("y", "n"):
                    entry[item] = a == "y"
                    break
                if a == "s":
                    skip = True
                    break
                if a == "q":
                    _save_labels(labels)
                    print(f"Saved {len(labels)} labels to {LABELS}.")
                    return
            if skip:
                break
        if skip:
            continue
        labels.append({"id": r["id"], "system": r["system"], "kind": r["kind"],
                       "query": r["query"], "answer": r["answer"],
                       "answer_hash": _h(r["answer"]), **entry})
        _save_labels(labels)
    print(f"Done: {len(labels)} labels in {LABELS}.")


# ---------------------------------------------------------------- agreement
def cmd_agreement() -> None:
    labels = _load_labels()
    if len(labels) < 10:
        raise SystemExit(f"Only {len(labels)} labels; label at least 10 (aim for 60+) first: "
                         "python -m eval.reliability label")
    s, llm, kb, jury = _setup()
    jj = JuryJudge(llm, jury, s.judge_samples, s.judge_temperature, VerdictCache())
    human = {"answers": [x["on_topic"] and x["concrete"] for x in labels],
             "declines": [x["declines"] for x in labels],
             "specifics": [x["specifics"] for x in labels]}
    v1 = [judge_v1(llm, s.judge_model, x["query"], x["answer"], kb) for x in labels]
    v2 = [jj(x["query"], x["answer"], kb) for x in labels]
    judges = {
        "v1": {"answers": [v["answers_question"] for v in v1],
               "declines": [v["declines"] for v in v1],
               "specifics": [v["specifics"] for v in v1]},
        "v2": {"answers": [v["answers_question"] for v in v2],
               "declines": [v["items"]["declines"] for v in v2],
               "specifics": [v["items"]["specifics"] for v in v2]},
    }

    def cell(a, b):
        k = cohen_kappa(a, b)
        agree = sum(x == y for x, y in zip(a, b, strict=True)) / len(a)
        return f"{k:.2f}" if k is not None else "n/a", f"{100 * agree:.0f}%"

    lines = [f"## Agreement with human labels ({date.today()})", "",
             f"{len(labels)} answers labelled by hand (`eval/labels/labels.yaml`), drawn from "
             "all three systems. Cohen's kappa: 1 = perfect, 0 = chance level; above 0.6 is "
             "usually read as substantial agreement.", "",
             "| metric | v1 kappa | v1 agreement | v2 kappa | v2 agreement | human 'yes' rate |",
             "|---|---|---|---|---|---|"]
    for key, (label, _) in METRICS.items():
        k1, a1 = cell(judges["v1"][key], human[key])
        k2, a2 = cell(judges["v2"][key], human[key])
        yes = 100 * sum(human[key]) / len(labels)
        lines.append(f"| {label} | {k1} | {a1} | {k2} | {a2} | {yes:.0f}% |")
    low = [x["id"] for x, v in zip(labels, v2, strict=True)
           if min(v["agreement"].values()) < 0.67]
    lines += ["", f"v2 items where the jury itself was split (under 67% of votes agreeing): "
              f"{len(low)} of {len(labels)} answers. These are the ones worth a human look."]
    _write_section("agreement", "\n".join(lines))
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("flip")
    f.add_argument("--runs", type=int, default=5)
    f.add_argument("--limit", type=int, default=30)
    f.add_argument("--seed", type=int, default=7)
    lab = sub.add_parser("label")
    lab.add_argument("--n", type=int, default=80)
    lab.add_argument("--seed", type=int, default=7)
    sub.add_parser("agreement")
    args = ap.parse_args()
    if args.cmd == "flip":
        cmd_flip(args.runs, args.limit, args.seed)
    elif args.cmd == "label":
        cmd_label(args.n, args.seed)
    else:
        cmd_agreement()


if __name__ == "__main__":
    main()
