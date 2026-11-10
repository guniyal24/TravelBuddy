"""Live agent trace: the planner streams real steps, and the result matches a plain run."""
from test_trip_graph import GOOD, REQ, make

from app.graph.trace import Tracer

BOTH = "destination_haridwar+destination_rishikesh"


def _run_both(script):
    """Run the same script with and without streaming; return (plain, streamed, events)."""
    events = []
    plain_tp, _ = make(list(script))
    live_tp, _ = make(list(script))
    plain = [plain_tp.start("p", "x"), plain_tp.resume("p", BOTH),
             plain_tp.resume("p", {"action": "approve"})]
    live = [live_tp.start("l", "x", on_event=events.append),
            live_tp.resume("l", BOTH, on_event=events.append),
            live_tp.resume("l", {"action": "approve"}, on_event=events.append)]
    return plain, live, events


def test_streamed_run_gives_the_same_results_as_a_plain_run():
    plain, live, _ = _run_both([REQ, GOOD])
    for a, b in zip(plain, live, strict=True):
        assert a["status"] == b["status"]
        assert a.get("prompt", {}).get("type") == b.get("prompt", {}).get("type")
        assert a.get("itinerary") == b.get("itinerary")
    assert live[-1]["state"]["structured"]["plan"] == plain[-1]["state"]["structured"]["plan"]


def test_events_describe_each_agent_from_real_state():
    _, _, events = _run_both([REQ, GOOD])
    ends = {e["node"]: e for e in events if e["phase"] == "end"}
    assert ends["extract"]["message"].startswith("Understood: 3 days · 2 people · November")
    assert ends["research"]["message"].endswith("stays in 2 towns")
    assert any(d.startswith("Transport: Haridwar to Rishikesh, ")
               for d in ends["specialists"]["details"])
    assert ends["critic"]["tone"] == "ok"
    assert ends["cost"]["message"].startswith("Estimated ₹")
    assert ends["choose"]["message"] == "You picked Haridwar + Rishikesh"
    assert ends["approve"]["message"] == "You approved the plan"
    assert ends["finalize"]["message"].startswith("Trip saved")
    waits = [e["node"] for e in events if e["phase"] == "wait"]
    assert waits == ["choose", "approve"]
    # every finished step has a duration; human steps never show a "start"
    assert all("ms" in e for e in events if e["phase"] != "start")
    assert not any(e["phase"] == "start" and e["node"] in ("choose", "approve") for e in events)


def test_critic_rejection_is_visible_in_the_trace():
    bad = {"days": [{"day": 1, "destination": "destination_haridwar", "stops": ["INVENTED"],
                     "meals": [], "stay": "s_hw1"}, *GOOD["days"][1:]]}
    events = []
    tp, _ = make([REQ, bad, GOOD])
    tp.start("t", "x", on_event=events.append)
    tp.resume("t", BOTH, on_event=events.append)
    critic = [e for e in events if e["node"] == "critic" and e["phase"] == "end"]
    assert critic[0]["tone"] == "warn" and "Rejected the draft" in critic[0]["message"]
    assert any("INVENTED" in d for d in critic[0]["details"])
    assert critic[1]["tone"] == "ok"
    plans = [e["message"] for e in events if e["node"] == "plan" and e["phase"] == "start"]
    assert plans == ["Drafting a day-by-day plan",
                     "Re-drafting the plan (attempt 2) to fix the Critic's notes"]


def test_a_broken_listener_does_not_break_planning():
    def boom(_):
        raise RuntimeError("UI went away")

    tp, _ = make([REQ, GOOD])
    r = tp.start("t", "x", on_event=boom)
    assert r["status"] == "waiting" and r["prompt"]["type"] == "choose"


def test_tracer_ignores_unknown_nodes_and_reports_failures():
    out = []
    t = Tracer(out.append)
    t.feed({"id": "1", "name": "__start__", "input": {}})
    t.feed({"id": "2", "name": "research", "input": {}})
    t.feed({"id": "2", "name": "research", "error": "boom", "result": None, "interrupts": []})
    assert [e["phase"] for e in out] == ["start", "end"]
    assert out[1]["tone"] == "warn" and out[1]["message"] == "This step failed"
