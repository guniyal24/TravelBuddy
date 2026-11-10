"""Terminal demo of the trip planner with human-in-the-loop prompts.

    python -m app.graph.cli "3 days in November for 2 people, love temples and food"
    python -m app.graph.cli --auto "..."     # picks option 1 and approves (smoke test)
"""
import argparse
import json
import uuid

from dotenv import load_dotenv

from app.config import Settings
from app.db.graph import GraphStore
from app.rag.factory import build_trip_planner


def ask_human(prompt: dict, auto: bool):
    kind = prompt["type"]
    print(f"\n[{kind.upper()}] {prompt['message']}")
    if kind == "ask":
        return "2 people" if auto else input("> ")
    if kind == "choose":
        for i, o in enumerate(prompt["options"], 1):
            print(f"  {i}. {o['label']}" + (f"  ({'; '.join(o['reasons'])})" if o["reasons"] else ""))
        if auto:
            return prompt["options"][0]["id"]
        n = int(input("Pick a number > ") or 1)
        return prompt["options"][n - 1]["id"]
    # approve
    cost = prompt["cost"]
    print(json.dumps(prompt["plan"], indent=1)[:1500])
    print(f"Cost: Rs {cost['total_inr'][0]:,} - Rs {cost['total_inr'][1]:,}")
    for w in prompt["warnings"]:
        print("  !", w)
    if auto:
        return {"action": "approve"}
    text = input("Type 'ok' to approve, 'cancel', or what to change > ").strip()
    if text.lower() in ("ok", "approve", "yes"):
        return {"action": "approve"}
    return {"action": "cancel"} if text.lower() == "cancel" else {"action": "edit", "text": text}


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--auto", action="store_true")
    args = ap.parse_args()
    s = Settings()
    store = GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database)
    planner = build_trip_planner(s, store)
    tid = str(uuid.uuid4())
    result = planner.start(tid, args.text)
    while result["status"] == "waiting":
        result = planner.resume(tid, ask_human(result["prompt"], args.auto))
    print("\n" + (result["itinerary"] or f"Finished: {result['status']}"))
    store.close()


if __name__ == "__main__":
    main()
