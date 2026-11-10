from app.booking.links import build_booking_links, render_links

PLAN = {"days": [{"day": 1, "destination": "destination_rishikesh", "stay": "s1"},
                 {"day": 2, "destination": "destination_rishikesh", "stay": None}]}
ENTS = {"s1": {"name": "Hostel & Co", "id": "s1"}}


def test_links_for_known_origin_include_flight_train_bus_and_stay():
    links = build_booking_links({"origin": "Pune"}, PLAN, ENTS)
    assert "PNQ" in links["flights"][0]["url"] and "DED" in links["flights"][0]["url"]
    assert "YNRK" in links["trains"][0]["label"]
    assert "Hostel+%26+Co+Rishikesh" in links["stays"][0]["url"]  # properly URL-encoded
    assert "fares" in links["buses"][0]["note"]


def test_unknown_origin_skips_flight_and_missing_origin_skips_ground_links():
    assert build_booking_links({"origin": "Smallville"}, PLAN, ENTS)["flights"] == []
    none = build_booking_links({}, PLAN, ENTS)
    assert none["trains"] == [] and none["buses"] == [] and none["flights"] == []


def test_render_has_checklist_and_no_payment_details():
    text = render_links(build_booking_links({"origin": "Delhi"}, PLAN, ENTS))
    assert "- [ ] Book long-distance travel first" in text and "you complete payment" in text
    assert "card" not in text.lower()
