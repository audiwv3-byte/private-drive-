"""Fixed fare and extra-service safety contract, no payment side effects."""
import pytest
from pd_native_order_quote import validated_details

def test_approved_vilnius_airport_both_directions_no_discount():
    for origin, destination in (
        ("Вильнюс", "Аэропорт Вильнюса"),
        ("Аэропорт Вильнюса", "Вильнюс"),
    ):
        quote = validated_details({"ride_type": "transfer"},
                                  origin=origin, destination=destination)
        assert quote["quoted_total_cents"] == 4000
        assert quote["currency"] == "EUR"
        assert quote["quote_required"] is False

def test_known_tariff_and_approved_addons():
    quote = validated_details({"ride_type": "transfer", "extras": [
        "meet_sign", "sober_driver",
    ]}, origin="Вильнюс", destination="Каунас")
    assert quote["quoted_total_cents"] == 23500
    assert quote["quote_required"] is False
    return_trip = validated_details({"ride_type": "transfer", "round_trip": True},
                                    origin="Вильнюс", destination="Каунас")
    assert return_trip["quoted_total_cents"] == 20000

def test_unknown_fares_and_unpriced_extras_require_a_quote():
    for request, a, b in [
        ({"ride_type": "taxi"}, "Вильнюс", "Каунас"),
        ({"ride_type": "transfer"}, "Аэропорт Вильнюса", "Паланга"),
        ({"ride_type": "transfer", "extras": ["flowers"]},
         "Вильнюс", "Каунас"),
        ({"ride_type": "transfer", "round_trip": True},
         "Вильнюс", "Клайпеда"),
        ({"ride_type": "transfer", "extras": ["jumpstart"]},
         "Вильнюс", "Аэропорт Вильнюса"),
    ]:
        quote = validated_details(request, origin=a, destination=b)
        assert quote["quoted_total_cents"] is None
        assert quote["quote_required"] is True

@pytest.mark.parametrize("bad", [
    {"quoted_total_cents": 1},
    {"payment_mode": "live"},
    {"extras": ["unknown"]},
    {"extras": ["meet_sign", "meet_sign"]},
    {"extras": "meet_sign"},
    {"round_trip": "yes"},
    {"ride_type": "luxury"},
    {"preferences": {"tracks": ["1", "2", "3", "4"]}},
    {"preferences": {"phone": "+37060000000"}},
    {"preferences": {"temperature": 30}},
])
def test_invalid_or_client_controlled_price_is_rejected(bad):
    with pytest.raises(ValueError):
        validated_details(bad, origin="Вильнюс", destination="Каунас")

def test_valid_comfort_details_with_no_extra_charge():
    q = validated_details({
        "ride_type": "transfer",
        "extras": ["music", "quiet_ride"],
        "preferences": {
            "radio": "M-1 · 106,8 FM",
            "tracks": ["first", "second", "third"],
            "temperature": 21,
            "wishes": "Без звонков",
        },
    }, origin="Вильнюс", destination="Аэропорт Вильнюса")
    assert q["quoted_total_cents"] == 4000
    assert q["preferences"]["temperature"] == 21
