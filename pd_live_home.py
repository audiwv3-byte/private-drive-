"""One current trip, explicit passenger location sharing and private optional avatars."""
import io,math,time,warnings
from pathlib import Path
from flask import request,jsonify,Response
from PIL import Image,ImageOps,UnidentifiedImageError

def photo_bytes(raw):
 if not raw or len(raw)>5*1024*1024:raise ValueError('Фото: JPEG, PNG, WebP или HEIC, до 5 МБ')
 try:
  with warnings.catch_warnings():
   warnings.simplefilter('error',Image.DecompressionBombWarning)
   with Image.open(io.BytesIO(raw)) as im:
    if im.format not in ('JPEG','PNG','WEBP','HEIF','HEIC') or im.width*im.height>20000000 or min(im.size)<64:raise ValueError('Нужно обычное фото размером от 64 × 64 пикселей')
    im.seek(0);im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((1000,1000));out=io.BytesIO();im.save(out,'JPEG',quality=86);return out.getvalue()
 except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):raise ValueError('Не удалось прочитать фото. Выберите JPEG, PNG, WebP или HEIC.') from None

def register(app,core,auth,clock=time.time):
 with core.db(core.ORDERS_DB) as c:c.execute('CREATE TABLE IF NOT EXISTS pd_passenger_location_v6(order_id INTEGER PRIMARY KEY,owner_id INTEGER NOT NULL,pilot_id INTEGER NOT NULL,lat REAL NOT NULL,lon REAL NOT NULL,accuracy REAL,updated_at INTEGER NOT NULL)')
 with core.db(core.USERS_DB) as c:c.execute('CREATE TABLE IF NOT EXISTS pd_profile_avatars_v6(uid INTEGER PRIMARY KEY,jpeg BLOB NOT NULL,updated_at INTEGER NOT NULL)')
 @app.after_request
 def pd_v6_private(response):
  if request.path.startswith(('/api/current-trip-v6','/api/profile/avatar-v6')) or request.path.endswith('/passenger-location-v6'):
   response.headers['Cache-Control']='private, no-store'
   response.headers['Vary']='X-Telegram-Init-Data'
  return response
 def pilot_allowed(uid):
  with core.db(core.USERS_DB) as c:return bool(c.execute("SELECT 1 FROM pd_driver_applications WHERE telegram_id=? AND status='approved'",(uid,)).fetchone())
 def owned_order(c,oid,uid):
  r=c.execute('SELECT o.*,a.pilot_id FROM orders o LEFT JOIN pd_pilot_assignments a ON a.order_id=o.id WHERE o.id=?',(oid,)).fetchone()
  if not r or uid not in (r['telegram_id'],r['pilot_id']):raise PermissionError('Нет доступа к геопозиции поездки')
  if r['status'] not in ('Подтверждена','В пути') or not r['pilot_id'] or not pilot_allowed(r['pilot_id']):raise ValueError('Передача геопозиции доступна только в активной поездке с назначенным пилотом')
  return r
 @app.get('/assets/pd-live-home-v6.js')
 def pd_live_home_script():return Response(Path(__file__).with_suffix('.js').read_text(),mimetype='application/javascript',headers={'Cache-Control':'no-cache'})
 @app.get('/api/current-trip-v6')
 def pd_current_trip_v6():
  uid,_=auth();pilot=request.args.get('role')=='pilot'
  if pilot and not pilot_allowed(uid):raise PermissionError('Кабинет доступен одобренному пилоту')
  condition='a.pilot_id=?' if pilot else "o.telegram_id=? AND o.payment_status='Оплачено'"
  with core.db(core.ORDERS_DB) as c:
   rows=c.execute("SELECT o.id,o.origin,o.stop_address,o.destination,o.trip_date,o.trip_time,o.status,o.price,o.payment_status,a.pilot_id,t.departed_at,t.departed_pilot_id,t.started_at FROM orders o JOIN pd_pilot_assignments a ON a.order_id=o.id LEFT JOIN pd_trip_runtime_v4 t ON t.order_id=o.id WHERE o.status IN ('Подтверждена','В пути') AND "+condition+" ORDER BY CASE WHEN o.status='В пути' THEN 0 WHEN t.departed_at IS NOT NULL AND t.departed_pilot_id=a.pilot_id THEN 1 ELSE 2 END,o.id DESC LIMIT 1",(uid,)).fetchall()
   # A GET only reads. Expired locations are filtered when retrieved, never deleted here.
  order=dict(rows[0]) if rows and pilot_allowed(rows[0]['pilot_id']) else None
  return jsonify(order=order,server_now=int(clock()))
 @app.route('/api/trip/<int:oid>/passenger-location-v6',methods=['GET','POST'])
 def pd_passenger_location_v6(oid):
  uid,_=auth()
  with core.db(core.ORDERS_DB) as c:
   r=owned_order(c,oid,uid)
   if request.method=='POST':
    if uid!=r['telegram_id']:raise PermissionError('Геопозицией делится только пассажир своего заказа')
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):raise ValueError('Некорректный запрос')
    if data.get('share') is False:
     c.execute('DELETE FROM pd_passenger_location_v6 WHERE order_id=? AND owner_id=?',(oid,uid));return jsonify(ok=True,sharing=False)
    if data.get('share') is not True:raise ValueError('Нужно согласие пассажира на передачу геопозиции пилоту')
    try:lat,lon,accuracy=float(data['lat']),float(data['lon']),float(data.get('accuracy',0))
    except (KeyError,TypeError,ValueError):raise ValueError('Некорректные координаты') from None
    if not all(math.isfinite(v) for v in (lat,lon,accuracy)) or not -90<=lat<=90 or not -180<=lon<=180 or not 0<=accuracy<=10000:raise ValueError('Некорректные координаты')
    c.execute('INSERT OR REPLACE INTO pd_passenger_location_v6 VALUES(?,?,?,?,?,?,?)',(oid,uid,r['pilot_id'],lat,lon,accuracy,int(clock())));return jsonify(ok=True,sharing=True)
   p=c.execute('SELECT lat,lon,accuracy,updated_at,pilot_id FROM pd_passenger_location_v6 WHERE order_id=?',(oid,)).fetchone()
   valid=bool(p and p['pilot_id']==r['pilot_id'] and 0<=clock()-p['updated_at']<=45)
   return jsonify(location={k:p[k] for k in ('lat','lon','accuracy','updated_at')} if valid else None,sharing=valid)
 @app.route('/api/profile/avatar-v6',methods=['GET','POST','DELETE'])
 def pd_profile_avatar_v6():
  uid,_=auth()
  if request.method=='POST':
   file=request.files.get('photo')
   if not file:raise ValueError('Выберите фотографию')
   jpeg=photo_bytes(file.stream.read(5*1024*1024+1))
   with core.db(core.USERS_DB) as c:c.execute('INSERT OR REPLACE INTO pd_profile_avatars_v6 VALUES(?,?,?)',(uid,jpeg,int(clock())))
   return jsonify(ok=True)
  if request.method=='DELETE':
   with core.db(core.USERS_DB) as c:c.execute('DELETE FROM pd_profile_avatars_v6 WHERE uid=?',(uid,))
   return jsonify(ok=True)
  target=request.args.get('uid',uid,type=int)
  if target!=uid and not core.is_admin(uid):raise PermissionError('Фото доступно владельцу и диспетчеру')
  with core.db(core.USERS_DB) as c:r=c.execute('SELECT jpeg FROM pd_profile_avatars_v6 WHERE uid=?',(target,)).fetchone()
  if not r:return Response(status=404)
  return Response(bytes(r['jpeg']),mimetype='image/jpeg',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


 # Queue pilot photo replacements; keep the approved image until dispatcher review.
 import pd_photo_review
 pd_photo_review.register(app,core,auth,photo_bytes,clock)
