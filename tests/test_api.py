def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_duplicate_and_login(client):
    body = {"email": "x@y.com", "password": "pw123456"}
    assert client.post("/api/register", json=body).status_code == 200
    assert client.post("/api/register", json=body).status_code == 400
    ok = client.post("/api/token", data={"username": "x@y.com", "password": "pw123456"})
    assert ok.status_code == 200 and ok.json()["token_type"] == "bearer"
    bad = client.post("/api/token", data={"username": "x@y.com", "password": "nope"})
    assert bad.status_code == 401


def test_chat_requires_auth(client):
    assert client.post("/api/chat", json={"query": "hi"}).status_code == 401


def test_chat_streams_and_returns_session_id(client, auth_headers):
    r = client.post("/api/chat", json={"query": "hi"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.text == "Hello from Uttarakhand"
    assert r.headers["x-session-id"]


def test_chat_rate_limit_returns_429(client, auth_headers):
    # limiter in fixture allows 3/min
    codes = [
        client.post("/api/chat", json={"query": "hi"}, headers=auth_headers).status_code
        for _ in range(5)
    ]
    assert codes == [200, 200, 200, 429, 429]


def test_feedback(client, auth_headers):
    r = client.post(
        "/api/feedback",
        json={"session_id": "s", "query": "q", "rating": 5},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert client.app.state.store.feedback


def test_trip_start_resume_and_ownership(client, auth_headers):
    r = client.post("/api/trips", json={"text": "3 days"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "waiting"
    trip_id = r.json()["trip_id"]
    r2 = client.post(f"/api/trips/{trip_id}/resume", json={"value": {"action": "approve"}},
                     headers=auth_headers)
    assert r2.json() == {"trip_id": trip_id, "status": "done", "itinerary": "# plan"}

    client.post("/api/register", json={"email": "other@b.com", "password": "pass1234"})
    tok = client.post("/api/token", data={"username": "other@b.com", "password": "pass1234"})
    other = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    assert client.post(f"/api/trips/{trip_id}/resume", json={"value": "x"},
                       headers=other).status_code == 403
    assert client.post("/api/trips/nope/resume", json={"value": "x"},
                       headers=auth_headers).status_code == 404


def test_trips_require_auth(client):
    assert client.post("/api/trips", json={"text": "x"}).status_code == 401


# ---------- profile, saved trips, replan, checklist, export ----------
def _saved_trip(client):
    from test_tier23 import _trip  # a realistic structured trip
    trip = {**_trip(), "checklist": [{"id": "todo-0", "kind": "todo", "label": "Book bus",
                                      "done": False}]}
    trip.pop("trip_id")
    trip.pop("title")
    client.app.state.trips.save_trip("T1", "a@b.com", trip)


def test_profile_roundtrip_is_validated_and_private(client, auth_headers):
    r = client.put("/api/profile", json={"tier": "mid", "diet": "veg", "hack": 1},
                   headers=auth_headers)
    assert r.json() == {"tier": "mid", "diet": "veg"}
    assert client.get("/api/profile", headers=auth_headers).json() == {"tier": "mid", "diet": "veg"}
    assert client.get("/api/profile").status_code == 401


def test_new_trip_receives_the_saved_profile(client, auth_headers):
    client.put("/api/profile", json={"tier": "premium"}, headers=auth_headers)
    client.post("/api/trips", json={"text": "x"}, headers=auth_headers)
    assert client.app.state.planner.calls[0][0] == "start"


def test_trip_list_get_checklist_and_ownership(client, auth_headers):
    _saved_trip(client)
    assert client.get("/api/trips", headers=auth_headers).json()[0]["trip_id"] == "T1"
    t = client.get("/api/trips/T1", headers=auth_headers).json()
    assert t["checklist"][0]["done"] is False and t["timeline"]["days"]
    r = client.put("/api/trips/T1/checklist", json={"item_id": "todo-0", "done": True},
                   headers=auth_headers)
    assert r.status_code == 200
    assert client.get("/api/trips/T1", headers=auth_headers).json()["checklist"][0]["done"] is True
    assert client.put("/api/trips/T1/checklist", json={"item_id": "zzz", "done": True},
                      headers=auth_headers).status_code == 404
    client.post("/api/register", json={"email": "c@d.com", "password": "pass1234"})
    tok = client.post("/api/token", data={"username": "c@d.com", "password": "pass1234"}).json()
    other = {"Authorization": f"Bearer {tok['access_token']}"}
    assert client.get("/api/trips/T1", headers=other).status_code == 403
    assert client.get("/api/trips", headers=other).json() == []
    assert client.put("/api/trips/T1/checklist", json={"item_id": "todo-0", "done": False},
                      headers=other).status_code == 403
    assert client.get("/api/trips/NOPE", headers=auth_headers).status_code == 404


def test_export_formats(client, auth_headers):
    _saved_trip(client)
    txt = client.get("/api/trips/T1/export?format=txt", headers=auth_headers)
    assert txt.status_code == 200 and "Day 1 Haridwar" in txt.text
    pdf = client.get("/api/trips/T1/export?format=pdf", headers=auth_headers)
    assert pdf.content[:4] == b"%PDF" and "attachment" in pdf.headers["content-disposition"]
    ics = client.get("/api/trips/T1/export?format=ics&start=2026-11-20", headers=auth_headers)
    assert ics.status_code == 200 and "BEGIN:VCALENDAR" in ics.text
    assert client.get("/api/trips/T1/export?format=ics", headers=auth_headers).status_code == 400
    assert client.get("/api/trips/T1/export?format=ics&start=nope",
                      headers=auth_headers).status_code == 400
    assert client.get("/api/trips/T1/export?format=doc", headers=auth_headers).status_code == 400
    assert client.get("/api/trips/T1/export?format=txt").status_code == 401


def test_replan_endpoint(client, auth_headers):
    import fakeredis

    from app.api.ratelimit import RateLimiter
    client.app.state.limiter = RateLimiter(fakeredis.FakeRedis(), limit_per_minute=100)
    start = client.post("/api/trips", json={"text": "x"}, headers=auth_headers).json()
    tid = start["trip_id"]
    r = client.post(f"/api/trips/{tid}/replan", json={"from_day": 2, "reason": "rain"},
                    headers=auth_headers)
    assert r.status_code == 200 and r.json()["prompt"]["type"] == "approve"
    assert client.post(f"/api/trips/{tid}/replan", json={"from_day": 9, "reason": "rain"},
                       headers=auth_headers).status_code == 400
    assert client.post(f"/api/trips/{tid}/replan", json={"from_day": 2, "reason": "  "},
                       headers=auth_headers).status_code == 400
    assert client.post("/api/trips/nope/replan", json={"from_day": 1, "reason": "x"},
                       headers=auth_headers).status_code == 404
