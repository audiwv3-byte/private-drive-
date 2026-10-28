"""Authenticated recent routes. Repeating a route never repeats a payment."""
import re,math
import Euro_Baltic_Transfer as core

def point_for(address,details,key):
    numeric=r'(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)'
    match=re.fullmatch(r'\s*'+numeric+r'\s*',address or '')
    label='Координаты подачи' if key=='origin' else 'Координаты назначения'
    matches=re.findall(re.escape(label)+r':\s*'+numeric,details or '')
    pair=matches[-1] if matches else match.groups() if match else None
    if not pair:return None
    lat,lon=map(float,pair)
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:return None
    return [lon,lat]

def recent(uid):
    with core.db(core.ORDERS_DB) as c:
        rows=c.execute("SELECT id,origin,destination,details,stop_address FROM orders WHERE telegram_id=? AND status!='Отменена' ORDER BY id DESC LIMIT 30",(uid,)).fetchall()
    items=[];seen=set()
    for row in rows:
        origin=str(row['origin'] or '').strip();dest=str(row['destination'] or '').strip()
        if len(origin)<2 or len(dest)<2:continue
        a=point_for(origin,row['details'],'origin');b=point_for(dest,row['details'],'destination')
        key=(tuple(round(x,6) for x in a) if a else ' '.join(origin.casefold().split()),tuple(round(x,6) for x in b) if b else ' '.join(dest.casefold().split()))
        key=key+(str(row['stop_address'] or '').casefold(),)
        if key in seen:continue
        seen.add(key)
        item=dict(order_id=row['id'],origin=origin,destination=dest,stop_address=row['stop_address'] or '')
        if a:item['origin_coordinates']=a
        if b:item['destination_coordinates']=b
        items.append(item)
        if len(items)==3:break
    return items

def register(app,auth):
    from flask import jsonify
    @app.get('/api/recent-routes')
    def pd_recent_route_list():
        uid,_=auth()
        return jsonify(routes=recent(uid))
