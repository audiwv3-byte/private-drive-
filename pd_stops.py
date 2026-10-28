"""Optional intermediate address included in route quotes and stored bookings."""
import json

def ensure_schema(core):
    core.initialize()
    with core.db(core.ORDERS_DB) as c:
        if 'stop_address' not in {r['name'] for r in c.execute('PRAGMA table_info(orders)')}:
            c.execute("ALTER TABLE orders ADD COLUMN stop_address TEXT NOT NULL DEFAULT ''")

def address(data):
    value=data.get('stop_address','')
    if not isinstance(value,str):raise ValueError('Укажите адрес остановки')
    value=' '.join(value.split())
    if value and not 2<=len(value)<=200:raise ValueError('Укажите адрес остановки')
    if value and value.casefold() in [str(data.get(k,'')).strip().casefold() for k in ('origin','destination')]:
        raise ValueError('Адрес остановки должен отличаться от начала и конца маршрута')
    return value

def directions(core,points,data,origin,destination):
    stop=address(data)
    start=core.geocode(points.route_address(data,'origin',origin))
    end=core.geocode(points.route_address(data,'destination',destination))
    coordinates=[start]+([core.geocode(stop)] if stop else [])+[end]
    payload=json.dumps({'coordinates':coordinates}).encode('utf-8')
    result=core.ors_request('https://api.openrouteservice.org/v2/directions/driving-car/geojson',payload)
    return result['features'][0],start,end
