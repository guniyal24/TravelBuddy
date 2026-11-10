"""Ablation table: what each component contributes, measured by switching it off.

    python -m eval.plans --ablate critic
    python -m eval.plans --ablate food
    python -m eval.ablations          # rebuild ABLATIONS.md from the latest saved runs

Every saved run is re-scored with the same code checks (eval/plans.py `score`), so the full
system and the ablated ones are compared on identical criteria.
"""
import json
from datetime import date
from pathlib import Path

import yaml

from eval.plans import CHECKS, LABELS, score
from eval.stats import fmt_rate

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
VARIANTS = [("full system", "plans"), ("without the Critic", "plans-no-critic"),
            ("without the Food agent", "plans-no-food")]


def _latest(stem: str) -> list[dict] | None:
    files = sorted(RESULTS.glob(f"*-{stem}.json"))
    return json.loads(files[-1].read_text()) if files else None


def write_ablations() -> None:
    scenarios = {s["id"]: s for s in
                 yaml.safe_load((ROOT / "scenarios.yaml").read_text())["scenarios"]}
    cols = []
    for label, stem in VARIANTS:
        rows = _latest(stem)
        if rows:
            scores = [score(scenarios[r["id"]], r) for r in rows]
            if stem == "plans-no-critic":  # nothing checks the draft, so these say nothing
                for s in scores:
                    s["valid_first_try"] = s["no_fallback"] = "not checked"
            cols.append((label, scores))
    lines = [f"# Ablations ({date.today()})", "",
             "Each component switched off in turn, on the same 30 trip requests "
             "(`eval/scenarios.yaml`), scored by the same code checks. A drop shows what the "
             "component prevents.", "",
             "| check | " + " | ".join(c[0] for c in cols) + " |",
             "|---|" + "---|" * len(cols)]
    for check in CHECKS:
        cells = []
        for _, scores in cols:
            if any(s.get(check) == "not checked" for s in scores):
                cells.append("not checked")
                continue
            vals = [s[check] for s in scores if s.get(check) is not None]
            cells.append(fmt_rate(sum(vals), len(vals)) if vals else "n/a")
        lines.append(f"| {LABELS[check]} | " + " | ".join(cells) + " |")
    trips_with_errors = {}
    for label, scores in cols:
        bad = [s for s in scores if any(v is False for k, v in s.items()
                                        if k not in ("valid_first_try", "no_fallback"))]
        trips_with_errors[label] = (len(bad), len(scores))
    lines += ["", "**Trips with at least one error a traveller would see:** " + "; ".join(
        f"{label}: {b} of {n}" for label, (b, n) in trips_with_errors.items()) + ".", "",
        "Without the Critic the first LLM draft is accepted as it is; without the "
        "Food agent eateries are not filtered for vegetarian travellers (5 scenarios).",
              "The answer-level ablations (no retrieval, plain RAG, Self-RAG) are in "
              "[RESULTS.md](RESULTS.md); single judge vs jury in "
              "[RELIABILITY.md](RELIABILITY.md).", ""]
    (ROOT / "ABLATIONS.md").write_text("\n".join(lines))


if __name__ == "__main__":
    write_ablations()
    print((ROOT / "ABLATIONS.md").read_text())
