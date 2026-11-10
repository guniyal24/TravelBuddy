from app.graph.critic import fallback_plan, validate_plan
from app.graph.trip_graph import TripPlanner


def ent(i, typ, dest, name=None, tier=None, price="", lat=None, lon=None):
    return {"id": i, "type": typ, "destination_id": dest, "name": name or i, "tier": tier,
            "price_text": price, "lat": lat, "lon": lon}


HW, RK = "destination_haridwar", "destination_rishikesh"
ENTS = {e["id"]: e for e in [
    ent("a_hw1", "Attraction", HW, "Har Ki Pauri", lat=29.95, lon=78.17),
    ent("a_hw2", "Attraction", HW, "Mansa Devi", lat=29.96, lon=78.18),
    ent("e_hw1", "Eatery", HW, "Mohan Puri"),
    ent("s_hw1", "Stay", HW, "Hotel Golden", tier="budget", price="₹500"),
    ent("a_rk1", "Attraction", RK, "Laxman Jhula", lat=30.12, lon=78.33),
    ent("a_rk2", "Activity", RK, "Yoga Class", lat=30.11, lon=78.32),
    ent("e_rk1", "Eatery", RK, "German Bakery"),
    ent("s_rk1", "Stay", RK, "Backpacker Hostel", tier="budget", price="₹400-600"),
]}


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def json(self, model, messages, default=None):
        self.prompts.append(messages[-1]["content"])
        return self.replies.pop(0)


class FakeRetriever:
    def search(self, query, top_k=12, filter=None, **kw):
        city = filter["city"]
        types = filter["type"]["$in"]
        dest = HW if city == "Haridwar" else RK
        return [{"id": e["id"], "score": 1, "name": e["name"], "type": e["type"], "city": city,
                 "text": ""} for e in ENTS.values()
                if e["destination_id"] == dest and e["type"] in types]


class FakeStore:
    def fetch_entities(self, ids):
        return {i: ENTS[i] for i in ids if i in ENTS}


REQ = {"origin": "Pune", "days": 3, "people": 2, "month": 11, "tier": "budget",
       "interests": ["temple"]}
GOOD = {"days": [
    {"day": 1, "destination": HW, "stops": ["a_hw1", "a_hw2"], "meals": ["e_hw1"], "stay": "s_hw1"},
    {"day": 2, "destination": RK, "stops": ["a_rk1"], "meals": ["e_rk1"], "stay": "s_rk1"},
    {"day": 3, "destination": RK, "stops": ["a_rk2"], "meals": [], "stay": None}]}


def make(replies):
    llm = FakeLLM(replies)
    return TripPlanner(llm, FakeRetriever(), FakeStore(), "small", "big"), llm


def test_full_happy_path_with_two_human_pauses_and_approval():
    tp, _ = make([REQ, GOOD])
    r = tp.start("t1", "3 days in November for 2 people from Pune, love temples")
    assert r["status"] == "waiting" and r["prompt"]["type"] == "choose"
    both = next(o["id"] for o in r["prompt"]["options"] if "+" in o["id"])
    r = tp.resume("t1", both)
    assert r["status"] == "waiting" and r["prompt"]["type"] == "approve"
    assert r["prompt"]["cost"]["total_inr"][0] > 0
    r = tp.resume("t1", {"action": "approve"})
    assert r["status"] == "done" and "Day 1 - Haridwar" in r["itinerary"]
    assert "Har Ki Pauri" in r["itinerary"] and "a_hw1" not in r["itinerary"]
    assert "Excludes travel" in r["itinerary"] and "destination_" not in r["itinerary"]


def test_asks_for_missing_details_then_continues():
    tp, _ = make([{"days": 3, "interests": []}, {"people": 2, "month": 11}])
    r = tp.start("t2", "3 days in Uttarakhand")
    assert r["prompt"]["type"] == "ask" and set(r["prompt"]["missing"]) == {"people", "month"}
    r = tp.resume("t2", "2 people in November")
    assert r["prompt"]["type"] == "choose"  # request now complete, merged with earlier answer


def test_critic_rejects_unknown_id_and_planner_retries_with_feedback():
    bad = {"days": [{"day": 1, "destination": HW, "stops": ["INVENTED"], "meals": [],
                     "stay": "s_hw1"},
                    *GOOD["days"][1:]]}
    tp, llm = make([REQ, bad, GOOD])
    r = tp.start("t3", "x")
    r = tp.resume("t3", "destination_haridwar+destination_rishikesh")
    assert r["prompt"]["type"] == "approve"
    assert "INVENTED" in llm.prompts[-1] and "Fix these problems" in llm.prompts[-1]
    assert "INVENTED" not in str(r["prompt"]["plan"])


def test_fallback_plan_after_repeated_failures_is_valid_and_flagged():
    bad = {"days": []}
    tp, _ = make([REQ, bad, bad, bad])
    tp.start("t4", "x")
    r = tp.resume("t4", "destination_haridwar+destination_rishikesh")
    assert r["prompt"]["type"] == "approve"
    assert any("automatic plan" in w for w in r["prompt"]["warnings"])
    assert len(r["prompt"]["plan"]["days"]) == 3


def test_edit_request_replans_then_cancel_ends():
    tp, llm = make([REQ, GOOD, GOOD])
    tp.start("t5", "x")
    tp.resume("t5", "destination_haridwar+destination_rishikesh")
    r = tp.resume("t5", {"action": "edit", "text": "less walking please"})
    assert r["prompt"]["type"] == "approve" and "less walking" in llm.prompts[-1]
    r = tp.resume("t5", {"action": "cancel"})
    assert r["status"] == "cancelled" and r["itinerary"] is None


def test_budget_warning_when_estimate_exceeds_budget():
    tp, _ = make([{**REQ, "budget_inr": 500}, GOOD])
    tp.start("t6", "x")
    r = tp.resume("t6", "destination_haridwar+destination_rishikesh")
    assert any("above your budget" in w for w in r["prompt"]["warnings"])


def test_critic_rules_directly():
    season = lambda place, month: {"status": "ok", "reasons": []}  # noqa: E731
    req = {"days": 2, "month": 11}
    plan = {"days": [{"day": 1, "destination": HW, "stops": ["a_hw1", "e_hw1", "a_hw1"],
                      "meals": ["a_hw2"], "stay": "s_rk1"},
                     {"day": 2, "destination": HW, "stops": [], "meals": [], "stay": None}]}
    errors, _ = validate_plan(plan, ENTS, req, season)
    text = " ".join(errors)
    assert "not allowed in stops" in text and "not allowed in meals" in text
    assert "already visited" in text and "is not in destination_haridwar" in text
    missing_stay = {"days": [{"day": 1, "destination": HW, "stops": [], "meals": [], "stay": None},
                             {"day": 2, "destination": HW, "stops": [], "meals": [], "stay": None}]}
    assert any("stay is required" in e for e in validate_plan(missing_stay, ENTS, req, season)[0])
    cands = {HW: {"stops": [ENTS["a_hw1"]], "meals": [ENTS["e_hw1"]], "stays": [ENTS["s_hw1"]]}}
    fp = fallback_plan(req, [HW], cands)
    assert validate_plan(fp, ENTS, req, season)[0] == []


def test_planner_prompt_uses_short_aliases_and_maps_back_to_real_ids():
    # model answers with aliases (A1/M1/S1...), which must be expanded to real ids
    aliased = {"days": [
        {"day": 1, "destination": HW, "stops": ["A1", "A2"], "meals": ["M1"], "stay": "S1"},
        {"day": 2, "destination": RK, "stops": ["A3"], "meals": ["M2"], "stay": "S2"},
        {"day": 3, "destination": RK, "stops": ["A4"], "meals": [], "stay": None}]}
    tp, llm = make([REQ, aliased])
    tp.start("t7", "x")
    r = tp.resume("t7", "destination_haridwar+destination_rishikesh")
    assert r["prompt"]["type"] == "approve"
    days = r["prompt"]["plan"]["days"]
    assert days[0]["stops"] == ["a_hw1", "a_hw2"] and days[0]["stay"] == "s_hw1"
    assert "a_hw1" not in llm.prompts[-1] and "A1 |" in llm.prompts[-1]  # prompt shows aliases only


def test_unknown_alias_is_reported_by_critic_not_silently_accepted():
    bad = {"days": [{"day": 1, "destination": HW, "stops": ["A99"], "meals": [], "stay": "S1"},
                    *GOOD["days"][1:]]}
    tp, llm = make([REQ, bad, GOOD])
    tp.start("t8", "x")
    tp.resume("t8", "destination_haridwar+destination_rishikesh")
    assert "A99" in llm.prompts[-1]
