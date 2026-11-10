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

Rates are reported with 95% Wilson intervals. The judge is eval/judge.py: by default the v2
checklist jury (three model families, sampled verdicts, majority vote, cached), or the old
single-call judge with --judge v1. Its reliability is measured in eval/reliability.py.
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

from app.config import Settings
from app.db.graph import GraphStore
from app.rag.factory import build_llm_clients, build_self_rag
from app.rag.llm import LLM
from eval.judge import (  # noqa: F401
    JUDGE_VERSION,
    JuryJudge,
    VerdictCache,
    _derive,
    grounding,
    in_kb,
    judge_v1,
)
from eval.stats import fmt_rate
from ingest.osm import normalize

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
ENTITIES = ROOT.parent / "data" / "processed" / "entities.json"
LANGS = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish"}


# ---------- systems: each returns (answer, context_ids) ----------
def run_no_rag(q: str, ctx) -> tuple[str, list[str]]:
    ans = ctx["llm"].complete(
        ctx["settings"].judge_model,
        [{"role": "system", "content": "You are an Uttarakhand travel assistant."},
         {"role": "user", "content": q}], temperature=0.2)
    return ans, []


def run_baseline(q: str, ctx) -> tuple[str, list[str]]:
    from app.rag.hybrid import SYSTEM_PROMPT, HybridRAG  # loads a re-ranking model

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
# Every text field the answering model is shown (see app/rag/self_rag.format_entity). A place
# that appears only in an address, e.g. "Kasardevi Rd", is still in our data.
KB_TEXT_FIELDS = ("description", "semantic_text", "address", "hours", "price_text")


def kb_index(store=None) -> dict:
    """What counts as 'in our data': entity names plus the text of every field shown to the
    model (descriptions, addresses, hours, prices).

    Uses the local dataset if present, otherwise Neo4j (CI has no git-ignored data/processed/).
    """
    if ENTITIES.exists():
        rows = [(e["name"], " ".join(e.get(f) or "" for f in KB_TEXT_FIELDS))
                for e in json.loads(ENTITIES.read_text())]
    else:
        fields = ", ".join(f"e.{f} AS {f}" for f in KB_TEXT_FIELDS)
        with store.driver.session() as s:
            rows = [(r["n"], " ".join(r[f] or "" for f in KB_TEXT_FIELDS)) for r in s.run(
                f"MATCH (e:Entity) RETURN e.name AS n, {fields}")]
    names = [n for n in {normalize(n) for n, _ in rows if n} if n]
    return {"names": names, "text": " " + normalize(" ".join(d for _, d in rows)) + " "}


def pct(xs: list[bool]) -> str:
    return f"{100 * sum(xs) / len(xs):.0f}%" if xs else "n/a"


def _rate(xs: list[bool]) -> str:
    return fmt_rate(sum(xs), len(xs))


def summarize(rows: list[dict]) -> dict:
    """Headline rates (plain percentages, read by the CI gate) plus the same rates with
    95% intervals (`*_ci`) and per-language answer rates for the report."""
    ans = [r for r in rows if r["kind"] == "answerable"]
    una = [r for r in rows if r["kind"] == "unanswerable"]
    has_ctx = bool(ans) and ans[0]["has_context"]
    metrics = {
        "hit": [r["hit"] for r in ans] if has_ctx else None,
        "ungrounded": [bool(r["judge"]["ungrounded_places"]) for r in ans],
        "answers": [r["judge"]["answers_question"] for r in ans],
        "declines": [r["judge"]["declines"] for r in una],
        "invents": [r["judge"]["invents"] and not r["judge"]["declines"] for r in una],
    }
    out = {"n_answerable": len(ans), "n_unanswerable": len(una)}
    for key, xs in metrics.items():
        out[key] = pct(xs) if xs is not None else "n/a"
        out[f"{key}_ci"] = _rate(xs) if xs is not None else "n/a"
    for lang in LANGS:
        sub = [r["judge"]["answers_question"] for r in ans if r.get("lang", "en") == lang]
        out[f"answers_{lang}"] = _rate(sub) if sub else "n/a"
    # A verdict with missing jury votes is counted, never silently read as "no".
    out["judge_incomplete"] = sum(1 for r in rows if r["judge"].get("complete") is False)
    out["answer_errors"] = sum(1 for r in rows if r.get("answer", "").startswith("[error"))
    out["calls"] = f"{statistics.mean(r['llm_calls'] for r in rows):.1f}" if rows else "n/a"
    out["latency_s"] = f"{statistics.mean(r['latency_s'] for r in rows):.1f}" if rows else "n/a"
    return out


def write_report(results: dict[str, dict], path: Path, judge_note: str = "") -> None:
    cols = [("hit_ci", "hit@k (answerable)"),
            ("ungrounded_ci", "answers naming places not in data ↓"),
            ("answers_ci", "answers the question"), ("declines_ci", "declines (unanswerable)"),
            ("invents_ci", "invents specifics (unanswerable) ↓"), ("calls", "LLM calls/q"),
            ("latency_s", "latency s/q")]
    lines = [f"# Evaluation results ({date.today()})", "",
             "| system | " + " | ".join(c[1] for c in cols) + " |",
             "|---|" + "---|" * len(cols)]
    for name, summ in results.items():
        lines.append(f"| {name} | " + " | ".join(str(summ.get(c[0], "n/a")) for c in cols) + " |")
    lines += ["", "**Answers the question, by language** (answerable questions)", "",
              "| system | " + " | ".join(LANGS.values()) + " |",
              "|---|" + "---|" * len(LANGS)]
    for name, summ in results.items():
        lines.append(f"| {name} | " + " | ".join(summ.get(f"answers_{k}", "n/a")
                                                 for k in LANGS) + " |")
    first = next(iter(results.values()))
    lines += ["", f"Golden set: {first['n_answerable']} answerable + "
              f"{first['n_unanswerable']} unanswerable questions (`eval/golden.yaml`), in "
              "English, Hindi and Hinglish, including prompt-injection and false-premise "
              "questions. Each cell is a rate with its 95% Wilson interval. ↓ = lower is better.",
              "", judge_note or "Judge: see eval/judge.py.", "",
              "Data quality: " + "; ".join(
                  f"{name}: {s.get('answer_errors', 0)} answer errors, "
                  f"{s.get('judge_incomplete', 0)} incomplete judgements"
                  for name, s in results.items()) + ".", ""]
    path.write_text("\n".join(lines))


def v2_note(s: Settings) -> str:
    jury = [m.strip() for m in s.judge_jury.split(",") if m.strip()]
    return (f"Judge {JUDGE_VERSION}: yes/no checklist, jury of {len(jury)} model families "
            f"({', '.join(m.split('/')[-1] for m in jury)}), {s.judge_samples} sampled verdicts "
            f"each at temperature {s.judge_temperature}, majority vote, cached. Named places "
            "are checked in code: they must appear in the answer and in the knowledge base "
            "(names, descriptions, addresses, hours, prices). Reliability: eval/RELIABILITY.md.")


def rescore(s: Settings) -> None:
    """Re-apply the code half of the judge to today's saved results and rebuild the report.
    The LLM verdicts are kept as they are; only the knowledge-base checks run again."""
    store = None if ENTITIES.exists() else GraphStore(s.neo4j_uri, s.neo4j_user,
                                                      s.neo4j_password, s.neo4j_database)
    kb = kb_index(store)
    merged = {}
    for name in SYSTEMS:
        f = ROOT / "results" / f"{date.today()}-{name}.json"
        if not f.exists():
            continue
        rows = json.loads(f.read_text())
        changed = 0
        for r in rows:
            j = r["judge"]
            if j.get("version") != JUDGE_VERSION:
                continue
            places, ungrounded = grounding(j["named_places"], r["answer"], kb)
            changed += ungrounded != j["ungrounded_places"]
            j.update({"named_places": places, "ungrounded_places": ungrounded,
                      **_derive(j["items"], ungrounded)})
        f.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
        merged[name] = summarize(rows)
        print(f"{name}: {changed} answers re-scored")
    write_report(merged, ROOT / "RESULTS.md", v2_note(s))
    print("\n" + (ROOT / "RESULTS.md").read_text())


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", nargs="*", default=list(SYSTEMS))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--judge", choices=["v1", "v2"], default="v2")
    ap.add_argument("--no-cache", action="store_true", help="re-ask every juror")
    ap.add_argument("--rescore", action="store_true",
                    help="re-apply the code checks to today's saved results (no LLM calls)")
    args = ap.parse_args()

    s = Settings()
    if args.rescore:
        rescore(s)
        return
    store = GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database)
    chat, _ = build_llm_clients(s)
    ctx = {"settings": s, "store": store, "llm": LLM(chat, retries=6)}
    if "baseline" in args.systems:
        from app.rag.hybrid import HybridRAG

        ctx["hybrid"] = HybridRAG(s, store)
    if "self_rag" in args.systems:
        ctx["self_rag"] = build_self_rag(s, store)
        ctx["self_rag"].llm.retries = 6  # batch job: wait out rate limits instead of failing
    judge_llm = LLM(chat, retries=6)
    kb = kb_index(store)
    jury = [m.strip() for m in s.judge_jury.split(",") if m.strip()]
    if args.judge == "v2":
        cache = VerdictCache(None if args.no_cache else ROOT / "results" / "judge_cache.sqlite")
        jj = JuryJudge(judge_llm, jury, s.judge_samples, s.judge_temperature, cache)
        judge_note = v2_note(s)

        def judge(q, a):
            return jj(q, a, kb)
    else:
        judge_note = f"Judge v1: one call to {s.judge_model}, temperature 0."

        def judge(q, a):
            return judge_v1(judge_llm, s.judge_model, q, a, kb)

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
            j = judge(q["query"], answer)
            rows.append({
                "id": q["id"], "kind": q["kind"], "category": q["category"],
                "lang": q.get("lang", "en"),
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
    write_report(merged, ROOT / "RESULTS.md", judge_note)
    print(f"judge LLM calls: {judge_llm.calls}, tokens in/out: {judge_llm.prompt_tokens}/"
          f"{judge_llm.completion_tokens}")
    print("\n" + (ROOT / "RESULTS.md").read_text())
    store.close()


if __name__ == "__main__":
    main()
