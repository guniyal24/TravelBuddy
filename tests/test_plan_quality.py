"""Plan-quality fixes: meals/stops stay in the day's town, the veg filter catches bars, and
towns the traveller names steer the circuit."""
from test_trip_graph import ENTS, GOOD, HW, RK, make

from app.graph.agents import FoodAgent
from app.graph.critic import validate_plan
from app.graph.trip_graph import named_places

SEASON = lambda place, month: {"status": "ok", "reasons": []}  # noqa: E731
REQ3 = {"days": 3, "month": 11}


def _with_day(n, **changes):
    days = [dict(d) for d in GOOD["days"]]
    days[n - 1].update(changes)
    return {"days": days}


# ---------- Critic: everything on a day belongs to that day's town ----------
def test_meal_from_another_town_is_rejected():
    errors, _ = validate_plan(_with_day(2, meals=["e_hw1"]), ENTS, REQ3, SEASON)
    assert errors == ["Day 2: e_hw1 (Mohan Puri) is in Haridwar, not Rishikesh; use only that "
                      "day's destination."]


def test_stop_from_another_town_is_rejected():
    errors, _ = validate_plan(_with_day(3, stops=["a_hw2"]), ENTS, REQ3, SEASON)
    assert len(errors) == 1 and "a_hw2 (Mansa Devi) is in Haridwar, not Rishikesh" in errors[0]


def test_a_day_without_meals_is_fine_and_unknown_town_is_not_guessed():
    assert validate_plan(_with_day(2, meals=[]), ENTS, REQ3, SEASON)[0] == []
    ents = {**ENTS, "e_x": {"id": "e_x", "type": "Eatery", "name": "No Town Cafe"}}
    assert validate_plan(_with_day(2, meals=["e_x"]), ents, REQ3, SEASON)[0] == []


def test_planner_retries_when_it_borrows_a_meal_from_another_town():
    borrowed = _with_day(3, meals=["e_hw1"])
    tp, llm = make([{"days": 3, "people": 2, "month": 11, "interests": []}, borrowed, GOOD])
    tp.start("q", "x")
    r = tp.resume("q", f"{HW}+{RK}")
    assert r["prompt"]["type"] == "approve"
    assert "is in Haridwar, not Rishikesh" in llm.prompts[-1]
    assert r["prompt"]["plan"]["days"][2]["meals"] == []


# ---------- Food agent ----------
def test_veg_filter_drops_bars_and_meat_by_whole_word():
    meals = [{"name": "Courtyard Bar", "description": "drinks and snacks"},
             {"name": "Barista Coffee", "description": "coffee and sandwiches"},
             {"name": "Fishtail Cafe", "description": "views of the lake"},
             {"name": "Tibetan market", "description": "momos filled with meat"},
             {"name": "Sattvik", "description": "pure veg thali"}]
    kept, note = FoodAgent.filter({}, meals, "veg")
    assert [m["name"] for m in kept] == ["Sattvik", "Barista Coffee", "Fishtail Cafe"]
    assert note.startswith("2 eatery listings mentioning meat, fish or a bar were left out")


def test_town_with_no_eateries_gets_an_honest_note():
    for diet in ("veg", ""):
        kept, note = FoodAgent.filter({}, [], diet)
        assert kept == [] and "No eateries are listed for this town" in note


# ---------- Named towns ----------
def test_named_places_reads_english_hinglish_and_hindi_in_order():
    assert named_places("Nainital aur Almora, 4 din") == ["destination_nainital",
                                                          "destination_almora"]
    assert named_places("मसूरी और देहरादून घूमना है") == ["destination_mussoorie",
                                                         "destination_dehradun"]
    assert named_places("safari in Corbett then Naini Tal") == ["destination_jim_corbett",
                                                               "destination_nainital"]
    assert named_places("a quiet hill trip with good food") == []
    assert named_places("Almorah-style sweets") == []  # whole words only


def _choose(user_text, extracted):
    tp, _ = make([{"people": 2, "month": 12, **extracted}])
    r = tp.start("n", user_text)
    req = tp.graph.get_state({"configurable": {"thread_id": "n"}}).values["request"]
    return r["prompt"], req


def test_named_towns_rank_first_and_leave_interests():
    prompt, req = _choose("Nainital aur Almora, 4 din, vegetarian khana, 2 log, December",
                          {"days": 4, "interests": ["Nainital", "Almora", "food"]})
    assert prompt["options"][0]["id"] == "destination_nainital+destination_almora"
    assert req["places"] == ["destination_nainital", "destination_almora"]
    assert req["interests"] == ["food"]


def test_single_named_town_beats_bigger_circuits():
    prompt, _ = _choose("A relaxed long weekend in Nainital for a family of 4",
                        {"days": 3, "interests": ["family"]})
    assert prompt["options"][0]["id"] == "destination_nainital"


def test_unavailable_town_is_explained_not_silently_dropped():
    prompt, _ = _choose("4 days in Auli for skiing", {"days": 4, "interests": ["ski"]})
    assert prompt["message"].startswith("Auli can't be planned yet")
    assert all("auli" not in o["id"] for o in prompt["options"])


def test_first_named_town_is_not_mistaken_for_the_origin():
    _, req = _choose("Nainital, Ranikhet and Almora, 4 days",
                     {"days": 4, "origin": "Nainital", "interests": []})
    assert req["origin"] is None
    assert req["places"] == ["destination_nainital", "destination_ranikhet",
                             "destination_almora"]


def test_misread_origin_falls_back_to_the_saved_one():
    tp, _ = make([{"days": 4, "people": 2, "month": 12, "origin": "Nainital"}])
    tp.start("o", "Nainital and Almora, 4 days", profile={"origin": "Pune"})
    req = tp.graph.get_state({"configurable": {"thread_id": "o"}}).values["request"]
    assert req["origin"] == "Pune"


def test_a_stated_starting_town_stays_the_origin():
    for text in ("3 days from Dehradun to Mussoorie", "Dehradun se Mussoorie, 3 din"):
        prompt, req = _choose(text, {"days": 3, "origin": "Dehradun", "interests": []})
        assert req["origin"] == "Dehradun" and req["places"] == ["destination_mussoorie"]
        assert prompt["options"][0]["id"] == "destination_mussoorie"


def test_places_survive_a_follow_up_answer():
    tp, _ = make([{"days": 3, "interests": []}, {"people": 2, "month": 11}])
    tp.start("f", "3 days in Rishikesh")
    r = tp.resume("f", "2 people in November")
    assert r["prompt"]["options"][0]["id"] == "destination_rishikesh"
