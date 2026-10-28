"""Immutable invoice PDFs with explicit administrator-confirmed tax details."""
import hashlib
import io
import json
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from flask import jsonify, request, send_file
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

CENT = Decimal('0.01')

def text(value, limit=300):
    result = ' '.join(str(value or '').split())
    if len(result) > limit:
        raise ValueError('Слишком длинное значение поля')
    return result

def totals(gross, mode, rate=''):
    try:
        amount = Decimal(str(gross).replace(',', '.'))
        tax_rate = Decimal('21') if mode == 'standard21' else Decimal('0') if mode == 'svs' else Decimal(str(rate))
        if mode not in ('standard21', 'svs', 'manual') or not amount.is_finite() or amount <= 0 or amount != amount.quantize(CENT):
            raise ValueError()
        if not tax_rate.is_finite() or not 0 <= tax_rate <= 100:
            raise ValueError()
    except (ValueError, InvalidOperation):
        raise ValueError('Проверьте сумму и режим PVM')
    net = (amount / (1 + tax_rate / 100)).quantize(CENT, rounding=ROUND_HALF_UP)
    return {'gross': format(amount, '.2f'), 'net': format(net, '.2f'), 'vat': format(amount-net, '.2f'), 'rate': str(tax_rate)}

def render_pdf(meta):
    if 'PDInvoiceRegular' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('PDInvoiceRegular', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('PDInvoiceBold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
    normal = ParagraphStyle('PDInvoiceBody', fontName='PDInvoiceRegular', fontSize=9, leading=14, spaceAfter=5)
    title = ParagraphStyle('PDInvoiceTitle', parent=normal, fontName='PDInvoiceBold', fontSize=18, leading=24, spaceAfter=12)
    bold = ParagraphStyle('PDInvoiceHeading', parent=normal, fontName='PDInvoiceBold')
    def p(value, style=normal):
        return Paragraph(escape(str(value or '-')), style)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(595,842), leftMargin=45,rightMargin=45,topMargin=42,bottomMargin=42)
    seller, buyer, money = meta['seller'], meta['buyer'], meta['amounts']
    flow = [p('PRIVATE DRIVE',title),p('PVM SĄSKAITA FAKTŪRA / VAT INVOICE',bold),p(meta['serial'],bold),p('Išrašymo data / Issue date: '+meta['issued_at'][:10]),Spacer(1,10),p('PARDAVĖJAS / SELLER',bold),p(seller['seller_name']),p(seller['seller_address']),p('PVM kodas / VAT ID: '+seller['seller_vat']),p('Individualios veiklos pažymos Nr.: '+seller['seller_iv']),p('eurobaltictransfer@gmail.com | Telegram @PrivatDraiv'),Spacer(1,10),p('PIRKĖJAS / BUYER',bold),p(buyer['name']),p(buyer['address'])]
    if buyer['code']: flow.append(p('Įmonės kodas / Company code: '+buyer['code']))
    if buyer['vat']: flow.append(p('PVM kodas / VAT ID: '+buyer['vat']))
    flow += [Spacer(1,10),p('Paslaugos data / Service date: '+meta['service_date']),p('Užsakymas / Order: '+str(meta['order_id'])),p('Maršrutas / Route: '+meta['origin']+' → '+meta['destination']),Spacer(1,12)]
    data=[[p('Paslauga / Service',bold),p('Kiekis',bold),p('Be PVM, EUR',bold)],[p('Keleivių pervežimo paslauga / Passenger transfer'),p('1'),p(money['net'])]]
    table=Table(data,colWidths=[325,55,125],hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EEE3CC')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),('LINEBELOW',(0,-1),(-1,-1),0.5,colors.HexColor('#B7A275'))]))
    flow += [table,Spacer(1,14),p('Suma be PVM / Net: '+money['net']+' EUR',bold)]
    if seller['tax_mode']!='svs':
        flow.append(p('PVM / VAT '+money['rate']+'%: '+money['vat']+' EUR'))
    if seller['tax_basis']: flow.append(p(seller['tax_basis']))
    flow += [p('IŠ VISO / TOTAL: '+money['gross']+' EUR',title),p('Mokėjimo būdas / Payment method: '+meta['payment_method']),p('Dokumentas pats savaime nepatvirtina mokėjimo. / This document is not proof of payment.')]
    def footer(canvas, document):
        canvas.setFont('PDInvoiceRegular',8)
        canvas.setFillColor(colors.HexColor('#666666'))
        canvas.drawString(45,25,'PRIVATE DRIVE | '+meta['serial'])
        canvas.drawRightString(550,25,str(document.page))
    doc.build(flow,onFirstPage=footer,onLaterPages=footer)
    return buf.getvalue()

def register(app, core, auth):
    def admin():
        uid,_=auth()
        if not core.is_admin(uid): raise PermissionError('Нет доступа')
        return uid

    def schema(conn):
        conn.execute('''CREATE TABLE IF NOT EXISTS pd_invoices (
            invoice_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL UNIQUE,
            invoice_year INTEGER NOT NULL, invoice_number INTEGER NOT NULL, serial TEXT NOT NULL UNIQUE,
            issued_at TEXT NOT NULL, seller_name TEXT NOT NULL, seller_address TEXT NOT NULL,
            seller_iv_code TEXT NOT NULL, buyer_name TEXT NOT NULL, buyer_code TEXT NOT NULL,
            service_date TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL,
            total_eur TEXT NOT NULL, payment_method TEXT NOT NULL, UNIQUE(invoice_year,invoice_number))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS pd_invoice_files (
            order_id INTEGER PRIMARY KEY,serial TEXT NOT NULL UNIQUE,pdf BLOB NOT NULL,
            sha256 TEXT NOT NULL,snapshot TEXT NOT NULL,created_at TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS pd_invoice_settings (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),data TEXT NOT NULL,updated_at TEXT NOT NULL,admin_id INTEGER NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS pd_invoice_settings_history (
            id INTEGER PRIMARY KEY,old_data TEXT,new_data TEXT NOT NULL,changed_at TEXT NOT NULL,admin_id INTEGER NOT NULL)''')

    def defaults():
        return dict(seller_name=os.getenv('PD_SELLER_NAME','Yauheni Ivantsou'),seller_address=os.getenv('PD_SELLER_ADDRESS',''),seller_iv=os.getenv('PD_SELLER_IV_NUMBER','1374775'),seller_vat='LT100018960214',tax_mode='',tax_rate='',tax_basis='')

    def settings(conn):
        row=conn.execute('SELECT data FROM pd_invoice_settings WHERE singleton=1').fetchone()
        return json.loads(row['data']) if row else defaults()

    def validate_settings(body):
        result={key:text(body.get(key),500 if key=='tax_basis' else 300) for key in defaults()}
        if len(result['seller_name'])<5 or len(result['seller_address'])<8 or not result['seller_iv'] or not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{6,15}',result['seller_vat']):
            raise ValueError('Заполните имя, полный адрес, номер деятельности и PVM-код продавца')
        totals('1.00',result['tax_mode'],result['tax_rate'])
        if result['tax_mode']=='svs': result['tax_basis']='PVM neskaičiuojamas: taikoma smulkiojo verslo schema Lietuvoje (SVS).'
        if result['tax_mode']=='manual' and len(result['tax_basis'])<10:
            raise ValueError('Укажите основание выбранной ставки PVM')
        return result

    @app.route('/api/admin/invoice-settings',methods=['GET','POST'])
    def pd_invoice_settings_v2():
        uid=admin()
        with core.db(core.ORDERS_DB) as conn:
            schema(conn)
            if request.method=='GET': return jsonify(settings=settings(conn))
            body=request.get_json(silent=True) or {}
            if body.get('confirmed') is not True: raise ValueError('Подтвердите актуальность реквизитов и режима PVM')
            value=validate_settings(body)
            old=settings(conn)
            now=core.now().isoformat()
            packed=json.dumps(value,ensure_ascii=False)
            conn.execute('INSERT INTO pd_invoice_settings_history(old_data,new_data,changed_at,admin_id) VALUES(?,?,?,?)',(json.dumps(old,ensure_ascii=False),packed,now,uid))
            conn.execute('INSERT INTO pd_invoice_settings(singleton,data,updated_at,admin_id) VALUES(1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at,admin_id=excluded.admin_id',(packed,now,uid))
        return jsonify(ok=True)

    def issue_invoice_v2(oid):
        uid=admin()
        body=request.get_json(silent=True) or {}
        with core.db(core.ORDERS_DB) as conn:
            conn.execute('BEGIN IMMEDIATE');schema(conn)
            existing=conn.execute('SELECT serial FROM pd_invoice_files WHERE order_id=?',(oid,)).fetchone()
            if existing:return jsonify(ok=True,number=existing['serial'],existing=True)
            if body.get('tax_confirmed') is not True:raise ValueError('Подтвердите применимость режима PVM для этой поездки')
            seller=validate_settings(settings(conn))
            order=conn.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
            if not order or order['status']!='Выполнена':raise ValueError('Счёт выпускается после завершения поездки')
            if conn.execute('SELECT 1 FROM pd_invoices WHERE order_id=?',(oid,)).fetchone():raise ValueError('Старый счёт уже существует. Автоматическая замена запрещена.')
            buyer=dict(name=text(body.get('buyer_name'),150),address=text(body.get('buyer_address')),code=text(body.get('buyer_code'),50),vat=text(body.get('buyer_vat'),40))
            if len(buyer['name'])<2 or len(buyer['address'])<8:raise ValueError('Укажите имя или название и полный адрес покупателя для PVM-счёта')
            amounts=totals(order['price'],seller['tax_mode'],seller['tax_rate'])
            now=core.now();year=now.year
            number=conn.execute('SELECT COALESCE(MAX(invoice_number),0)+1 FROM pd_invoices WHERE invoice_year=?',(year,)).fetchone()[0]
            serial=f'PD-{year}-{number:05d}'
            meta=dict(order_id=oid,serial=serial,issued_at=now.isoformat(),seller=seller,buyer=buyer,amounts=amounts,service_date=order['trip_date'],origin=order['origin'],destination=order['destination'],payment_method=order['payment_method'],issued_by=uid)
            pdf=render_pdf(meta)
            conn.execute('''INSERT INTO pd_invoices(order_id,invoice_year,invoice_number,serial,issued_at,seller_name,seller_address,seller_iv_code,buyer_name,buyer_code,service_date,origin,destination,total_eur,payment_method) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(oid,year,number,serial,meta['issued_at'],seller['seller_name'],seller['seller_address'],seller['seller_iv'],buyer['name'],buyer['code'],meta['service_date'],meta['origin'],meta['destination'],amounts['gross'],meta['payment_method']))
            conn.execute('INSERT INTO pd_invoice_files(order_id,serial,pdf,sha256,snapshot,created_at) VALUES(?,?,?,?,?,?)',(oid,serial,pdf,hashlib.sha256(pdf).hexdigest(),json.dumps(meta,ensure_ascii=False),meta['issued_at']))
        return jsonify(ok=True,number=serial,existing=False)

    def invoice_bytes(oid):
        uid,_=auth()
        with core.db(core.ORDERS_DB) as conn:
            schema(conn)
            order=conn.execute('SELECT telegram_id FROM orders WHERE id=?',(oid,)).fetchone()
            if not order or (order['telegram_id']!=uid and not core.is_admin(uid)):raise PermissionError('Нет доступа')
            row=conn.execute('SELECT serial,pdf,sha256 FROM pd_invoice_files WHERE order_id=?',(oid,)).fetchone()
        if not row:raise ValueError('Счёт ещё не выпущен администратором')
        pdf=bytes(row['pdf'])
        if hashlib.sha256(pdf).hexdigest()!=row['sha256']:raise ValueError('Проверка целостности PDF не пройдена')
        return pdf,row['serial']

    @app.get('/api/invoices/<int:oid>/pdf')
    def pd_passenger_invoice_v2(oid):
        pdf,serial=invoice_bytes(oid)
        response=send_file(io.BytesIO(pdf),mimetype='application/pdf',as_attachment=True,download_name=f'PRIVATE_DRIVE_{serial}.pdf',max_age=0)
        response.headers['Cache-Control']='private, no-store'
        return response

    @app.get('/api/invoices')
    def pd_passenger_invoices_v2():
        uid,_=auth()
        with core.db(core.ORDERS_DB) as conn:
            schema(conn)
            rows=conn.execute('SELECT f.order_id,f.serial,f.created_at FROM pd_invoice_files f JOIN orders o ON o.id=f.order_id WHERE o.telegram_id=? ORDER BY f.created_at DESC LIMIT 200',(uid,)).fetchall()
        response=jsonify(invoices=[dict(row) for row in rows]);response.headers['Cache-Control']='private, no-store';return response

    def send_invoice_v2(oid):
        admin();pdf,serial=invoice_bytes(oid)
        order=core.order_find(oid)
        document=io.BytesIO(pdf);document.name=f'PRIVATE_DRIVE_{serial}.pdf'
        core.bot.send_document(order['telegram_id'],document,caption=f'PRIVATE DRIVE · PVM sąskaita faktūra {serial}')
        return jsonify(ok=True,number=serial)

    def archive_v2():
        admin()
        with core.db(core.ORDERS_DB) as conn:
            schema(conn)
            rows=conn.execute('SELECT i.order_id,i.serial,i.issued_at,i.buyer_name,i.total_eur,i.payment_method,o.payment_status,CASE WHEN f.order_id IS NULL THEN 0 ELSE 1 END AS has_pdf FROM pd_invoices i LEFT JOIN orders o ON o.id=i.order_id LEFT JOIN pd_invoice_files f ON f.order_id=i.order_id ORDER BY i.invoice_id DESC LIMIT 200').fetchall()
        return jsonify(invoices=[dict(row) for row in rows])

    app.view_functions['issue_invoice']=issue_invoice_v2
    app.view_functions['invoice_pdf']=pd_passenger_invoice_v2
    app.view_functions['send_invoice']=send_invoice_v2
    app.view_functions['invoice_archive_pd']=archive_v2

    @app.get('/assets/pd-invoice-v2.js')
    def pd_invoice_script_v2():
        return send_file(Path(__file__).with_suffix('.js'),mimetype='text/javascript',max_age=0)
