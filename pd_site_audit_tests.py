"""Additional isolated registration, pilot and dispatcher checks. No live services."""
import io
import json
from PIL import Image


def run(server, core, client, call, signed, check):
    pilot, stranger, admin = 202, 203, 999
    check(call('/api/register', {'name': 'Test Pilot', 'phone': '+37060000001'}, uid=pilot), 200)
    check(call('/api/driver/work', uid=pilot), 401)
    application = dict(name='Test Pilot', phone='+37060000001', city='Vilnius',
                       vehicle='Toyota RAV4', vehicle_year=2020, plate='TEST123', seats=4)

    def photo(color, size=(1200, 800)):
        out = io.BytesIO()
        Image.new('RGB', size, color).save(out, format='JPEG')
        return out.getvalue()

    images = {side: photo(color) for side, color in zip(
        server.pd_onboarding.ACTIVE_SIDES, ('white', 'gray', 'red', 'green', 'blue'))}

    def apply(data=application, files=None):
        payload = {'application': json.dumps(data)}
        payload.update({side: (io.BytesIO(content), side+'.jpg')
                        for side, content in (images if files is None else files).items()})
        return client.post('/api/driver/application', data=payload, content_type='multipart/form-data',
                           headers={'X-Telegram-Init-Data': signed(pilot)})

    check(apply(files={}), 400)
    check(apply(data=application | {'phone': 'abc'}), 400)
    check(apply(files=images | {'license_front': photo('white', (100, 100))}), 400)
    duplicate = images | {key: images['car_front'] for key in ('car_rear', 'car_interior')}
    check(apply(files=duplicate), 400)
    assert not check(call('/api/me', uid=pilot), 200)['driver_application']
    check(apply(), 200)
    own = check(call('/api/me', uid=pilot), 200)
    assert own['driver_application']['status'] == 'pending' and not own['pilot_access']
    document = f'/api/driver/documents/{pilot}/license_front'
    assert call(document, uid=pilot).status_code == 200
    assert call(document, uid=admin).status_code == 200
    check(call(document, uid=stranger), 401)
    check(call(f'/api/admin/driver-applications/{pilot}/decision', {'status': 'approved'}, uid=pilot), 401)
    check(call(f'/api/admin/driver-applications/{pilot}/decision', {'status': 'approved'}, uid=admin), 200)
    assert check(call('/api/me', uid=pilot), 200)['pilot_access']
    assert not check(call('/api/me', uid=pilot), 200)['admin']
    print('PASS pilot application: invalid phone, missing/small/duplicate photos, atomic rejection, private documents, administrator approval and pilot-only access')

    # The order is a local fixture, never a request to a production database.
    departure = (core.now()+__import__('datetime').timedelta(days=3)).strftime('%d.%m.%Y')
    oid = core.order_save(101, dict(order_type='В одну сторону', origin='Vilnius',
        destination='Kaunas', trip_date=departure, trip_time='14:00', passengers=1,
        luggage='Без багажа', payment_method='Банковский перевод', details='TEST SITE AUDIT'))
    check(call(f'/api/admin/pilot-assignments/{oid}', {'pilot_id': pilot}, uid=101), 401)
    check(call(f'/api/admin/pilot-assignments/{oid}', {'pilot_id': stranger}, uid=admin), 400)
    check(call(f'/api/admin/pilot-assignments/{oid}', {'pilot_id': pilot}, uid=admin), 200)
    assert any(o['id'] == oid for o in check(call('/api/driver/work', uid=pilot), 200)['orders'])
    console = f'/api/admin/console/orders/{oid}'
    data = check(call(console, uid=admin), 200)
    change = {'changes': {'admin_note': 'Test note'}, 'reason': 'Offline regression test', 'revision': data['revision']}
    check(call(console, change, uid=101), 401)
    check(call(console, change, uid=admin), 200)
    check(call(console, change, uid=admin), 409)
    updated = check(call(console, uid=admin), 200)
    assert updated['admin_note'] == 'Test note' and updated['audit']
    assert check(call('/api/admin/console/orders?status=unassigned', uid=admin), 200)['orders'] is not None
    from pd_trip_runtime_v4 import waiting_cents
    assert waiting_cents(1000, 1000, 1300) == 0
    assert waiting_cents(1000, 1000, 1301) == 25
    assert waiting_cents(1000, None, 2000) == 0
    print('PASS dispatcher: approved-pilot assignment, role checks, work list, order detail, revision conflict, audit and filters; pickup waiting boundary at five minutes')
