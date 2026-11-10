"""Plan-quality evaluation: run the real trip planner on eval/scenarios.yaml and score every
plan in code (no LLM judge), so the numbers are exactly reproducible from the saved plans.

    python -m eval.plans [--limit N] [--only p01 p02]

Checks, each reported as a pass rate with a 95% interval over the scenarios it applies to:
  completes        the planner reached the approval step without an error
  day_count        the plan has exactly the requested number of days
  towns_covered    every town the traveller named is in the plan
  named_first      the first circuit offered covers the towns the traveller named
  meals_in_town    every stop and meal is in that day's town
  stays_nightly    every night except the last has a stay
  veg_respected    vegetarian travellers get no meat, fish or bar listings
  budget_honest    the estimate fits the budget, or the plan says it does not
  health_noted     vulnerable travellers going above 2,500 m get a health note
  valid_first_try  the LLM's first draft passed the Critic (no retry, no fallback)
  no_fallback      the plan came from the LLM, not the rule-based fallback
Writes eval/PLANS.md and the raw plans to eval/results/<date>-plans.json.
"""
import argparse
import json
import logging
import statistics
import time
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

from app.graph.agents import NON_VEG, _text
from eval.stats import fmt_rate

ROOT = Path(__file__).resolve().parent
CHECKS = ["completes", "day_count", "towns_covered", "named_first", "meals_in_town",
          "stays_nightly", "veg_respected", "budget_honest", "health_noted", "valid_first_try",
          "no_fallback"]
LABELS = {
    "completes": "reaches the approval step", "day_count": "exact number of days",
    "towns_covered": "includes every named town", "named_first": "named towns offered first",
    "meals_in_town": "stops and meals in that day's town", "stays_nightly": "a stay every night",
    "veg_respected": "veg diet respected", "budget_honest": "budget fits or is flagged",
    "health_noted": "health note above 2,500 m", "valid_first_try": "LLM draft valid first try",
    "no_fallback": "no rule-based fallback needed",
}
log = logging.getLogger(__name__)


def score(sc: dict, run: dict) -> dict:
    """Code-only checks for one scenario. None = check does not apply."""
    exp = sc.get("expect", {})
    out: dict[str, bool | None] = dict.fromkeys(CHECKS)
    out["completes"] = run.get("reached") == "approve"
    if not out["completes"]:
        return out
    plan, ents = run["plan"], run["entities"]
    days = plan.get("days") or []
    dests = {d["destination"] for d in days}
    warnings = run.get("warnings") or []
    out["day_count"] = len(days) == exp.get("days", len(days))
    towns = exp.get("towns") or []
    if towns:
        out["towns_covered"] = set(towns) <= dests
        out["named_first"] = set(towns) <= set(run.get("first_option", []))
    out["meals_in_town"] = all(
        ents.get(i, {}).get("destination_id") in (None, d["destination"])
        for d in days for i in [*(d.get("stops") or []), *(d.get("meals") or [])])
    out["stays_nightly"] = all(d.get("stay") for d in days if d["day"] < len(days))
    if exp.get("veg"):
        out["veg_respected"] = not any(
            NON_VEG.search(_text(ents.get(i, {}))) for d in days for i in d.get("meals") or [])
    if exp.get("budget"):
        low = (run.get("cost") or {}).get("total_inr", [0])[0]
        out["budget_honest"] = low <= exp["budget"] or any("budget" in w.lower() for w in warnings)
    if exp.get("health"):
        out["health_noted"] = any(w.startswith("Health:") for w in warnings)
    fallback = any("automatic plan was used" in w for w in warnings)
    out["no_fallback"] = not fallback
    out["valid_first_try"] = run.get("plan_attempts") == 1 and not fallback
    return out


def build_planner():
    from pinecone import Pinecone

    from app.config import Settings
    from app.db.graph import GraphStore
    from app.graph.trip_graph import TripPlanner
    from app.rag.factory import build_llm_clients
    from app.rag.llm import LLM
    from app.rag.retriever import Retriever
    from mcp_server.client import LocalTools

    s = Settings()
    chat, embed = build_llm_clients(s)
    index = Pinecone(api_key=s.pinecone_api_key).Index(s.pinecone_index_name)
    llm = LLM(chat, retries=6)  # batch job: wait out rate limits instead of failing
    store = GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database)
    tp = TripPlanner(llm, Retriever(embed, index, s.embed_model), store, s.router_model,
                     s.planner_model, checkpointer=MemorySaver(), tools=LocalTools())
    return tp, llm


def run_scenario(tp, sc: dict) -> dict:
    tid = f"eval-{sc['id']}-{time.time_ns()}"
    towns = set(sc.get("expect", {}).get("towns") or [])
    run: dict = {"id": sc["id"], "text": sc["text"]}
    r = tp.start(tid, sc["text"], owner="eval")
    asks = 0
    while r["status"] == "waiting" and r["prompt"]["type"] == "ask" and asks < 2:
        r = tp.resume(tid, sc.get("followup") or "2 people")
        asks += 1
    if r["status"] == "waiting" and r["prompt"]["type"] == "choose":
        options = r["prompt"]["options"]
        run["first_option"] = options[0]["id"].split("+") if options else []
        pick = next((o["id"] for o in options if towns and towns <= set(o["id"].split("+"))),
                    options[0]["id"])
        r = tp.resume(tid, pick)
    run["reached"] = r["prompt"]["type"] if r["status"] == "waiting" else r["status"]
    vals = tp.graph.get_state({"configurable": {"thread_id": tid}}).values
    used = {i for d in (vals.get("plan") or {}).get("days", [])
            for i in [*(d.get("stops") or []), *(d.get("meals") or []), d.get("stay")] if i}
    run.update({
        "request": vals.get("request"), "plan": vals.get("plan"),
        "entities": {i: {k: e.get(k) for k in ("name", "type", "destination_id", "description",
                                               "semantic_text")}
                     for i, e in (vals.get("entities") or {}).items() if i in used},
        "warnings": vals.get("warnings"), "cost": vals.get("cost"),
        "plan_attempts": vals.get("plan_attempts"), "asks": asks})
    return run


def write_report(rows: list[dict], path: Path) -> None:
    lines = [f"# Plan quality ({date.today()})", "",
             f"{len(rows)} trip requests (`eval/scenarios.yaml`), run through the real planner "
             "(LLM planner, rule-based Critic and agents). Every check is computed in code from "
             "the saved plan; no LLM judge. Rates with 95% Wilson intervals, over the scenarios "
             "each check applies to.", "",
             "| check | pass rate | scenarios |", "|---|---|---|"]
    for c in CHECKS:
        vals = [r["score"][c] for r in rows if r["score"][c] is not None]
        lines.append(f"| {LABELS[c]} | {fmt_rate(sum(vals), len(vals))} | {len(vals)} |")
    fails = [(r["id"], c) for r in rows for c in CHECKS if r["score"][c] is False]
    lat = [r["latency_s"] for r in rows]
    lines += ["", f"Median time to a plan ready for review: {statistics.median(lat):.0f} s "
              f"(max {max(lat):.0f} s); LLM calls per plan: "
              f"{statistics.mean(r['llm_calls'] for r in rows):.1f}.", ""]
    if fails:
        lines += ["Failures:", ""] + [f"- {sid}: {LABELS[c]}" for sid, c in fails] + [""]
    path.write_text("\n".join(lines))


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    scenarios = yaml.safe_load((ROOT / "scenarios.yaml").read_text())["scenarios"]
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in args.only]
    if args.limit:
        scenarios = scenarios[: args.limit]
    tp, llm = build_planner()
    rows = []
    for sc in scenarios:
        before, t0 = llm.calls, time.time()
        try:
            run = run_scenario(tp, sc)
        except Exception as exc:
            log.exception("scenario %s failed", sc["id"])
            run = {"id": sc["id"], "text": sc["text"], "reached": f"error: {exc}"}
        run["latency_s"] = round(time.time() - t0, 1)
        run["llm_calls"] = llm.calls - before
        run["score"] = score(sc, run)
        rows.append(run)
        bad = [c for c, v in run["score"].items() if v is False]
        status = "ok" if not bad else "FAIL: " + ", ".join(bad)
        print(f"{sc['id']} {run['latency_s']:>5}s  {status}")
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / f"{date.today()}-plans.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    write_report(rows, ROOT / "PLANS.md")
    print("\n" + (ROOT / "PLANS.md").read_text())


if __name__ == "__main__":
    main()
