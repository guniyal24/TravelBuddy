from datetime import date

import pytest
from test_trip_graph import ENTS, GOOD, HW, REQ, RK, FakeLLM, FakeRetriever, FakeStore

from app.export.ics import build_ics
from app.export.share import build_pdf, build_share_text
from app.graph.agents import FoodAgent, SafetyAgent, StayAgent
from app.graph.schedule import build_timeline
from app.graph.trip_graph import TripPlanner, detect_language
from app.trips.store import TripStore, clean_profile
from mcp_server.client import LocalTools

BOTH = "destination_haridwar+destination_rishikesh"


class LangLLM(FakeLLM):
    """FakeLLM plus `complete`, used for translation."""
    def json(self, model, messages, default=None, max_tokens=600):
        return super().json(model, messages, default)

    def complete(self, model, messages, temperature=0.0, max_tokens=None):
        self.prompts.append("TRANSLATE:" + messages[-1]["content"][:40])
        return "अनुवाद: " + messages[-1]["content"]


def make(replies, cls=LangLLM):
    llm = cls(replies)
    return TripPlanner(llm, FakeRetriever(), FakeStore(), "small", "big"), llm


def approved(tp, tid="p1"):
    tp.start(tid, "x")
    tp.resume(tid, BOTH)
    return tp.resume(tid, {"action": "approve"})


# ---------- store ----------
def test_profile_is_validated_and_learning_never_overrides_explicit_choices():
    s = TripStore()
    assert clean_profile({"tier": "gold", "diet": "veg", "interests": [" Yoga ", ""],
                          "language": "xx", "evil": 1}) == {"diet": "veg", "interests": ["yoga"]}
    s.save_profile("a@b.com", {"tier": "premium"})
    learned = s.learn("a@b.com", {"tier": "budget", "origin": "Pune",
                                  "interests": ["temple", "Yoga"], "vulnerable_travellers": True})
    assert learned["tier"] == "premium"  # explicit value wins
    assert learned["origin"] == "Pune" and learned["interests"] == ["temple", "yoga"]
    assert learned["vulnerable_travellers"] is True
    assert s.get_profile("nobody@x.com") == {}


def test_trips_are_saved_listed_per_owner_and_checklist_state_persists():
    s = TripStore()
    trip = {"request": {"days": 2}, "plan": {"days": [{"destination": HW}, {"destination": RK}]},
            "checklist": [{"id": "todo-0", "label": "x", "done": False},
                          {"id": "buses-0", "label": "y", "done": False}]}
    s.save_trip("t1", "a@b.com", trip)
    assert s.list_trips("b@b.com") == []
    assert s.list_trips("a@b.com")[0]["title"] == "2 days: Haridwar, Rishikesh"
    assert s.set_check("t1", "todo-0", True) is True
    got = s.get_trip("t1")
    assert [i["done"] for i in got["checklist"]] == [True, False]
    assert s.set_check("t1", "nope", True) is False and s.set_check("zz", "todo-0", True) is False
    s.set_check("t1", "todo-0", False)
    assert not s.get_trip("t1")["checklist"][0]["done"]


# ---------- agents ----------
def test_stay_agent_ranks_by_budget_and_tier():
    stays = [{"id": "dear", "tier": "mid", "price_text": "₹9000"},
             {"id": "cheap", "tier": "budget", "price_text": "₹800"},
             {"id": "unpriced", "tier": "budget", "price_text": ""}]
    ranked, note = StayAgent.rank({"tier": "budget", "budget_inr": 10000, "days": 3,
                                   "people": 2}, stays)
    assert [s["id"] for s in ranked] == ["cheap", "unpriced", "dear"] and "ranked lower" in note


def test_food_agent_applies_diet_and_never_returns_nothing():
    meals = [{"name": "Chicken Corner", "description": "chicken curry"},
             {"name": "Sattvik Bhojanalay", "description": "pure veg thali"},
             {"name": "Cafe", "description": "coffee"}]
    kept, note = FoodAgent.filter({}, meals, "veg")
    assert [m["name"] for m in kept] == ["Sattvik Bhojanalay", "Cafe"] and "left out" in note
    assert FoodAgent.filter({}, meals, "")[0] == meals
    only_meat = [meals[0]]
    kept, note = FoodAgent.filter({}, only_meat, "veg")
    assert kept == only_meat and "confirm the menu" in note


def test_safety_agent_flags_altitude_jump_health_and_permits():
    plan = {"days": [
        {"day": 1, "destination": "destination_rishikesh", "stay": "r"},
        {"day": 2, "destination": "destination_badrinath", "stay": "b"},
        {"day": 3, "destination": "destination_badrinath", "stay": None}]}
    ents = {"r": {"name": "Rishi Stay", "elevation_m": 340}, "b": {"name": "Badri Stay"}}
    res = SafetyAgent(LocalTools()).review(
        plan, ents, {"days": 3, "month": 6, "vulnerable_travellers": True})
    text = " ".join(res["warnings"])
    assert "Altitude, day 2" in text and "Health:" in text and "registration is mandatory" in text
    calm = SafetyAgent(LocalTools()).review(
        {"days": [{"day": 1, "destination": HW, "stay": None}]}, {}, {"days": 1, "month": 11})
    assert calm["warnings"] == []


# ---------- timeline ----------
def test_timeline_orders_a_day_and_adds_a_transfer_with_road_info():
    tl = build_timeline(GOOD, ENTS, lambda a, b: {
        "found": True, "distance_km": 25, "hours": [0.75, 1.25], "note": ""})
    day1, day2 = tl["days"][0]["items"], tl["days"][1]["items"]
    times = [i["time"] for i in day1]
    assert times == sorted(times) and day1[0]["time"] == "09:00"
    assert [i["kind"] for i in day1].count("stop") == 2
    assert day1[-1]["kind"] == "stay"
    assert day2[0]["kind"] == "transfer" and "25 km" in day2[0]["note"]
    assert any(i["kind"] == "meal" and i["time"] >= "13:00" for i in day1)
    assert tl["points"] and all(p["lat"] and p["lon"] for p in tl["points"])


# ---------- exports ----------
def _trip():
    tl = build_timeline(GOOD, ENTS)
    return {"trip_id": "abc", "title": "3 days: Haridwar, Rishikesh", "timeline": tl,
            "request": {"days": 3, "people": 2}, "plan": GOOD, "entities": ENTS,
            "cost": {"total_inr": [9000, 12000], "items": [
                {"label": "Food", "low": 1, "high": 2, "source": "assumption"}]},
            "warnings": ["Day 2: ₹ check"]}


def test_ics_is_valid_folded_and_dated():
    ics = build_ics(_trip(), date(2026, 11, 20))
    assert ics.startswith("BEGIN:VCALENDAR") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == ics.count("END:VEVENT") > 3
    assert "DTSTART;TZID=Asia/Kolkata:20261120T090000" in ics
    assert "DTSTART;TZID=Asia/Kolkata:20261121T" in ics and "BEGIN:VTIMEZONE" in ics
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))


def test_share_text_and_pdf():
    txt = build_share_text(_trip())
    assert "Day 1 Haridwar: Har Ki Pauri, Mansa Devi" in txt and "Rs.9,000 to Rs.12,000" in txt
    pdf = build_pdf(_trip())
    assert pdf[:4] == b"%PDF" and len(pdf) > 800


# ---------- planner: end to end ----------
def test_approved_trip_has_structured_output_timeline_checklist_and_safety():
    tp, _ = make([REQ, GOOD])
    tp.start("s1", "x")
    r = tp.resume("s1", BOTH)
    assert r["prompt"]["timeline"]["days"][0]["items"]  # review step shows the timeline too
    r = tp.resume("s1", {"action": "approve"})
    st = r["state"]["structured"]
    assert set(st["entities"]) <= set(ENTS) and "a_hw1" in st["entities"]
    ids = [c["id"] for c in st["checklist"]]
    assert len(ids) == len(set(ids)) and any(i.startswith("todo-") for i in ids)
    assert st["timeline"]["points"] and "safety" in st and st["itinerary"] == st["itinerary_en"]


def test_profile_fills_defaults_but_the_message_wins():
    profile = {"tier": "premium", "diet": "veg", "interests": ["yoga"], "language": "en"}
    tp, _ = make([{"days": 3, "people": 2, "month": 11, "interests": []}])
    r = tp.start("pf1", "3 days 2 people november", profile=profile)
    req = tp.graph.get_state(tp._cfg("pf1")).values["request"]
    assert r["status"] == "waiting" and req["tier"] == "premium" and req["diet"] == "veg"
    assert req["interests"] == ["yoga"]
    tp2, _ = make([{"days": 3, "people": 2, "month": 11, "tier": "budget"}])
    tp2.start("pf2", "budget please", profile=profile)
    assert tp2.graph.get_state(tp2._cfg("pf2")).values["request"]["tier"] == "budget"


def test_hindi_request_gets_translated_prompts_and_itinerary_but_keeps_links_and_english_copy():
    tp, llm = make([{**REQ, "language": "hi"}, GOOD])
    r = tp.start("h1", "मुझे हरिद्वार जाना है")
    assert r["prompt"]["message"].startswith("अनुवाद:")  # choose prompt translated
    r = tp.resume("h1", BOTH)
    assert r["prompt"]["preview"].startswith("अनुवाद:") and r["prompt"]["message"].startswith("अनुवाद:")
    r = tp.resume("h1", {"action": "approve"})
    st = r["state"]["structured"]
    assert st["itinerary"].startswith("अनुवाद:") and st["itinerary_en"].startswith("# Your Uttarakhand")


def test_language_comes_from_the_text_not_the_llm():
    # the LLM once labelled plain English as Hinglish; code decides now
    tp, llm = make([{**REQ, "language": "hinglish"}, GOOD])
    r = tp.start("l1", "Kausani and Almora, 3 days from next Friday, vegetarian")
    assert r["prompt"]["message"] == "Which circuit would you like?"
    assert not [p for p in llm.prompts if p.startswith("TRANSLATE:")]


@pytest.mark.parametrize("text,lang", [
    ("Kausani and Almora, 3 days from next Friday for 2 people", "en"),
    ("mujhe 3 din ke liye Rishikesh jana hai", "hinglish"),
    ("Nainital ka trip chahiye family ke saath", "hinglish"),
    ("मुझे हरिद्वार जाना है", "hi"),
    ("2", None), ("veg", None),  # too short to tell: keeps the trip's language
    ("Dehradun se Mussoorie, 2 days, budget hotel", "en"),
])
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_translation_failure_falls_back_to_english():
    class Broken(LangLLM):
        def complete(self, *a, **k):
            raise RuntimeError("down")
    tp, _ = make([{**REQ, "language": "hinglish"}, GOOD], cls=Broken)
    r = tp.start("h2", "mujhe 3 din ke liye Haridwar jana hai")
    assert r["prompt"]["message"] == "Which circuit would you like?"


# ---------- mid-trip re-planning ----------
def test_replan_keeps_earlier_days_and_goes_back_for_approval():
    new_tail = {"days": [  # model also (wrongly) rewrites day 1; the lock must restore it
        {"day": 1, "destination": HW, "stops": [], "meals": [], "stay": "s_hw1"},
        {"day": 2, "destination": RK, "stops": ["a_rk2"], "meals": ["e_rk1"], "stay": "s_rk1"},
        {"day": 3, "destination": RK, "stops": ["a_rk1"], "meals": [], "stay": None}]}
    tp, llm = make([REQ, GOOD, new_tail])
    approved(tp, "r1")
    r = tp.replan("r1", 2, "heavy rain, avoid outdoor spots")
    assert r["status"] == "waiting" and r["prompt"]["type"] == "approve"
    days = r["prompt"]["plan"]["days"]
    assert days[0] == GOOD["days"][0]  # day 1 untouched
    assert days[1]["stops"] == ["a_rk2"] and "heavy rain" in llm.prompts[-1]
    assert "Days 1 to 1 are already done" in llm.prompts[-1]
    done = tp.resume("r1", {"action": "approve"})
    assert done["status"] == "done" and done["state"]["structured"]["plan"]["days"][1]["stops"] == ["a_rk2"]


def test_replan_rejects_unapproved_trips_and_bad_days():
    tp, _ = make([REQ, GOOD])
    tp.start("r2", "x")
    tp.resume("r2", BOTH)  # still waiting at approval
    with pytest.raises(ValueError, match="approved"):
        tp.replan("r2", 2, "x")
    tp.resume("r2", {"action": "approve"})
    with pytest.raises(ValueError, match="between 1 and 3"):
        tp.replan("r2", 4, "x")
    with pytest.raises(ValueError, match="approved"):
        tp.replan("never-existed", 1, "x")


def test_translation_work_is_not_repeated_when_the_graph_resumes():
    tp, llm = make([{**REQ, "language": "hi"}, GOOD])
    tp.start("n1", "मुझे हरिद्वार जाना है")
    tp.resume("n1", BOTH)
    tp.resume("n1", {"action": "approve"})
    # choose message, review text, approve message, booking links: each piece exactly once
    # (long texts are split into sections translated in parallel, so count pieces, not calls)
    pieces = [p for p in llm.prompts if p.startswith("TRANSLATE:")]
    assert len(pieces) >= 4 and len(pieces) == len(set(pieces))


def test_learning_remembers_diet_and_language_but_not_over_explicit_values():
    s = TripStore()
    s.save_profile("a@b.com", {"language": "en"})
    learned = s.learn("a@b.com", {"diet": "veg", "language": "hi", "pace": "relaxed"})
    assert learned["diet"] == "veg" and learned["pace"] == "relaxed" and learned["language"] == "en"
