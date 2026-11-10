import pytest

from app.cost.engine import StayChoice, TransportLeg, TripInput, estimate, rooms_needed
from app.cost.pricing import parse_price_range
from app.rules.altitude import Stop, check_altitude_plan
from app.rules.season import check_season, load_seasons


@pytest.mark.parametrize("text,expected", [
    ("₹300-2500", (300, 2500)), ("₹700/₹1500 (Air-con & non-air-con)", (700, 1500)),
    ("Rs 500", (500, 500)), ("₹1,200", (1200, 1200)), ("", None), ("free entry", None),
    ("call 9876543210", None),
])
def test_parse_price_range(text, expected):
    assert parse_price_range(text) == expected


def test_rooms_needed():
    assert [rooms_needed(n) for n in (1, 2, 3, 4, 5)] == [1, 1, 2, 2, 3]


def test_estimate_uses_listing_price_and_labels_sources():
    trip = TripInput(people=3, days=2, tier="budget",
                     stays=[StayChoice(nights=2, price_text="₹1000-1500", name="Hotel X")],
                     legs=[TransportLeg("Delhi-Haridwar bus", (300, 500))],
                     entry_fees_per_person=50, permits_total=200)
    est = estimate(trip)
    stay = est.items[0]
    assert stay.source == "listing" and (stay.low, stay.high) == (1000 * 2 * 2, 1500 * 2 * 2)
    assert any(i.label.startswith("Travel") and i.low == 900 for i in est.items)
    assert est.total[0] > est.subtotal[0] and est.total[1] > est.subtotal[1]  # buffer applied
    assert est.per_person[1] == round(est.total[1] / 3)


def test_estimate_falls_back_to_tier_assumption_and_is_deterministic():
    trip = TripInput(people=2, days=1, tier="mid", stays=[StayChoice(nights=1, tier="mid")])
    a, b = estimate(trip), estimate(trip)
    assert a == b and a.items[0].source == "assumption"


def test_estimate_validates_input():
    with pytest.raises(ValueError):
        estimate(TripInput(people=0, days=1))
    with pytest.raises(ValueError):
        estimate(TripInput(people=1, days=1, tier="luxury"))


def test_altitude_flags_big_sleep_gain_above_3000m():
    plan = [Stop(1, "Rishikesh", 350), Stop(2, "Joshimath", 1900), Stop(3, "Hemkund base", 3050),
            Stop(4, "Summit camp", 4300)]
    msgs = [i.message for i in check_altitude_plan(plan)]
    assert any("4300" in m for m in msgs)
    assert not any("3050" in m for m in msgs) or any("rises" in m for m in msgs)


def test_altitude_ok_for_gradual_plan_and_vulnerable_flag():
    gradual = [Stop(1, "A", 2500), Stop(2, "B", 3000), Stop(3, "C", 3400), Stop(4, "D", 3800)]
    assert check_altitude_plan(gradual) == []
    msgs = check_altitude_plan(gradual, vulnerable_travellers=True)
    assert len(msgs) == 1 and "high altitude" in msgs[0].message


def test_season_known_unknown_and_validation():
    s = load_seasons()
    assert check_season("destination_rishikesh", 7, s).status == "caution"
    assert "rafting" in check_season("destination_rishikesh", 7, s).reasons[0]
    assert check_season("destination_haridwar", 11, s).status == "good"
    unk = check_season("destination_nowhere", 6, s)
    assert unk.status == "unknown"  # never guesses
    with pytest.raises(ValueError):
        check_season("destination_haridwar", 13, s)
