"""Isolated invoice configuration, ownership and immutable PDF checks."""
import hashlib,json

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
