"""PRIVATE DRIVE: non-PVM Lithuanian invoice extension. No automatic issuance."""
import io, os, sqlite3, re
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from flask import jsonify, request, send_file
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.enums import TA_RIGHT
from xml.sax.saxutils import escape

FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

def register(app, core, auth):
    pdfmetrics.registerFont(TTFont('PDText', FONT))
    pdfmetrics.registerFont(TTFont('PDTextBold', BOLD))

    def check_admin():
        uid,_=auth()
        if not core.is_admin(uid):
            raise PermissionError('Нет доступа')
        return uid

    def ensure_schema(conn):
        conn.execute('''CREATE TABLE IF NOT EXISTS pd_invoices (
           invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
           order_id INTEGER NOT NULL UNIQUE,
           invoice_year INTEGER NOT NULL,
           invoice_number INTEGER NOT NULL,
           serial TEXT NOT NULL UNIQUE,
           issued_at TEXT NOT NULL,
           seller_name TEXT NOT NULL, seller_address TEXT NOT NULL,
           seller_iv_code TEXT NOT NULL,
           buyer_name TEXT NOT NULL, buyer_code TEXT NOT NULL,
           service_date TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL,
           total_eur TEXT NOT NULL, payment_method TEXT NOT NULL,
           UNIQUE(invoice_year,invoice_number))''')

    def seller_settings():
        name=os.getenv('PD_SELLER_NAME','').strip()
        if len(name)<5 or name.lower().startswith('укажите'):
            raise ValueError('Укажите PD_SELLER_NAME (имя и фамилию продавца) в .env')
        return (name,os.getenv('PD_SELLER_ADDRESS','').strip(),os.getenv('PD_SELLER_IV_NUMBER','').strip())

    @app.post('/api/admin/invoices/<int:oid>')
    def issue_invoice(oid):
        check_admin()
        raise ValueError('Выпуск счетов временно отключён до проверки PVM/SVS. Архив доступен для просмотра.')
        data=request.get_json(silent=True) or {}
        seller_name, seller_address, iv_code=seller_settings()
        buyer_name=' '.join(str(data.get('buyer_name','')).split())
        buyer_code=' '.join(str(data.get('buyer_code','')).split())
        if len(buyer_name)>150 or len(buyer_code)>50:
            raise ValueError('Слишком длинные реквизиты покупателя')
        if buyer_code and not buyer_name:
            raise ValueError('Для кода покупателя укажите название покупателя')
        with core.db(core.ORDERS_DB) as conn:
            conn.execute('BEGIN IMMEDIATE')
            ensure_schema(conn)
            existing=conn.execute('SELECT serial FROM pd_invoices WHERE order_id=?',(oid,)).fetchone()
            if existing: return jsonify(ok=True,number=existing['serial'],existing=True)
            order=conn.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
            if not order: raise ValueError('Заказ не найден')
            if order['status']!='Выполнена': raise ValueError('Счёт можно выпустить после оказания услуги')
            try:
                amount=Decimal(str(order['price']).replace(',','.'))
                if not amount.is_finite() or amount<=0 or amount!=amount.quantize(Decimal('.01')): raise ValueError()
            except (InvalidOperation,ValueError):
                raise ValueError('Перед выдачей счёта установите корректную цену EUR')
            if not buyer_name:
                user=core.user_record(order['telegram_id'])
                buyer_name=user['name'] if user else 'Pirkėjas nenurodytas'
            moment=core.now()
            year=moment.year
            last=conn.execute('SELECT COALESCE(MAX(invoice_number),0) FROM pd_invoices WHERE invoice_year=?',(year,)).fetchone()[0]
            serial=f'PD-{year}-{last+1:05d}'
            conn.execute('''INSERT INTO pd_invoices
              (order_id,invoice_year,invoice_number,serial,issued_at,seller_name,seller_address,seller_iv_code,
               buyer_name,buyer_code,service_date,origin,destination,total_eur,payment_method)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
               (oid,year,last+1,serial,moment.isoformat(),seller_name,seller_address,iv_code,
                buyer_name,buyer_code,order['trip_date'],order['origin'],order['destination'],
                f'{amount:.2f}',order['payment_method']))
        return jsonify(ok=True,number=serial,existing=False)

    @app.get('/api/admin/invoices/<int:oid>/pdf')
    def invoice_pdf(oid):
        check_admin()
        raise ValueError('Скачивание PDF временно отключено: шаблон PVM/SVS требует исправления.')
        with core.db(core.ORDERS_DB) as conn:
            ensure_schema(conn)
            r=conn.execute('SELECT * FROM pd_invoices WHERE order_id=?',(oid,)).fetchone()
        if r is None: raise ValueError('Сначала выпустите счёт-фактуру')
        def p(t): return escape(str(t or '—'))
        style=getSampleStyleSheet()
        normal=ParagraphStyle('PDNormal',parent=style['Normal'],fontName='PDText',fontSize=9,leading=15,spaceAfter=6)
        heading=ParagraphStyle('PDHeading',parent=normal,fontName='PDTextBold',fontSize=17,leading=24,spaceAfter=16)
        bold=ParagraphStyle('PDBold',parent=normal,fontName='PDTextBold')
        buf=io.BytesIO()
        doc=SimpleDocTemplate(buf,pagesize=(595,842),leftMargin=45,rightMargin=45,topMargin=50,bottomMargin=50)
        txt=[Paragraph('PRIVATE DRIVE',heading),Paragraph('SĄSKAITA FAKTŪRA',heading),
             Paragraph('Serija ir Nr.: '+p(r['serial']),bold),Paragraph('Išrašymo data: '+p(r['issued_at'][:10]),normal),
             Spacer(1,12),Paragraph('PARDAVĖJAS',bold),Paragraph(p(r['seller_name']),normal)]
        if r['seller_address']: txt.append(Paragraph('Adresas: '+p(r['seller_address']),normal))
        if r['seller_iv_code']: txt.append(Paragraph('Individualios veiklos pažymos Nr.: '+p(r['seller_iv_code']),normal))
        txt.extend([Spacer(1,8),Paragraph('PIRKĖJAS',bold),Paragraph(p(r['buyer_name']),normal)])
        if r['buyer_code']: txt.append(Paragraph('Įmonės kodas / ID: '+p(r['buyer_code']),normal))
        txt.extend([Spacer(1,15),Paragraph('Paslaugos suteikimo data: '+p(r['service_date']),normal),
                   Paragraph('Užsakymo Nr.: '+str(oid),normal)])
        data=[['Paslauga / Service','Kiekis','Suma, EUR'],
             [Paragraph('Keleivių pervežimo paslauga / Passenger transfer',normal),'1',p(r['total_eur'])]]
        tb=Table(data,colWidths=[345,55,100],hAlign='LEFT')
        tb.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'PDText'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E6D1A0')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10),
            ('LINEBELOW',(0,-1),(-1,-1),0.6,colors.grey)]))
        txt.extend([Spacer(1,12),tb,Spacer(1,12),Paragraph('IŠ VISO: '+p(r['total_eur'])+' EUR',bold),
             Paragraph('PVM neišskiriamas. Pardavėjas nėra PVM mokėtojas.',normal),
             Paragraph('Maršrutas: '+p(r['origin'])+' → '+p(r['destination']),normal),
             Paragraph('Apmokėjimo būdas: '+p(r['payment_method']),normal)])
        doc.build(txt)
        buf.seek(0)
        return send_file(buf,mimetype='application/pdf',as_attachment=True,download_name=f"PRIVATE_DRIVE_{r['serial']}.pdf")

    @app.post('/api/admin/invoices/<int:oid>/send')
    def send_invoice(oid):
        check_admin()
        raise ValueError('Отправка PDF временно отключена до проверки PVM/SVS.')
        with core.db(core.ORDERS_DB) as conn:
            ensure_schema(conn)
            doc=conn.execute('SELECT serial FROM pd_invoices WHERE order_id=?',(oid,)).fetchone()
            order=conn.execute('SELECT telegram_id FROM orders WHERE id=?',(oid,)).fetchone()
        if not doc or not order: raise ValueError('Счёт не найден')
        # Use current PDF endpoint under application context; no user-supplied URL
        with app.test_request_context(f'/api/admin/invoices/{oid}/pdf', headers={'X-Telegram-Init-Data': request.headers.get('X-Telegram-Init-Data','')}):
            response=invoice_pdf(oid)
        pdf=response.get_data() if hasattr(response,'get_data') else response.response.read()
        output=io.BytesIO(pdf); output.name=f"PRIVATE_DRIVE_{doc['serial']}.pdf"
        core.bot.send_document(order['telegram_id'],output,caption=f"PRIVATE DRIVE · Sąskaita faktūra {doc['serial']}")
        return jsonify(ok=True,number=doc['serial'])

    @app.get('/api/admin/finance/summary')
    def finance_summary_pd():
        check_admin()
        paid = Decimal('0.00')
        unpaid = Decimal('0.00')
        paid_count = unpaid_count = 0
        with core.db(core.ORDERS_DB) as conn:
            orders = conn.execute('SELECT price,payment_status FROM orders').fetchall()
        for order in orders:
            try:
                value = Decimal(str(order['price']).replace(',', '.'))
                if not value.is_finite() or value < 0:
                    continue
            except (InvalidOperation, TypeError, ValueError):
                continue
            if order['payment_status'] == 'Оплачено':
                paid += value
                paid_count += 1
            else:
                unpaid += value
                unpaid_count += 1
        return jsonify(paid_eur=f'{paid:.2f}', unpaid_eur=f'{unpaid:.2f}',
                       paid_count=paid_count, unpaid_count=unpaid_count,
                       note='По заказам PRIVATE DRIVE; не бухгалтерская выручка или сверка Stripe')

    @app.get('/api/admin/finance/invoices')
    def invoice_archive_pd():
        check_admin()
        with core.db(core.ORDERS_DB) as conn:
            ensure_schema(conn)
            rows = conn.execute("""SELECT i.order_id, i.serial, i.issued_at,
                                     i.buyer_name, i.total_eur, i.payment_method,
                                     o.payment_status
                              FROM pd_invoices i LEFT JOIN orders o ON o.id=i.order_id
                              ORDER BY i.invoice_id DESC LIMIT 200""").fetchall()
        return jsonify(invoices=[dict(row) for row in rows],
                       note='Архив ранее выпущенных документов. Налоговая корректность не подтверждена.')
