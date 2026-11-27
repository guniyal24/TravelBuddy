"""Town discovery: town profiles, LLM-proposed circuits checked in code, and grading of the
places retrieved for the chosen towns."""
from app.graph.circuits import MAX_TOWNS, check_circuit, leg_days, parse_circuits
from app.graph.trip_graph import TripPlanner, _rerank_towns
from app.rag.retriever import Retriever
from app.towns import CIRCUITS, DESTINATIONS
from ingest.town_profiles import TOWN_NAMESPACE, build_profiles, pinecone_town_record

HW, RK, NT = "destination_haridwar", "destination_rishikesh", "destination_nainital"
KB = ("destination_kedarnath", "destination_badrinath")


def road(a, b):
    return TripPlanner._road_leg(a, b)


# ---------------- circuit check ----------------
def test_every_curated_circuit_passes_at_its_minimum_days():
    for towns, min_days in CIRCUITS:
        assert check_circuit(towns, min_days, set(towns), road) == [], towns


def test_circuit_check_rejects_impossible_circuits():
    allowed = {HW, RK, NT, *KB}
    assert check_circuit([HW, RK], 2, allowed, road) == []
    assert "unknown or unavailable" in check_circuit([HW, "destination_atlantis"], 3, allowed,
                                                     road)[0]
    assert check_circuit([HW, HW], 3, allowed, road) == ["a town is repeated"]
    assert "needs at least" in check_circuit(list(KB), 3, allowed, road)[0]  # 10-12 h apart
    many = list(DESTINATIONS)[: MAX_TOWNS + 1]
    assert f"at most {MAX_TOWNS}" in check_circuit(many, 14, set(many), road)[0]
    assert check_circuit([], 3, allowed, road) == ["no towns"]


def test_circuit_check_rejects_long_or_unknown_legs():
    long = lambda a, b: {"hours": [13, 15]}  # noqa: E731
    assert "at most 12 h" in check_circuit([HW, RK], 9, {HW, RK}, long)[0]
    assert "no known road route" in check_circuit([HW, RK], 9, {HW, RK}, lambda a, b: None)[0]


def test_leg_days_grow_with_drive_time():
    assert [leg_days(h) for h in (1, 3.5, 6, 10, 11)] == [0, 0.5, 1, 1, 2]


def test_parse_circuits_maps_codes_and_keeps_unknown_towns_for_the_check():
    codes = {"haridwar": HW, "rishikesh": RK}
    out = parse_circuits({"circuits": [
        {"towns": ["Haridwar", "rishikesh"], "why": "Ganga towns"},
        {"towns": ["goa"]}, "junk", {"towns": []}, {"towns": ["rishikesh"]},
        {"towns": ["haridwar"]}]}, codes)
    assert out[0] == {"towns": [HW, RK], "why": "Ganga towns"}
    assert out[1]["towns"] == ["goa"]  # kept, so check_circuit rejects it visibly
    assert len(out) == 3
    assert parse_circuits({}, codes) == [] and parse_circuits(None, codes) == []


# ---------------- town search ----------------
def test_theme_match_lifts_a_clearly_named_interest():
    hits = [{"id": "destination_gangotri", "score": 0.54}, {"id": HW, "score": 0.48}]
    assert _rerank_towns(hits, ["temples", "Ganga", "aarti"])[0]["id"] == HW
    assert _rerank_towns(hits, [])[0]["id"] == "destination_gangotri"  # no interests: as found


def test_profiles_describe_what_can_be_planned():
    towns = [{"id": HW, "name": "Haridwar", "region": "Garhwal", "elevation_m": 294,
              "themes": ["temple", "aarti"], "offer": True},
             {"id": "destination_jageshwar", "name": "Jageshwar", "offer": False}]
    ents = [{"id": HW, "type": "Destination", "name": "Haridwar",
             "description": "thumb|Har Ki Pauri Haridwar is a holy city. More text here."},
            {"id": "a1", "type": "Attraction", "name": "Har Ki Pauri", "destination_id": HW,
             "description": "The famous ghat."},
            {"id": "a2", "type": "Attraction", "name": "Temples Nearby", "destination_id": HW},
            {"id": "e1", "type": "Eatery", "name": "Mohan Puri", "destination_id": HW},
            {"id": "s1", "type": "Stay", "name": "Hotel", "destination_id": HW,
             "tier": "budget"}]
    [p] = build_profiles(ents, towns)  # the town that is not offered gets no profile
    assert p["id"] == HW and p["counts"] == {"sights": 1, "eateries": 1, "stays": 1}
    assert "thumb|" not in p["text"] and "Har Ki Pauri" in p["text"]
    assert "Good for: temple, aarti." in p["text"] and "Temples Nearby" not in p["text"]
    assert "(budget)" in p["text"]
    rec = pinecone_town_record(p)
    assert rec["id"] == HW and rec["metadata"]["type"] == "Town"
    assert rec["metadata"]["city"] == "Haridwar"


def test_retriever_searches_the_given_namespace():
    seen = {}

    class Index:
        def query(self, **kw):
            seen.update(kw)
            return {"matches": [{"id": HW, "score": 0.5, "metadata": {"name": "Haridwar"}}]}

    class Embedder:
        class embeddings:  # noqa: N801
            @staticmethod
            def create(**kw):
                return type("R", (), {"data": [type("D", (), {"embedding": [0.1]})]})

    r = Retriever(Embedder, Index(), "m")
    assert r.search("ganga", top_k=3, namespace=TOWN_NAMESPACE)[0]["id"] == HW
    assert seen["namespace"] == TOWN_NAMESPACE and seen["top_k"] == 3
    seen.clear()
    r.search("ganga")  # places (and chat) stay in the default namespace
    assert "namespace" not in seen


# ---------------- planner with discovery="search" ----------------
def ent(i, typ, dest, name, tier=None):
    return {"id": i, "type": typ, "destination_id": dest, "name": name, "tier": tier,
            "price_text": "", "lat": None, "lon": None}


ENTS = {e["id"]: e for e in [
    ent("a_hw1", "Attraction", HW, "Har Ki Pauri"), ent("a_hw2", "Attraction", HW, "Bharat Mata"),
    ent("e_hw1", "Eatery", HW, "Mohan Puri"), ent("s_hw1", "Stay", HW, "Hotel Golden", "budget"),
    ent("a_rk1", "Attraction", RK, "Laxman Jhula"), ent("a_rk2", "Activity", RK, "Yoga Class"),
    ent("e_rk1", "Eatery", RK, "German Bakery"), ent("s_rk1", "Stay", RK, "Hostel", "budget")]}


class LLM:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def json(self, model, messages, default=None):
        self.prompts.append((messages[0]["content"], messages[-1]["content"]))
        return self.replies.pop(0)


class Retriever_:
    def __init__(self, fail_towns=False):
        self.fail_towns, self.calls = fail_towns, []

    def search(self, query, top_k=12, filter=None, namespace=None, **kw):
        self.calls.append((namespace, filter))
        if namespace == TOWN_NAMESPACE:
            if self.fail_towns:
                raise ConnectionError("down")
            towns = [HW, RK]
            if isinstance(filter.get("city"), dict):
                towns = [d for d in towns if DESTINATIONS[d]["name"] in filter["city"]["$in"]]
            return [{"id": d, "score": 0.5, "name": DESTINATIONS[d]["name"], "type": "Town",
                     "city": DESTINATIONS[d]["name"], "text": f"{DESTINATIONS[d]['name']} profile"}
                    for d in towns]
        dest = HW if filter["city"] == "Haridwar" else RK
        return [{"id": e["id"], "score": 1, "name": e["name"], "type": e["type"],
                 "city": filter["city"], "text": ""} for e in ENTS.values()
                if e["destination_id"] == dest and e["type"] in filter["type"]["$in"]]


class Store:
    def __init__(self):
        self.fetched = []

    def fetch_entities(self, ids):
        self.fetched.append(list(ids))
        return {i: ENTS[i] for i in ids if i in ENTS}


REQ = {"days": 3, "people": 2, "month": 11, "tier": "budget", "interests": ["temple"]}
GOOD = {"days": [
    {"day": 1, "destination": HW, "stops": ["a_hw1"], "meals": ["e_hw1"], "stay": "s_hw1"},
    {"day": 2, "destination": RK, "stops": ["a_rk1"], "meals": ["e_rk1"], "stay": "s_rk1"},
    {"day": 3, "destination": RK, "stops": ["a_rk2"], "meals": [], "stay": None}]}
BOTH = {"circuits": [{"towns": ["haridwar", "rishikesh"], "why": "Ganga towns, an hour apart."}]}


def make(replies, **kw):
    llm, retriever, store = LLM(replies), Retriever_(**kw), Store()
    return TripPlanner(llm, retriever, store, "small", "big", discovery="search"), llm, retriever, store


def test_llm_circuits_are_offered_and_places_fetched_only_for_the_chosen_towns():
    tp, llm, retriever, store = make([REQ, BOTH, {"relevant": ["P2"]}, GOOD])
    r = tp.start("d1", "3 days in November for 2 people, love temples")
    opts = r["prompt"]["options"]
    assert opts[0]["id"] == f"{HW}+{RK}" and opts[0]["why"] == "Ganga towns, an hour apart."
    assert {o["id"] for o in opts} == {f"{HW}+{RK}", HW}  # + the best single town, from code
    circuit_system, circuit_prompt = llm.prompts[1]
    assert "circuits" in circuit_system and "haridwar | Haridwar profile" in circuit_prompt
    assert "haridwar-rishikesh" in circuit_prompt  # road times between candidates
    assert store.fetched == []  # no place details before a circuit is chosen
    r = tp.resume("d1", f"{HW}+{RK}")
    assert r["prompt"]["type"] == "approve"
    state = tp.graph.get_state({"configurable": {"thread_id": "d1"}}).values
    assert state["discovery"]["method"] == "search" and "fallback" not in state["discovery"]
    assert state["grading"] == {"graded": 4, "relevant": 1}
    # The graded place (P2 = Bharat Mata) moved ahead of Har Ki Pauri for the planner.
    plan_prompt = llm.prompts[-1][1]
    assert plan_prompt.index("Bharat Mata") < plan_prompt.index("Har Ki Pauri")
    fetched = {i for ids in store.fetched for i in ids}
    assert fetched <= {e for e, v in ENTS.items() if v["destination_id"] in (HW, RK)}


def test_impossible_llm_circuit_is_sent_back_with_feedback_then_replaced():
    bad = {"circuits": [{"towns": ["haridwar", "goa"], "why": "?"}]}
    tp, llm, *_ = make([REQ, bad, BOTH])
    r = tp.start("d2", "3 days in November for 2 people, love temples")
    assert r["prompt"]["options"][0]["id"] == f"{HW}+{RK}"
    assert "Fix these problems" in llm.prompts[2][1] and "goa" in llm.prompts[2][1]
    state = tp.graph.get_state({"configurable": {"thread_id": "d2"}}).values
    assert state["discovery"]["attempts"] == 2
    assert state["discovery"]["rejected"][0]["towns"] == [HW, "goa"]


def test_named_towns_are_always_offered_exactly():
    req = {**REQ, "days": 3}
    only_hw = {"circuits": [{"towns": ["haridwar"], "why": "Short trip."}]}
    tp, *_ = make([req, only_hw])
    r = tp.start("d3", "3 days in Haridwar and Rishikesh in November for 2 people")
    assert r["prompt"]["options"][0]["id"] == f"{HW}+{RK}"  # named towns rank first


def test_town_search_outage_falls_back_to_the_rule_based_circuits():
    tp, llm, *_ = make([REQ, GOOD], fail_towns=True)
    r = tp.start("d4", "3 days in November for 2 people, love temples")
    assert r["prompt"]["type"] == "choose" and len(r["prompt"]["options"]) == 3
    state = tp.graph.get_state({"configurable": {"thread_id": "d4"}}).values
    assert state["discovery"]["fallback"] == "town search failed"
    assert len(llm.prompts) == 1  # no circuit LLM call was made


def test_rules_mode_makes_no_town_search_or_circuit_call():
    llm, retriever = LLM([REQ]), Retriever_()
    tp = TripPlanner(llm, retriever, Store(), "small", "big")  # discovery defaults to "rules"
    tp.start("d5", "3 days in November for 2 people, love temples")
    assert all(ns is None for ns, _ in retriever.calls) and len(llm.prompts) == 1


def test_place_search_uses_the_same_city_name_the_loader_stored():
    """Regression: Ghangaria's places are stored under "Ghangaria"; searching with the display
    name "Valley of Flowers (Ghangaria)" found nothing, so every trip there failed."""
    from app.towns import search_city
    from ingest.load import pinecone_record

    assert search_city("destination_ghangaria") == "Ghangaria"
    for d in DESTINATIONS:
        place = {"id": "x", "name": "x", "type": "Attraction", "destination_id": d}
        assert pinecone_record(place)["metadata"]["city"] == search_city(d)
