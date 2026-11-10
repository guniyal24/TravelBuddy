"""Plan-quality fixes: meals/stops stay in the day's town, the veg filter catches bars, and
towns the traveller names steer the circuit."""
import pytest
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
    # Jageshwar is in the registry but has no stays in the data, so it is not offered yet
    prompt, _ = _choose("4 days in Jageshwar for the temples", {"days": 4, "interests": []})
    assert prompt["message"].startswith("Jageshwar can't be planned yet")
    assert all("jageshwar" not in o["id"] for o in prompt["options"])


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


def test_named_towns_without_a_ready_circuit_get_one_built_for_them():
    prompt, _ = _choose("Ranikhet and Almora for 3 days, vegetarian",
                        {"days": 3, "interests": []})
    assert prompt["options"][0]["id"] == "destination_ranikhet+destination_almora"
    prompt, _ = _choose("Rishikesh and Badrinath in 5 days", {"days": 5, "interests": []})
    assert set(prompt["options"][0]["id"].split("+")) == {"destination_rishikesh",
                                                          "destination_badrinath"}


def test_built_circuit_needs_a_day_per_town_and_follows_the_road():
    from app.graph.trip_graph import _route_order
    prompt, _ = _choose("Haridwar, Almora and Mussoorie in 2 days", {"days": 2, "interests": []})
    assert all(len(o["id"].split("+")) <= 2 for o in prompt["options"])
    # Almora is far from the other two, so it is not visited in the middle
    route = _route_order(["destination_haridwar", "destination_almora", "destination_mussoorie"])
    assert route == ["destination_haridwar", "destination_mussoorie", "destination_almora"]


# ---------- a failing knowledge base never yields an empty plan ----------
def test_retriever_strict_mode_retries_then_raises(monkeypatch):
    from app.rag.retriever import RetrievalError, Retriever

    class Index:
        calls = 0

        def query(self, **kw):
            Index.calls += 1
            raise TimeoutError("slow")

    class Emb:
        def create(self, **kw):
            return type("R", (), {"data": [type("D", (), {"embedding": [0.1]})()]})()

    r = Retriever(type("E", (), {"embeddings": Emb()})(), Index(), "m")
    assert r.search("q") == []  # default: chat declines honestly
    Index.calls = 0
    with pytest.raises(RetrievalError):
        r.search("q", strict=True, attempts=3)
    assert Index.calls == 3


def test_planner_stops_with_a_clear_message_when_search_fails():
    from test_trip_graph import REQ, FakeLLM, FakeStore

    from app.graph.trip_graph import PlanningUnavailable, TripPlanner
    from app.rag.retriever import RetrievalError

    class DownRetriever:
        def search(self, *a, **kw):
            raise RetrievalError("down")

    tp = TripPlanner(FakeLLM([REQ]), DownRetriever(), FakeStore(), "s", "b")
    tp.start("d", "x")
    with pytest.raises(PlanningUnavailable, match="not responding"):
        tp.resume("d", f"{HW}+{RK}")


def test_planner_treats_empty_research_as_an_outage():
    from test_trip_graph import REQ, FakeLLM, FakeStore

    from app.graph.trip_graph import PlanningUnavailable, TripPlanner

    class EmptyRetriever:
        def search(self, *a, **kw):
            return []

    tp = TripPlanner(FakeLLM([REQ]), EmptyRetriever(), FakeStore(), "s", "b")
    tp.start("e", "x")
    with pytest.raises(PlanningUnavailable):
        tp.resume("e", f"{HW}+{RK}")


def test_api_turns_an_outage_into_a_503_and_a_stream_error():
    import fakeredis
    from conftest import FakeRAG, FakeStore
    from fastapi.testclient import TestClient

    from app.api.main import create_app
    from app.api.ratelimit import RateLimiter
    from app.config import Settings
    from app.graph.trip_graph import UNAVAILABLE_MSG, PlanningUnavailable
    from app.trips.store import TripStore

    class DownPlanner:
        def start(self, *a, **kw):
            raise PlanningUnavailable(UNAVAILABLE_MSG)

    app = create_app(Settings(secret_key="test-secret-key-at-least-16-chars"))
    app.state.store, app.state.rag, app.state.planner = FakeStore(), FakeRAG(), DownPlanner()
    app.state.trips = TripStore(":memory:")
    app.state.limiter = RateLimiter(fakeredis.FakeRedis(), 10)
    with TestClient(app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/guest").json()["access_token"]}
        r = c.post("/api/trips", json={"text": "x"}, headers=h)
        assert r.status_code == 503 and r.json()["detail"] == UNAVAILABLE_MSG
        s = c.post("/api/trips?stream=true", json={"text": "x"}, headers=h)
        assert UNAVAILABLE_MSG in s.text and '"type": "error"' in s.text


# ---------- ablation switches (evaluation only) ----------
def test_critic_ablation_lets_an_invalid_draft_through():
    from test_trip_graph import REQ, FakeLLM, FakeRetriever, FakeStore

    from app.graph.trip_graph import TripPlanner
    bad = {"days": [{"day": 1, "destination": HW, "stops": ["INVENTED"], "meals": [],
                     "stay": "s_hw1"}, *GOOD["days"][1:]]}
    tp = TripPlanner(FakeLLM([REQ, bad]), FakeRetriever(), FakeStore(), "s", "b",
                     ablate=frozenset({"critic"}))
    tp.start("a", "x")
    r = tp.resume("a", f"{HW}+{RK}")
    assert r["prompt"]["plan"]["days"][0]["stops"] == ["INVENTED"]  # nothing caught it


def test_food_ablation_skips_the_diet_filter():
    from test_trip_graph import REQ, FakeLLM, FakeRetriever, FakeStore

    from app.graph.trip_graph import TripPlanner
    on = TripPlanner(FakeLLM([{**REQ, "diet": "veg"}]), FakeRetriever(), FakeStore(), "s", "b")
    off = TripPlanner(FakeLLM([{**REQ, "diet": "veg"}]), FakeRetriever(), FakeStore(), "s",
                      "b", ablate=frozenset({"food"}))
    state = {"request": {**REQ, "diet": "veg"}, "destinations": [HW],
             "candidates": {HW: {"stops": [], "stays": [], "meals": [
                 {"id": "m1", "name": "Chicken Corner", "description": "chicken curry"},
                 {"id": "m2", "name": "Sattvik", "description": "pure veg thali"}]}}}
    assert [m["id"] for m in on._specialists(state)["candidates"][HW]["meals"]] == ["m2"]
    assert [m["id"] for m in off._specialists(state)["candidates"][HW]["meals"]] == ["m1", "m2"]


def test_consecutive_nights_in_one_town_keep_one_hotel():
    from app.graph.trip_graph import _one_stay_per_town
    plan = {"days": [
        {"day": 1, "destination": "destination_almora", "stay": "s1"},
        {"day": 2, "destination": "destination_almora", "stay": "s2"},   # LLM switched hotel
        {"day": 3, "destination": "destination_kausani", "stay": "s3"},  # new town: keep
        {"day": 4, "destination": "destination_kausani", "stay": None}]}  # last day: no stay
    assert [d["stay"] for d in _one_stay_per_town(plan)["days"]] == ["s1", "s1", "s3", None]
    assert _one_stay_per_town({"days": "bad"}) == {"days": "bad"}


def test_heading_like_listings_are_not_places():
    from ingest.schema import is_generic_name
    for junk in ["Temples Nearby", "Local Temples", "Other cafes", "Things to do"]:
        assert is_generic_name(junk), junk
    for real in ["Pingla Devi Mandir", "Hotel Golden", "Cafe Coffee Day", "Mall Road",
                 "Lake Mist", "Dhaba shop"]:
        assert not is_generic_name(real), real
