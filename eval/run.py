"""Evaluate three systems on eval/golden.yaml:

  no_rag    LLM alone (what a generic chatbot does)           -> hallucination baseline
  baseline  prototype pipeline: vector search -> rerank -> graph -> answer
  self_rag  LangGraph Self-RAG (grade, rewrite, verify, abstain)

    python -m eval.run [--systems no_rag baseline self_rag] [--limit N]

Metrics (all printed + written to eval/RESULTS.md):
  hit@k            answerable: an expected entity was in the context the answer was built from
  ungrounded       answerable: share of answers naming a place/dish that is NOT in our data
  declines         unanswerable: share of answers that decline instead of inventing
  invents          unanswerable: share that give specific names/prices/times anyway
  answers          answerable: share judged to actually answer the question
  calls/latency    LLM calls and seconds per question

The judge is an LLM (the reasoning model, temperature 0), so absolute numbers are
indicative; the comparison between systems under the same judge is what matters.
"""
import argparse
import json
import logging
import statistics
import time
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import yaml
from dotenv import load_dotenv

from app.config import Settings
from app.db.graph import GraphStore
from app.rag.factory import build_llm_clients, build_self_rag
from app.rag.hybrid import SYSTEM_PROMPT, HybridRAG
from app.rag.llm import LLM
from ingest.osm import normalize

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
ENTITIES = ROOT.parent / "data" / "processed" / "entities.json"

JUDGE_SYSTEM = (
    "You evaluate a travel assistant's ANSWER to a QUESTION about Uttarakhand. Return JSON "
    'only: {"answers_question": bool, "declines": bool, "invents_specifics": bool, '
    '"named_places": [str]}. answers_question: the answer gives useful, on-topic content. '
    "declines: the answer says it lacks the information / cannot confirm. invents_specifics: "
    "the answer states specific names, prices, fares, timings or fees as fact. named_places: "
    "every specific hotel, restaurant, temple, ashram, attraction or dish named in the answer "
    "(NOT cities, rivers, states or generic words)."
)


# ---------- systems: each returns (answer, context_ids) ----------
def run_no_rag(q: str, ctx) -> tuple[str, list[str]]:
    ans = ctx["llm"].complete(
        ctx["settings"].judge_model,
        [{"role": "system", "content": "You are an Uttarakhand travel assistant."},
         {"role": "user", "content": q}], temperature=0.2)
    return ans, []


def run_baseline(q: str, ctx) -> tuple[str, list[str]]:
    hybrid: HybridRAG = ctx["hybrid"]
    matches = hybrid.retrieve(q)
    ids = [m["id"] for m in matches]
    context = HybridRAG._build_context(matches, ctx["store"].fetch_graph_context(ids))
    ans = ctx["llm"].complete(
        ctx["settings"].judge_model,
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {q}"}], temperature=0.2)
    return ans, ids


def run_self_rag(q: str, ctx) -> tuple[str, list[str]]:
    state = ctx["self_rag"].run(q)
    return state["answer"], [d["id"] for d in state.get("relevant", [])]


SYSTEMS = {"no_rag": run_no_rag, "baseline": run_baseline, "self_rag": run_self_rag}


# ---------- judging ----------
def kb_index(store=None) -> dict:
    """What counts as 'in our data': entity names plus all description text.

    Uses the local dataset if present, otherwise Neo4j (CI has no git-ignored data/processed/).
    A place mentioned only inside a description (e.g. 'Neel Parvat') is still grounded.
    """
    if ENTITIES.exists():
        rows = [(e["name"], (e.get("description") or "") + " " + (e.get("semantic_text") or ""))
                for e in json.loads(ENTITIES.read_text())]
    else:
        with store.driver.session() as s:
            rows = [(r["n"], (r["d"] or "") + " " + (r["t"] or "")) for r in s.run(
                "MATCH (e:Entity) RETURN e.name AS n, e.description AS d, e.semantic_text AS t")]
    names = [n for n in {normalize(n) for n, _ in rows if n} if n]
    return {"names": names, "text": " " + normalize(" ".join(d for _, d in rows)) + " "}


def in_kb(place: str, kb: dict) -> bool:
    p = normalize(place)
    if not p:
        return True  # nothing meaningful to check
    if f" {p} " in kb["text"]:
        return True  # mentioned in a description
    for n in kb["names"]:
        if p == n or SequenceMatcher(None, p, n).ratio() >= 0.85:
            return True
        if min(len(p), len(n)) >= 5 and (p in n or n in p):
            return True
    return False


def judge(judge_llm: LLM, model: str, question: str, answer: str, kb: dict) -> dict:
    res = judge_llm.json(
        model,
        [{"role": "system", "content": JUDGE_SYSTEM},
         {"role": "user", "content": f"QUESTION: {question}\n\nANSWER: {answer}"}],
        default={})
    places = [p for p in (res.get("named_places") or []) if isinstance(p, str)]
    ungrounded = [p for p in places if not in_kb(p, kb)]
    return {"answers_question": bool(res.get("answers_question")),
            "declines": bool(res.get("declines")),
            "invents": bool(res.get("invents_specifics")),
            "named_places": places, "ungrounded_places": ungrounded}


def pct(xs: list[bool]) -> str:
    return f"{100 * sum(xs) / len(xs):.0f}%" if xs else "n/a"


def summarize(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["kind"] == "answerable"]
    una = [r for r in rows if r["kind"] == "unanswerable"]
    return {
        "n_answerable": len(ans), "n_unanswerable": len(una),
        "hit": pct([r["hit"] for r in ans]) if ans and ans[0]["has_context"] else "n/a",
        "ungrounded": pct([bool(r["judge"]["ungrounded_places"]) for r in ans]),
        "answers": pct([r["judge"]["answers_question"] for r in ans]),
        "declines": pct([r["judge"]["declines"] for r in una]),
        "invents": pct([r["judge"]["invents"] and not r["judge"]["declines"] for r in una]),
        "calls": f"{statistics.mean(r['llm_calls'] for r in rows):.1f}",
        "latency_s": f"{statistics.mean(r['latency_s'] for r in rows):.1f}",
    }


def write_report(results: dict[str, dict], path: Path) -> None:
    cols = [("hit", "hit@k (answerable)"), ("ungrounded", "answers naming places not in data"),
            ("answers", "answers the question"), ("declines", "declines (unanswerable)"),
            ("invents", "invents specifics (unanswerable)"), ("calls", "LLM calls/q"),
            ("latency_s", "latency s/q")]
    lines = [f"# Evaluation results ({date.today()})", "",
             "| system | " + " | ".join(c[1] for c in cols) + " |",
             "|---|" + "---|" * len(cols)]
    for name, summ in results.items():
        lines.append(f"| {name} | " + " | ".join(str(summ[c[0]]) for c in cols) + " |")
    first = next(iter(results.values()))
    lines += ["", f"Golden set: {first['n_answerable']} answerable + "
              f"{first['n_unanswerable']} unanswerable questions (`eval/golden.yaml`). "
              "Lower is better for 'names places not in data' and 'invents specifics'; "
              "higher is better elsewhere. Judge: LLM, temperature 0.", ""]
    path.write_text("\n".join(lines))


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", nargs="*", default=list(SYSTEMS))
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    s = Settings()
    store = GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database)
    chat, _ = build_llm_clients(s)
    ctx = {"settings": s, "store": store, "llm": LLM(chat)}
    if "baseline" in args.systems:
        ctx["hybrid"] = HybridRAG(s, store)
    if "self_rag" in args.systems:
        ctx["self_rag"] = build_self_rag(s, store)
    judge_llm = LLM(chat)
    kb = kb_index(store)

    questions = yaml.safe_load((ROOT / "golden.yaml").read_text())["questions"]
    if args.limit:
        questions = questions[: args.limit]

    results, raw = {}, {}
    for name in args.systems:
        rows = []
        for q in questions:
            gen_llm = ctx["self_rag"].llm if name == "self_rag" else ctx["llm"]
            before, t0 = gen_llm.calls, time.time()
            try:
                answer, ids = SYSTEMS[name](q["query"], ctx)
            except Exception as exc:  # keep going; record the failure
                log.exception("%s failed on %s", name, q["id"])
                answer, ids = f"[error: {exc}]", []
            latency = time.time() - t0
            calls = gen_llm.calls - before
            j = judge(judge_llm, s.judge_model, q["query"], answer, kb)
            rows.append({
                "id": q["id"], "kind": q["kind"], "category": q["category"],
                "query": q["query"], "answer": answer, "context_ids": ids,
                "has_context": name != "no_rag",
                "hit": bool(set(q.get("expected_any", [])) & set(ids)),
                "judge": j, "llm_calls": calls, "latency_s": latency,
            })
            print(f"[{name}] {q['id']} hit={rows[-1]['hit']} declines={j['declines']} "
                  f"ungrounded={len(j['ungrounded_places'])}")
        results[name] = summarize(rows)
        raw[name] = rows

    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    for name, rows in raw.items():  # one file per system so parallel runs do not clash
        (out_dir / f"{date.today()}-{name}.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False))
    # Build the report from every system's latest file, in a fixed order.
    merged = {}
    for name in SYSTEMS:
        f = out_dir / f"{date.today()}-{name}.json"
        if f.exists():
            merged[name] = summarize(json.loads(f.read_text()))
    write_report(merged, ROOT / "RESULTS.md")
    print("\n" + (ROOT / "RESULTS.md").read_text())
    store.close()


if __name__ == "__main__":
    main()
