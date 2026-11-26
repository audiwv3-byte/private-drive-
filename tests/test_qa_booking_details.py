"""QA assertion: booking detail fields remain strictly typed and safe in UI."""
from pathlib import Path
import pytest
from pd_qa_order_details import normalize_details

ROOT = Path(__file__).resolve().parents[1]


def test_payment_free_validation_contract():
    details = normalize_details({
        "ride_type": "Трансфер", "tariff": "Вильнюс – Каунас",
        "extras": ["Встреча с табличкой", "Вода"],
        "wishes": "Температура 21 °C", "fare_preview_eur": 110,
        "preferences": {"radio": "M-1", "tracks": ["Track A"], "temperature": 21},
        "round_trip": True, "advance_booking": True
    })
    assert details["fare_preview_eur"] == 110
    assert details["preferences"]["temperature"] == 21
    assert normalize_details(None) == {}
    for invalid in [
        {"payment_method": "card"},
        {"payment_token": "fake"},
        {"extras": "not-array"},
        {"extras": ["x"] * 31},
        {"wishes": "x" * 1001},
        {"passengers": 0},
        {"passengers": True},
        {"fare_preview_eur": -1},
        {"preferences": {"tracks": ["a"] * 6}},
    ]:
        with pytest.raises(ValueError):
            normalize_details(invalid)


def test_dispatcher_map_renders_details_as_plain_text():
    page = (ROOT / "pd_dispatcher_mapbox.html").read_text()
    start = page.index("const details=order.booking_details||{}")
    end = page.index("{% if order_gps_enabled %}", start)
    snippet = page[start:end]
    assert "notes.textContent=fields.join" in snippet
    assert "notes.innerHTML" not in snippet
    for field in ("extras", "wishes", "tariff", "ride_type",
                  "round_trip", "advance_booking", "fare_preview_eur",
                  "preferences", "luggage", "passengers"):
        assert "details." + field in snippet
    assert "не оплачено" in snippet
