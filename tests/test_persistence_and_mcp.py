import pytest

from app.graph.persistence import make_checkpointer
from app.graph.trip_graph import TripPlanner
from mcp_server.client import LocalTools, MCPTools, ToolError
from tests.test_trip_graph import GOOD, REQ, FakeLLM, FakeRetriever, FakeStore

BOTH = "destination_haridwar+destination_rishikesh"


def planner(db, replies, tools=None):
    return TripPlanner(FakeLLM(replies), FakeRetriever(), FakeStore(), "s", "b",
                       checkpointer=make_checkpointer(str(db)), tools=tools)


# ---------------- persistence ----------------
def test_trip_survives_a_restart_and_keeps_its_owner(tmp_path):
    db = tmp_path / "trips.sqlite"
    first = planner(db, [REQ])
    r = first.start("trip-1", "3 days", owner="me@x.com")
    assert r["prompt"]["type"] == "choose"
    del first  # "server restart": the in-memory planner is gone

    second = planner(db, [GOOD])  # brand new instance reading the same file
    assert second.owner("trip-1") == "me@x.com"
    r = second.resume("trip-1", BOTH)
    assert r["prompt"]["type"] == "approve"
    assert second.resume("trip-1", {"action": "approve"})["status"] == "done"


def test_unknown_trip_has_no_owner(tmp_path):
    assert planner(tmp_path / "t.sqlite", []).owner("nope") is None


# ---------------- MCP client ----------------
@pytest.fixture(scope="module")
def mcp():
    client = MCPTools("memory")
    yield client
    client.close()


def test_mcp_memory_calls_real_tools_over_the_protocol(mcp):
    assert mcp.call("check_season", place_id="destination_haridwar", month=11)["status"] == "good"
    cost = mcp.call("estimate_budget", people=2, days=2, tier="budget",
                    stays=[{"nights": 1, "price_text": "₹500"}])
    assert cost["currency"] == "INR" and cost["total_inr"][0] > 0
    alt = mcp.call("check_altitude_plan", stops=[{"day": 1, "name": "A", "sleep_elevation_m": 300}])
    assert alt["ok"] is True


def test_mcp_tool_errors_raise_toolerror(mcp):
    with pytest.raises(ToolError):
        mcp.call("check_season", place_id="destination_haridwar", month=99)  # invalid month
    with pytest.raises(ToolError):
        mcp.call("no_such_tool")


def test_local_and_mcp_clients_agree(mcp):
    args = {"place_id": "destination_rishikesh", "month": 7}
    assert LocalTools().call("check_season", **args) == mcp.call("check_season", **args)


def test_mcp_stdio_subprocess_server_works():
    client = MCPTools("stdio")  # launches `python -m mcp_server.server` as a subprocess
    try:
        out = client.call("check_season", place_id="destination_haridwar", month=11)
        assert out["status"] == "good"
    finally:
        client.close()


def test_invalid_transport_rejected():
    with pytest.raises(ValueError):
        MCPTools("carrier-pigeon")


# ---------------- planner through MCP ----------------
def test_planner_runs_end_to_end_with_tools_via_mcp(tmp_path, mcp):
    tp = planner(tmp_path / "m.sqlite", [REQ, GOOD], tools=mcp)
    tp.start("t", "x", owner="o")
    r = tp.resume("t", BOTH)
    assert r["prompt"]["type"] == "approve" and r["prompt"]["cost"]["currency"] == "INR"


def test_planner_degrades_to_unknown_season_if_tool_fails(tmp_path):
    class BrokenTools:
        def call(self, name, **kw):
            if name == "check_season":
                raise ToolError("down")
            return LocalTools().call(name, **kw)

    tp = planner(tmp_path / "b.sqlite", [REQ, GOOD], tools=BrokenTools())
    tp.start("t", "x")
    r = tp.resume("t", BOTH)
    assert r["prompt"]["type"] == "approve"
    assert any("no season data" in w.lower() for w in r["prompt"]["warnings"])
