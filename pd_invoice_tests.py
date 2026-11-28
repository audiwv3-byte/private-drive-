"""Isolated invoice configuration, ownership and immutable PDF checks."""
import hashlib,json
from datetime import timedelta
from unittest.mock import patch

def run(server,core,call,check):
    import pd_invoice_v2 as inv
    assert inv.totals('121.00','standard21')['vat']=='21.00'
    assert inv.totals('100.00','svs')['vat']=='0.00'
    for invalid in [('NaN','svs',''),('100','manual','NaN'),('100','invalid','0')]:
        try:inv.totals(*invalid)
        except ValueError:pass
        else:raise AssertionError('Invalid tax input accepted')
    check(call('/api/admin/invoice-settings',uid=101),401)
    check(call('/api/admin/invoice-settings',{},uid=999),400)
    seller=dict(seller_name='TEST PRIVATE DRIVE',seller_address='Test address 1, Vilnius, Lietuva',seller_iv='TEST',seller_vat='LT000000000',tax_mode='svs',tax_rate='',tax_basis='',confirmed=True)
    check(call('/api/admin/invoice-settings',seller,uid=999),200)
    with core.db(core.ORDERS_DB) as c:
        order=c.execute("SELECT id,telegram_id FROM orders WHERE status='Выполнена' AND telegram_id=101 ORDER BY id LIMIT 1").fetchone()
    oid=order['id']
    check(call(f'/api/admin/invoices/{oid}',{'buyer_name':'Test Buyer','buyer_address':'Test address 2, Kaunas'},uid=999),400)
    payload=dict(tax_confirmed=True,buyer_name='Тестовый пассажир / Živilė Ąžuolaitė',buyer_address='Test address 2, Kaunas, Lietuva',buyer_code='',buyer_vat='')
    first=check(call(f'/api/admin/invoices/{oid}',payload,uid=999),200)
    repeat=check(call(f'/api/admin/invoices/{oid}',payload,uid=999),200)
    assert repeat['existing'] and first['number']==repeat['number']
    pdf=call(f'/api/invoices/{oid}/pdf',uid=101)
    assert pdf.status_code==200 and pdf.data.startswith(b'%PDF-')
    with core.db(core.ORDERS_DB) as c:
        saved=c.execute('SELECT pdf,sha256,snapshot FROM pd_invoice_files WHERE order_id=?',(oid,)).fetchone()
        assert hashlib.sha256(pdf.data).hexdigest()==saved['sha256']
        assert json.loads(saved['snapshot'])['seller']['tax_mode']=='svs'
    check(call(f'/api/invoices/{oid}/pdf',uid=103),401)
    invoices=check(call('/api/invoices',uid=101),200)['invoices'];assert any(x['order_id']==oid for x in invoices)
    print('PASS invoices: explicit tax confirmation, totals, immutable PDF and number, Unicode, owner/admin access and passenger archive')
    check_booking_prices(server, core, call, check)


def check_booking_prices(server, core, call, check):
    from pd_crypto_manual import total_with_crypto_surcharge

    assert total_with_crypto_surcharge(10010) == 11512
    booking = dict(origin='Vilnius', destination='Trakai',
                   trip_date=(core.now()+timedelta(days=2)).strftime('%d.%m.%Y'),
                   trip_time='14:00', passengers=2, luggage='Без багажа')
    quote = {'properties': {'summary': {'distance': 50000, 'duration': 2700}},
             'geometry': {'coordinates': []}}
    with (patch.object(core, 'quote', return_value='100.00'),
          patch.object(core, 'route', return_value=(50, 45)),
          patch.object(server.pd_stops, 'directions', return_value=(quote, [25, 54], [24, 54])),
          patch.dict(core.CRYPTO_ADDRESSES, {'ETH': '0x' + 'a' * 40})):
        route = check(call('/api/route', booking), 200)
        assert route['base_price'] == route['price'] == '100.00'
        for method, price, key in (
            ('Банковский перевод', '100.00', 'qa_normal_price_20261128'),
            ('Криптовалюта', '115.00', 'qa_crypto_price_20261128'),
        ):
            data = booking | dict(payment_method=method, request_key=key, quoted_price=price)
            check(call('/api/order', data | {'quoted_price': '99.00'}), 409)
            created = check(call('/api/order', data), 200)
            oid = created['order_id']
            repeat = check(call('/api/order', data), 200)
            assert repeat['replayed'] and repeat['order_id'] == oid
            assert created['price'] == repeat['price'] == price
            queue = check(call('/api/admin/console/orders', uid=999), 200)['orders']
            assert next(o for o in queue if o['id'] == oid)['price'] == price
            check(call('/api/admin/status', {'id': oid, 'status': 'Подтверждена'}, uid=999), 200)
            if method == 'Криптовалюта':
                check(call(f'/api/payment/{oid}/bank', {}), 400)
                check(call(f'/api/payment/{oid}/cash', {}), 400)
                path = f'/api/admin/crypto-payment/{oid}'
                assert check(call(path, uid=999), 200)['price'] == price
                instructions = {'currency': 'ETH', 'amount': '0.05'}
                check(call(path, instructions, uid=999), 200)
                assert check(call(path, instructions, uid=999), 200)['replayed']
                assert check(call(path, uid=999), 200)['payment']['price_cents'] == 11500
                txid = '0x' + 'b' * 64
                check(call(f'/api/payment/{oid}/crypto/claimed', {'txid': txid}), 200)
                check(call(f'{path}/received', instructions | {'txid': txid, 'verified_on_chain': True}, uid=999), 200)
            else:
                assert check(call(f'/api/payment/{oid}/bank', {}), 200)['amount'] == price
                check(call(f'/api/admin/bank-transfers/{oid}/received',
                           {'amount': price, 'verified_in_bank': True}, uid=999), 200)
            assert check(call(f'/api/payment/{oid}'), 200)['price'] == price
            for status in ('В пути', 'Выполнена'):
                check(call('/api/admin/status', {'id': oid, 'status': status}, uid=999), 200)
            check(call(f'/api/admin/invoices/{oid}', dict(tax_confirmed=True, buyer_name='QA Buyer',
                       buyer_address='Synthetic address 2, Vilnius'), uid=999), 200)
            archive = check(call('/api/invoices'), 200)['invoices']
            assert any(i['order_id'] == oid for i in archive)
            pdf = call(f'/api/invoices/{oid}/pdf')
            assert pdf.status_code == 200 and pdf.data.startswith(b'%PDF-')
            with core.db(core.ORDERS_DB) as conn:
                invoice = conn.execute('SELECT snapshot, sha256 FROM pd_invoice_files WHERE order_id=?',
                                       (oid,)).fetchone()
            snapshot = json.loads(invoice['snapshot'])
            assert snapshot['amounts']['gross'] == price and snapshot['payment_method'] == method
            assert hashlib.sha256(pdf.data).hexdigest() == invoice['sha256']
    print('PASS Mini App order price: bank 100.00 EUR, crypto 115.00 EUR, dispatcher, payment and invoice agree')
