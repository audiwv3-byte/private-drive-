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


def register(app, core, auth):
    from flask import jsonify, request

    with core.db(core.ORDERS_DB) as db:
        initialize(db)

    @app.post('/api/preorders/<int:order_id>/choose')
    def accept_passenger_offer(order_id):
        passenger_id, _ = auth()
        selection = request.get_json(silent=True)
        if not isinstance(selection, dict):
            raise ValueError('Выберите предложение')
        pilot_id = selection.get('pilot_id')
        expected = selection.get('cents')
        if type(pilot_id) is not int or type(expected) is not int or expected <= 0:
            raise ValueError('Выберите предложение с указанной ценой')
        cents = finalize_selection(core, order_id, passenger_id, pilot_id, expected)
        return jsonify(order_id=order_id, pilot_id=pilot_id, cents=cents)


def finalize_selection(core, order_id, passenger_id, pilot_id, expected):
    with core.db(core.ORDERS_DB) as db:
        db.execute('ATTACH DATABASE ? AS pilot_users', (str(core.USERS_DB),))
        db.execute('BEGIN IMMEDIATE')
        order = db.execute('SELECT * FROM orders WHERE id=? AND telegram_id=?',
                           (order_id, passenger_id)).fetchone()
        if not order:
            raise PermissionError('Нет доступа к заказу')
        cents, changed = choose_offer(db, order_id, passenger_id, pilot_id)
        if cents != expected:
            raise ValueError('Цена изменилась. Обновите предложения.')
        if changed:
            if (order['status'] != 'Новая' or order['payment_status'] not in ('', 'Не оплачено')
                    or order['stripe_session_id'] or order['card_payment_url']):
                raise ValueError('Заказ больше недоступен для выбора цены')
            approved = db.execute("""SELECT 1 FROM pilot_users.pd_driver_applications
                WHERE telegram_id=? AND status='approved'""", (pilot_id,)).fetchone()
            if not approved:
                raise ValueError('Пилот недоступен')
            assigned = db.execute('SELECT 1 FROM pd_pilot_assignments WHERE order_id=?',
                                  (order_id,)).fetchone()
            if assigned:
                raise ValueError('Пилот уже назначен. Обновите заказ.')
            stamp = core.now().isoformat()
            db.execute("""INSERT INTO pd_pilot_assignments
                (order_id,pilot_id,assigned_by,assigned_at) VALUES(?,?,?,?)""",
                (order_id, pilot_id, passenger_id, stamp))
            fare = f'{cents // 100}.{cents % 100:02d}'
            db.execute("""UPDATE orders SET price=?, status='Подтверждена',
                quote_status='Согласовано пассажиром', updated_at=? WHERE id=?""",
                (fare, stamp, order_id))
    return cents
