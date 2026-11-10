"""Concierge evaluation: run the hotel agent on real hotels in every offered town.

    python -m eval.concierge [--per-town 3]

Reports (eval/CONCIERGE.md):
  match rate         share of our hotels Google could match (name and location checks)
  claim survival     share of the Review Analyst's pros/cons whose quote is found word for word
                     in the cited review; the rest are dropped before a traveller sees them
  sentiment check    Spearman correlation between the analyst's mean aspect score and
                     Google's star rating, across hotels. Positive = the analyst reads the
                     reviews the same way reviewers rated the hotel.
Costs one Google Places call per hotel (results are not stored; see mcp_server/places.py).
"""
import argparse
import json
import statistics
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from app.graph.trip_graph import DESTINATIONS, NOT_READY
from eval.stats import fmt_rate

ROOT = Path(__file__).resolve().parent


def spearman(xs: list[float], ys: list[float]) -> float | None:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-town", type=int, default=3)
    args = ap.parse_args()

    from app.config import Settings
    from app.db.graph import GraphStore
    from app.graph.concierge import HotelAgent
    from app.rag.factory import build_llm_clients
    from app.rag.llm import LLM
    from mcp_server.client import LocalTools

    s = Settings()
    store = GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database)
    chat, _ = build_llm_clients(s)
    agent = HotelAgent(LocalTools(), LLM(chat, retries=6), s.router_model)
    with store.driver.session() as sess:
        stays = [dict(r["n"]) for r in sess.run(
            "MATCH (n:Entity) WHERE n.type = 'Stay' RETURN n ORDER BY n.id")]
    towns = []
    for dest, meta in DESTINATIONS.items():
        if dest in NOT_READY:
            continue
        pool = [x for x in stays if x.get("destination_id") == dest][: args.per_town]
        if not pool:
            continue
        town = {"name": meta["name"], "lat": meta["lat"], "lon": meta["lon"]}
        found = agent.research(dest, town, pool, {"tier": "mid", "days": 3, "people": 2}, None)
        towns.append(found)
        print(f"{meta['name']}: {len(found['options'])} hotels, {found['reviews_read']} reviews, "
              f"{found['verified']}/{found['claims']} claims kept")

    opts = [o for t in towns for o in t["options"]]
    matched = [o for o in opts if o["google"].get("found")]
    claims = sum(t["claims"] for t in towns)
    kept = sum(t["verified"] for t in towns)
    pairs = [(statistics.mean(o["analysis"]["aspects"].values()), o["google"]["rating"])
             for o in matched if o["analysis"]["aspects"] and o["google"].get("rating")]
    rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
    lines = [f"# Concierge evaluation ({date.today()})", "",
             f"The hotel agent run on the first {args.per_town} hotels of each offered town "
             f"({len(opts)} hotels, {len(towns)} towns), with live Google reviews.", "",
             "| measure | result |", "|---|---|",
             "| hotels Google could match (name + location) | "
             f"{fmt_rate(len(matched), len(opts))} |",
             f"| reviews read | {sum(t['reviews_read'] for t in towns)} |",
             "| analyst claims whose quote was found in the cited review | "
             f"{fmt_rate(kept, claims)} |",
             f"| Spearman: analyst aspect score vs Google star rating | "
             f"{f'{rho:.2f} over {len(pairs)} hotels' if rho is not None else 'n/a'} |", "",
             "Claims that fail the quote check are dropped before a traveller sees them, so the "
             "survival rate measures how often the analyst paraphrases or invents; it is not an "
             "error rate of what is shown. Ranking is computed in code (rating shrunk toward "
             f"{4.0} by review count, tier and budget fit), not by the LLM.", ""]
    (ROOT / "CONCIERGE.md").write_text("\n".join(lines))
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    # Google content is not stored: keep only the numbers.
    (out / f"{date.today()}-concierge.json").write_text(json.dumps(
        [{"town": t["town"], "hotels": len(t["options"]), "reviews_read": t["reviews_read"],
          "claims": t["claims"], "verified": t["verified"]} for t in towns], indent=2))
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
