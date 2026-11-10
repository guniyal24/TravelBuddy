"""CI quality gate: fail the build if answer quality (or, optionally, plan quality) regresses.

    python -m eval.run --systems self_rag && python -m eval.gate
    python -m eval.plans && python -m eval.gate --plans

Thresholds apply to the point estimate; the 95% interval is printed beside it so a reader can
see how much of a change is noise at this sample size.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from eval.run import summarize

RESULTS = Path(__file__).parent / "results"
# Minimum / maximum acceptable values (fractions), with headroom for judge noise.
THRESHOLDS = {"hit": (">=", 0.90), "answers": (">=", 0.90), "declines": (">=", 0.80),
              "invents": ("<=", 0.20), "ungrounded": ("<=", 0.10)}
# Plan checks that must hold for (almost) every applicable scenario.
PLAN_THRESHOLDS = {"completes": 0.95, "day_count": 0.95, "meals_in_town": 0.95,
                   "stays_nightly": 0.95, "veg_respected": 0.90, "budget_honest": 0.95,
                   "health_noted": 0.95, "towns_covered": 0.80, "no_fallback": 0.85}


def to_fraction(text: str) -> float | None:
    return None if text == "n/a" else float(text.rstrip("%")) / 100


def check(summary: dict) -> list[str]:
    failures = []
    for key, (op, limit) in THRESHOLDS.items():
        value = to_fraction(summary[key])
        if value is None:
            failures.append(f"{key}: no data")
        elif op == ">=" and value < limit or op == "<=" and value > limit:
            ci = summary.get(f"{key}_ci", "")
            failures.append(f"{key} = {value:.0%} (needs {op} {limit:.0%}){' ' + ci if ci else ''}")
    # Unreliable data fails the gate rather than skewing the rates.
    if summary.get("judge_incomplete"):
        failures.append(f"{summary['judge_incomplete']} judgements are missing jury votes")
    if summary.get("answer_errors"):
        failures.append(f"{summary['answer_errors']} answers failed with an error")
    return failures


def check_plans(rows: list[dict]) -> list[str]:
    failures = []
    for key, limit in PLAN_THRESHOLDS.items():
        vals = [r["score"][key] for r in rows if r["score"].get(key) is not None]
        if not vals:
            continue
        rate = sum(vals) / len(vals)
        if rate < limit:
            failures.append(f"{key} = {rate:.0%} over {len(vals)} scenarios (needs >= {limit:.0%})")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", action="store_true", help="gate plan quality instead")
    args = ap.parse_args()
    if args.plans:
        rows = json.loads((RESULTS / f"{date.today()}-plans.json").read_text())
        failures = check_plans(rows)
        label = "Plan quality"
    else:
        summary = summarize(json.loads((RESULTS / f"{date.today()}-self_rag.json").read_text()))
        failures = check(summary)
        label = "Self-RAG"
        for key in THRESHOLDS:
            print(f"  {key:<11} {summary.get(f'{key}_ci', summary[key])}")
    if failures:
        print(f"EVAL GATE FAILED ({label}):\n  " + "\n  ".join(failures))
        return 1
    print(f"Eval gate passed ({label}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
