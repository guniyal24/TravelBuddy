from app.rag.llm import LLM
from app.rag.retriever import RetrievalError
from app.rag.self_rag import (
    ABSTAIN_MESSAGE,
    ERROR_MESSAGE,
    UNAVAILABLE_MESSAGE,
    SelfRAG,
    format_entity,
)


class FakeLLM:
    """Scripted LLM: .json() and .complete() each pop from their own queue."""

    def __init__(self, json_replies, completions):
        self.json_replies = list(json_replies)
        self.completions = list(completions)
        self.complete_prompts = []

    def json(self, model, messages, default=None):
        return self.json_replies.pop(0)

    def complete(self, model, messages, temperature=0.0, max_tokens=None):
        self.complete_prompts.append(messages[-1]["content"])
        return self.completions.pop(0)


class FakeRetriever:
    def __init__(self, results_per_call):
        self.results = list(results_per_call)
        self.queries = []

    def search(self, query, top_k=12, **kw):
        self.queries.append(query)
        return self.results.pop(0) if self.results else []


class FakeStore:
    def __init__(self):
        self.logged = []

    def fetch_entities(self, ids):
        return {i: {"name": i, "description": f"desc of {i}", "tier": "budget",
                    "price_text": "Rs 500"} for i in ids}

    def fetch_graph_context(self, ids):
        return [{"source_id": ids[0], "rel": "NEAR", "target_id": "other", "name": "Other Place",
                 "desc": "", "km": 1.2}]

    def log_interaction(self, *args):
        self.logged.append(args)


def doc(i, name="Hotel A", typ="Stay"):
    return {"id": i, "score": 0.9, "name": name, "type": typ, "city": "Rishikesh", "text": "t"}


def make(json_replies, completions, retrievals):
    llm = FakeLLM(json_replies, completions)
    rag = SelfRAG(FakeRetriever(retrievals), FakeStore(), llm, "router", "reasoner")
    return rag, llm


def test_happy_path_filters_irrelevant_and_cites():
    rag, _ = make(
        json_replies=[{"relevant_ids": ["a"]}, {"grounded": True, "unsupported_claims": []}],
        completions=["Try Hotel A [a]."],
        retrievals=[[doc("a"), doc("b", "Hotel B")]],
    )
    s = rag.run("cheap stay in Rishikesh")
    assert [d["id"] for d in s["relevant"]] == ["a"]
    assert s["answer"] == "Try Hotel A [a]." and s["grounded"] is True
    assert "[a] Hotel A" in s["context"] and "Rs 500" in s["context"]
    assert "1.2 km" in s["context"]  # nearby fact included


def test_rewrites_query_when_nothing_relevant_then_succeeds():
    rag, llm = make(
        json_replies=[{"relevant_ids": []}, {"relevant_ids": ["a"]},
                      {"grounded": True, "unsupported_claims": []}],
        completions=["budget hotel Rishikesh", "Hotel A [a]"],
        retrievals=[[doc("x")], [doc("a")]],
    )
    s = rag.run("somewhere to sleep cheap")
    assert s["retrievals"] == 2 and not s.get("abstained")
    assert rag.retriever.queries == ["somewhere to sleep cheap", "budget hotel Rishikesh"]


def test_abstains_when_nothing_relevant_after_retries():
    rag, _ = make(
        json_replies=[{"relevant_ids": []}, {"relevant_ids": []}],
        completions=["rewritten"],
        retrievals=[[doc("x")], [doc("y")]],
    )
    s = rag.run("best hotel in Nainital")
    assert s["abstained"] is True and s["answer"] == ABSTAIN_MESSAGE


def test_abstains_when_retrieval_empty():
    rag, _ = make(json_replies=[], completions=["q2"], retrievals=[[], []])
    assert rag.run("anything")["abstained"] is True


def test_regenerates_once_when_ungrounded_with_feedback():
    rag, llm = make(
        json_replies=[{"relevant_ids": ["a"]},
                      {"grounded": False, "unsupported_claims": ["Hotel Z has a pool"]},
                      {"grounded": True, "unsupported_claims": []}],
        completions=["Hotel Z has a pool", "Hotel A [a]"],
        retrievals=[[doc("a")]],
    )
    s = rag.run("hotel with pool")
    assert s["generations"] == 2 and s["answer"] == "Hotel A [a]"
    assert "Hotel Z has a pool" in llm.complete_prompts[1]  # feedback passed to retry


def test_adds_caveat_if_still_ungrounded_after_max_generations():
    bad = {"grounded": False, "unsupported_claims": ["x"]}
    rag, _ = make(
        json_replies=[{"relevant_ids": ["a"]}, bad, bad],
        completions=["first", "second"],
        retrievals=[[doc("a")]],
    )
    s = rag.run("q")
    assert s["generations"] == 2 and s["grounded"] is False
    assert "not be fully verified" in s["answer"]


def test_get_answer_matches_hybrid_interface_and_logs():
    rag, _ = make(
        json_replies=[{"relevant_ids": ["a"]}, {"grounded": True}],
        completions=["ok [a]"], retrievals=[[doc("a")]],
    )
    chunks = list(rag.get_answer("q", "sess1", []))
    assert chunks[-1] == "ok [a]"
    statuses = [c for c in chunks[:-1]]
    assert all(c.startswith("\x01") and c.endswith("\x02") for c in statuses)
    assert "\x01Verifying facts...\x02" in statuses
    assert rag.store.logged == [("sess1", "q", "ok [a]", ["a"])]


def test_a_search_outage_is_reported_not_answered_as_unknown():
    class DownRetriever(FakeRetriever):
        def search(self, query, top_k=12, **kw):
            assert kw.get("strict") is True  # outages must raise, not look like "nothing found"
            raise RetrievalError("down")

    rag = SelfRAG(DownRetriever([]), FakeStore(), FakeLLM([], []), "router", "reasoner")
    chunks = list(rag.get_answer("yoga in Rishikesh", "s", []))
    assert chunks[-1] == UNAVAILABLE_MESSAGE and ABSTAIN_MESSAGE not in chunks
    assert rag.store.logged == []  # nothing answered, nothing logged as an answer


def test_an_unexpected_failure_still_ends_with_a_message():
    class BrokenLLM(FakeLLM):
        def json(self, *a, **kw):
            raise RuntimeError("provider exploded")

    rag = SelfRAG(FakeRetriever([[doc("a")]]), FakeStore(), BrokenLLM([], []), "r", "g")
    chunks = list(rag.get_answer("q", "s", []))
    assert chunks[-1] == ERROR_MESSAGE and chunks[0] == "\x01Searching places...\x02"


def test_stream_steps_yields_nodes_in_order():
    rag, _ = make(
        json_replies=[{"relevant_ids": ["a"]}, {"grounded": True}],
        completions=["ok"], retrievals=[[doc("a")]],
    )
    nodes = [name for name, _ in rag.stream_steps("q")]
    assert nodes == ["retrieve", "grade", "expand", "generate", "check"]


def test_format_entity_includes_price_tier_and_falls_back_to_doc_text():
    out = format_entity({"id": "i", "name": "N", "type": "Stay", "city": "C", "text": "fallback"},
                        None)
    assert "fallback" in out and out.startswith("[i] N")


def test_llm_json_parser_handles_wrapped_and_bad_output():
    class Resp:
        def __init__(self, text):
            self.choices = [type("C", (), {"message": type("M", (), {"content": text})()})()]
            self.usage = type("U", (), {"prompt_tokens": 3, "completion_tokens": 2})()

    class Client:
        def __init__(self, text):
            self.chat = type("Ch", (), {"completions": self})()
            self.text = text

        def create(self, **kw):
            return Resp(self.text)

    ok = LLM(Client('Sure! ```json\n{"a": 1}\n```'))
    assert ok.json("m", []) == {"a": 1} and ok.snapshot()["prompt_tokens"] == 3
    assert LLM(Client("not json")).json("m", [], default={"d": 1}) == {"d": 1}
    assert LLM(Client("{broken")).json("m", [], default={"d": 2}) == {"d": 2}


def test_grader_ids_echoed_with_prefix_or_brackets_are_accepted():
    rag, _ = make(
        json_replies=[{"relevant_ids": ["id=a", "[b]"]}, {"grounded": True}],
        completions=["ok"], retrievals=[[doc("a"), doc("b"), doc("c")]],
    )
    assert [d["id"] for d in rag.run("q")["relevant"]] == ["a", "b"]


def test_retriever_search_times_out_instead_of_hanging():
    import time

    from app.rag.retriever import Retriever

    class Embedder:
        class embeddings:  # noqa: N801
            @staticmethod
            def create(**kw):
                return type("R", (), {"data": [type("D", (), {"embedding": [0.1]})()]})()

    class HangingIndex:
        def query(self, **kw):
            time.sleep(2)
            return {"matches": []}

    r = Retriever(Embedder(), HangingIndex(), "m", query_timeout=0.2)
    start = time.time()
    assert r.search("anything") == []
    assert time.time() - start < 1.0  # returned promptly, did not wait for the hung call


def test_llm_json_degrades_to_default_on_provider_failure_and_caps_output():
    class Boom:
        def __init__(self):
            self.chat = type("Ch", (), {"completions": self})()
            self.kwargs = None

        def create(self, **kw):
            self.kwargs = kw
            raise TimeoutError("provider stalled")

    boom = Boom()
    out = LLM(boom).json("m", [], default={"relevant_ids": []})
    assert out == {"relevant_ids": []}      # no exception escapes
    assert boom.kwargs["max_tokens"] == 600  # output is capped
