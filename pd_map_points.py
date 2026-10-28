"""Validated map points and reverse geocoding for signed Telegram users."""
import math,urllib.parse
import Euro_Baltic_Transfer as core

def read_point(data,key):
    p=data.get(key+'_coordinates')
    if p is None:return None
    if not isinstance(p,list) or len(p)!=2 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or (isinstance(x,float) and not math.isfinite(x)) for x in p):
        raise ValueError('Некорректная точка на карте')
    lon,lat=p
    if not -180<=lon<=180 or not -90<=lat<=90:raise ValueError('Точка находится вне карты')
    return [float(lon),float(lat)]

def route_address(data,key,label):
    p=read_point(data,key)
    return ('%.6f,%.6f'%(p[1],p[0])) if p else label

def point_details(data):
    parts=[]
    for key,label in [('origin','Координаты подачи'),('destination','Координаты назначения')]:
        p=read_point(data,key)
        if p:parts.append(label+': %.6f, %.6f'%(p[1],p[0]))
    return '; '.join(parts)

def reverse(point):
    fallback='Точка на карте (%.5f, %.5f)'%(point[1],point[0])
    if not core.ORS_API_KEY:return dict(label=fallback,available=False)
    query=urllib.parse.urlencode({'api_key':core.ORS_API_KEY,'point.lat':point[1],'point.lon':point[0],'size':1,'layers':'address,street'})
    try:
        doc=core.ors_request('https://api.openrouteservice.org/geocode/reverse?'+query)
        features=doc.get('features') or []
        label=str(features[0].get('properties',{}).get('label','')).strip() if features else ''
        return dict(label=label[:200] or fallback,available=bool(label))
    except Exception:
        core.LOG.warning('Reverse geocoding unavailable; keeping the selected map point')
        return dict(label=fallback,available=False)

def suggest(raw):
    if not isinstance(raw,str):raise ValueError('Введите адрес текстом')
    text=' '.join(raw.split())
    if not 3<=len(text)<=200:raise ValueError('Введите от 3 до 200 символов адреса')
    if not core.ORS_API_KEY:return dict(available=False,suggestions=[])
    query=urllib.parse.urlencode({'api_key':core.ORS_API_KEY,'text':text,'size':5,'focus.point.lat':54.6872,'focus.point.lon':25.2797})
    try:
        doc=core.ors_request('https://api.openrouteservice.org/geocode/autocomplete?'+query)
        results=[];seen=set()
        for f in doc.get('features') or []:
            if not isinstance(f,dict):continue
            label=str((f.get('properties') or {}).get('label') or '').strip()[:200]
            coords=(f.get('geometry') or {}).get('coordinates')
            try:point=read_point({'item_coordinates':coords},'item')
            except (ValueError,TypeError):continue
            if not label or point is None:continue
            key=(label.casefold(),round(point[0],6),round(point[1],6))
            if key in seen:continue
            seen.add(key);results.append(dict(label=label,coordinates=point))
            if len(results)==5:break
        return dict(available=True,suggestions=results)
    except Exception:
        core.LOG.warning('Address suggestions unavailable; manual entry remains available')
        return dict(available=False,suggestions=[])

def register(app,auth):
    from flask import request,jsonify
    @app.post('/api/map/reverse')
    def pd_reverse_map_point():
        auth()
        d=request.get_json(silent=True)
        if not isinstance(d,dict):raise ValueError('Некорректная точка')
        p=read_point(d,'point')
        if p is None:raise ValueError('Выберите точку на карте')
        return jsonify(reverse(p))

    @app.post('/api/map/suggest')
    def pd_suggest_addresses():
        auth()
        d=request.get_json(silent=True)
        if not isinstance(d,dict):raise ValueError('Некорректный запрос адреса')
        return jsonify(suggest(d.get('text')))
