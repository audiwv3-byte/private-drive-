"""Детерминированная серверная стоимость дополнительных услуг PRIVATE DRIVE."""
from decimal import Decimal, ROUND_HALF_UP

MEETING = "Встреча с табличкой"
SOBER = "Трезвый водитель"
PET = "Перевозка животного"
MEETING_FEE = Decimal("20.00")
PET_RATE = Decimal("0.10")


def breakdown(base_price, data):
    """Дважды базовый тариф за услугу «Трезвый водитель», встреча +20 €.

    Доплата за питомца равна 10% от базового маршрута (без удвоения).
    Все надбавки рассчитываются сервером; значения цен из клиента игнорируются.
    """
    if not isinstance(data, dict):
        raise ValueError("Некорректный заказ")
    extras = data.get("extras", [])
    if not isinstance(extras, list) or len(extras) > 10 or any(
        not isinstance(x, str) or len(x) > 100 for x in extras
    ):
        raise ValueError("Некорректные дополнительные услуги")
    base = Decimal(str(base_price).replace(",", "."))
    if not base.is_finite() or base < 0:
        raise ValueError("Некорректная базовая цена")
    pet = base * PET_RATE if PET in extras else Decimal("0")
    sober = base if SOBER in extras else Decimal("0")
    meeting = MEETING_FEE if MEETING in extras else Decimal("0")
    q = lambda x: x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "base": format(q(base), ".2f"),
        "pet": format(q(pet), ".2f"),
        "sober": format(q(sober), ".2f"),
        "meeting": format(q(meeting), ".2f"),
        "total": format(q(base + pet + sober + meeting), ".2f"),
    }
