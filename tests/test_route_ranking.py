from app.trips.ranking import rank_routes, transfer_estimate


def test_personalization_keeps_requested_town_priority_and_caution_or_unknown_slots():
    def route(town, score, hours, *, reasons=(), wanted=True):
        return {"id": town, "score": score, "reasons": reasons,
                "transfers": {"hours": hours} if hours else None,
                "destinations": ["requested", town] if wanted else [town]}

    options = [
        route("long", 6, [6, 8]),
        route("caution", 5, [1, 2], reasons=["Season warning"]),
        route("unknown", 5, None),
        route("short", 5, [2, 3]),
        route("unrequested", 10, [0, 0], wanted=False),
    ]
    fixed = {"requested"}
    assert rank_routes(options, fixed, {}) == options
    assert rank_routes(options, fixed, {"shorter_transfers": .5}) == [
        options[3], options[1], options[2], options[0], options[4],
    ]


def test_an_unknown_road_leg_makes_the_whole_estimate_unavailable():
    assert transfer_estimate(["destination_haridwar", "destination_rishikesh"])
    assert transfer_estimate(["destination_haridwar", "destination_rishikesh", "unknown"]) is None
