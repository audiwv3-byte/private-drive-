"""Passenger-owned invoice preview for the isolated native booking lab."""
import uuid
from decimal import Decimal
from json import dumps

from werkzeug.wrappers import Response

from pd_invoice_v2 import render_pdf, totals


def invoice_response(db, raw_id, user_id, environ, start_response):
    headers = {"Cache-Control": "private, no-store"}
    try:
        order_id = uuid.UUID(raw_id)
    except ValueError:
        return Response(status=404, headers=headers)(environ, start_response)
    row = db.execute("""
        SELECT o.origin, o.destination, o.trip_date, o.created_at,
               q.quoted_total_cents, q.details->>'payment_method'
        FROM public.pd_dispatch_orders o
        JOIN public.pd_native_order_owners n ON n.order_id=o.id
        JOIN public.pd_native_order_quotes q ON q.order_id=o.id
        WHERE o.id=%s AND n.user_id=%s AND NOT q.quote_required
              AND q.details ? 'payment_method'
    """, (order_id, user_id)).fetchone()
    if row is None:
        return Response(status=404, headers=headers)(environ, start_response)
    origin, destination, service_date, created, cents, payment = row
    if environ.get("HTTP_ACCEPT") == "application/json":
        body = dumps({"order_id": str(order_id), "total_cents": cents,
                      "currency": "EUR", "payment_mode": "disabled"})
        return Response(body, mimetype="application/json", headers=headers)(environ, start_response)
    pdf = render_pdf({
        "qa_preview": True,
        "serial": f"QA-{order_id}",
        "order_id": str(order_id),
        "origin": origin,
        "destination": destination,
        "service_date": service_date,
        "issued_at": created.isoformat(),
        "buyer": {"name": "QA Passenger", "address": "", "code": "", "vat": ""},
        "seller": {"seller_name": "PRIVATE DRIVE QA", "seller_address": "",
                   "seller_vat": "", "seller_iv": "", "tax_mode": "svs", "tax_basis": ""},
        "amounts": totals(Decimal(cents) / 100, "svs"),
        "payment_method": payment,
    })
    headers["Content-Disposition"] = f'inline; filename="QA-{order_id}.pdf"'
    return Response(pdf, mimetype="application/pdf", headers=headers)(environ, start_response)
