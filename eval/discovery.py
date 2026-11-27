"""Compare the two ways the planner finds circuits, from saved eval runs:

  search  Pinecone town profiles -> LLM proposes circuits -> code checks them (the app default)
  rules   score the curated circuit list in code (the previous design, now the fallback)

on both test sets: eval/scenarios.yaml (30 requests, mostly naming towns) and
eval/discovery.yaml (15 open requests that name no town). Writes eval/DISCOVERY.md from the
latest eval/results/<date>-plans[-rules][-discovery].json files; run eval.plans first:

    python -m eval.plans                       # search, scenarios (also writes PLANS.md)
    python -m eval.plans --discovery rules
    python -m eval.plans --set discovery
    python -m eval.plans --set discovery --discovery rules
"""
import json
import statistics
from pathlib import Path

from app.towns import DESTINATIONS
from eval.plans import CHECKS, LABELS
from eval.stats import fmt_rate

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RUNS = {("search", "scenarios"): "plans", ("rules", "scenarios"): "plans-rules",
        ("search", "discovery"): "plans-discovery", ("rules", "discovery"): "plans-rules-discovery"}


def _latest(suffix: str) -> tuple[str, list[dict]] | None:
    files = sorted(RESULTS.glob(f"????-??-??-{suffix}.json"))
    if not files:
        return None
    return files[-1].name[:10], json.loads(files[-1].read_text())


def _rate(rows: list[dict], check: str) -> str:
    vals = [r["score"][check] for r in rows if r.get("score", {}).get(check) is not None]
    return fmt_rate(sum(vals), len(vals))


def _median(rows: list[dict], key: str) -> float:
    vals = [r.get(key) or 0 for r in rows]
    return statistics.median(vals) if vals else 0


def _names(towns: list[str]) -> str:
    return " + ".join(DESTINATIONS.get(t, {}).get("name", t) for t in towns) or "-"


def write_discovery(path: Path = ROOT / "DISCOVERY.md") -> None:
    runs = {k: _latest(v) for k, v in RUNS.items()}
    lines = ["# Circuit discovery: town search + LLM vs rule-based list", "",
             "**search** (app default): Pinecone town profiles find towns that fit the request; "
             "an LLM proposes circuits from those short profiles and road times; code rejects "
             "impossible ones (days, road times, availability) and the rule-based list is the "
             "fallback. Places are then retrieved only for the chosen towns, graded against the "
             "interests, and expanded from the graph. **rules**: the previous design, the "
             "curated circuit list scored in code by season and interest tags.", "",
             "Same code, data, models and day for both; only the circuit step differs. Checks "
             "are computed in code (see `eval/plans.py`); 95% Wilson intervals.", ""]
    for dataset, title in (("scenarios", "30 trip requests (`eval/scenarios.yaml`)"),
                           ("discovery", "15 open requests, no town named "
                                         "(`eval/discovery.yaml`)")):
        s, r = runs[("search", dataset)], runs[("rules", dataset)]
        if not (s and r):
            lines += [f"## {title}", "", "Not run yet.", ""]
            continue
        lines += [f"## {title}", "", f"Runs: search {s[0]}, rules {r[0]}.", "",
                  "| check | search | rules |", "|---|---|---|"]
        for c in CHECKS:
            a, b = _rate(s[1], c), _rate(r[1], c)
            if a == b == "n/a":
                continue
            lines.append(f"| {LABELS[c]} | {a} | {b} |")
        lines += ["", "| per trip (median) | search | rules |", "|---|---|---|",
                  f"| LLM calls | {_median(s[1], 'llm_calls'):.0f} | "
                  f"{_median(r[1], 'llm_calls'):.0f} |",
                  f"| tokens | {_median(s[1], 'tokens'):,.0f} | {_median(r[1], 'tokens'):,.0f} |",
                  f"| agent time | {_median(s[1], 'latency_s'):.0f} s | "
                  f"{_median(r[1], 'latency_s'):.0f} s |",
                  f"| LLM cost | ${_median(s[1], 'cost_usd'):.4f} | "
                  f"${_median(r[1], 'cost_usd'):.4f} |"]
        fell_back = [x["id"] for x in s[1] if (x.get("discovery") or {}).get("fallback")]
        lines += ["", f"Search fell back to the rule-based list in {len(fell_back)} of "
                  f"{len(s[1])} requests" + (f" ({', '.join(fell_back)})." if fell_back else "."),
                  ""]
        if dataset == "discovery":
            by_id = {x["id"]: x for x in r[1]}
            lines += ["First circuit offered:", "", "| request | search | rules |",
                      "|---|---|---|"]
            for x in s[1]:
                y = by_id.get(x["id"], {})
                text = x["text"] if len(x["text"]) <= 60 else x["text"][:57] + "..."
                mark = lambda row: "" if row.get("score", {}).get("fits_first") else " ✗"  # noqa: E731
                lines.append(f"| {x['id']} {text} | {_names(x.get('first_option') or [])}"
                             f"{mark(x)} | {_names(y.get('first_option') or [])}{mark(y)} |")
            lines += ["", "✗ = the first circuit has none of the hand-labelled fitting towns.", ""]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    write_discovery()
    print((ROOT / "DISCOVERY.md").read_text())
