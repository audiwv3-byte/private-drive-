"""Closed offers for advance bookings. Call mutations inside the order write transaction."""
from datetime import timedelta
from zoneinfo import ZoneInfo

VILNIUS = ZoneInfo("Europe/Vilnius")


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS pd_preorders (
        order_id INTEGER PRIMARY KEY REFERENCES orders(id),
        passenger_id INTEGER NOT NULL, closes_at INTEGER NOT NULL,
        chosen_pilot INTEGER, chosen_cents INTEGER
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS pd_preorder_offers (
        order_id INTEGER NOT NULL REFERENCES pd_preorders(order_id),
        pilot_id INTEGER NOT NULL, cents INTEGER NOT NULL CHECK(cents > 0),
        PRIMARY KEY(order_id, pilot_id)
    )""")


def open_request(db, order_id, passenger_id, pickup, now):
    if pickup.tzinfo is None or now.tzinfo is None:
        raise ValueError("Timezone required")
    if pickup.astimezone(VILNIUS) < now.astimezone(VILNIUS) + timedelta(days=7):
        raise ValueError("До поездки должно оставаться не меньше недели")
    owner = db.execute("SELECT telegram_id FROM orders WHERE id=?", (order_id,)).fetchone()
    if owner is None or owner[0] != passenger_id:
        raise PermissionError("Нет доступа к заказу")
    db.execute("""INSERT INTO pd_preorders(order_id, passenger_id, closes_at)
        VALUES (?, ?, ?) ON CONFLICT(order_id) DO NOTHING""",
        (order_id, passenger_id, int(now.timestamp()) + 86400))


def submit_offer(db, order_id, pilot_id, cents, now):
    if type(cents) is not int or not 0 < cents <= 99999999:
        raise ValueError("Некорректная цена")
    result = db.execute("""INSERT INTO pd_preorder_offers(order_id, pilot_id, cents)
        SELECT order_id, ?, ? FROM pd_preorders WHERE order_id=? AND passenger_id<>?
        AND chosen_pilot IS NULL AND closes_at>?
        ON CONFLICT(order_id, pilot_id) DO UPDATE SET cents=excluded.cents""",
        (pilot_id, cents, order_id, pilot_id, int(now.timestamp())))
    if not result.rowcount:
        raise ValueError("Приём предложений закрыт")


def passenger_offers(db, order_id, passenger_id):
    return db.execute("""SELECT o.pilot_id, o.cents FROM pd_preorder_offers o
        JOIN pd_preorders p USING(order_id) WHERE o.order_id=? AND p.passenger_id=?
        ORDER BY o.cents, o.pilot_id""", (order_id, passenger_id)).fetchall()


def choose_offer(db, order_id, passenger_id, pilot_id):
    """Caller finalizes the dispatch assignment and fare in the same transaction."""
    result = db.execute("""UPDATE pd_preorders SET chosen_pilot=?, chosen_cents=(
        SELECT cents FROM pd_preorder_offers WHERE order_id=? AND pilot_id=?)
        WHERE order_id=? AND passenger_id=? AND chosen_pilot IS NULL
        AND EXISTS (SELECT 1 FROM pd_preorder_offers WHERE order_id=? AND pilot_id=?)""",
        (pilot_id, order_id, pilot_id, order_id, passenger_id, order_id, pilot_id))
    chosen = db.execute("""SELECT chosen_pilot, chosen_cents FROM pd_preorders
        WHERE order_id=? AND passenger_id=?""", (order_id, passenger_id)).fetchone()
    if chosen is None or chosen[0] != pilot_id:
        raise ValueError("Выбор предложения недоступен")
    return chosen[1], bool(result.rowcount)
