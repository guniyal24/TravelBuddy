"""CI quality gate: fail the build if Self-RAG quality regresses.

    python -m eval.run --systems self_rag && python -m eval.gate
"""
import json
import sys
from datetime import date
from pathlib import Path

from eval.run import summarize

# Minimum / maximum acceptable values (fractions). Tuned from the first full run
# (hit 100%, answers 100%, declines 100%, invents 0%) with headroom for judge noise.
THRESHOLDS = {"hit": (">=", 0.90), "answers": (">=", 0.90), "declines": (">=", 0.80),
              "invents": ("<=", 0.20), "ungrounded": ("<=", 0.10)}


def to_fraction(text: str) -> float | None:
    return None if text == "n/a" else float(text.rstrip("%")) / 100


def check(summary: dict) -> list[str]:
    failures = []
    for key, (op, limit) in THRESHOLDS.items():
        value = to_fraction(summary[key])
        if value is None:
            failures.append(f"{key}: no data")
        elif op == ">=" and value < limit or op == "<=" and value > limit:
            failures.append(f"{key} = {value:.0%} (needs {op} {limit:.0%})")
    return failures


def main() -> int:
    f = Path(__file__).parent / "results" / f"{date.today()}-self_rag.json"
    summary = summarize(json.loads(f.read_text()))
    failures = check(summary)
    print("Self-RAG:", summary)
    if failures:
        print("EVAL GATE FAILED:\n  " + "\n  ".join(failures))
        return 1
    print("Eval gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
