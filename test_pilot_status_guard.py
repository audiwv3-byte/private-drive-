"""Safe unit regression of route adapters, no live app, bookings or payments."""
import json
from flask import Flask, jsonify
from pd_trip_runtime_v4 import secure_legacy_status_route

app=Flask(__name__)
app.config['TESTING']=True
calls=[]
@app.post('/api/driver/work/<int:oid>/status')
def legacy_status(oid):
    raise AssertionError('Insecure old handler must not run')
app.config['PD_TRIP_TRANSITION_V4']=lambda oid, action, uid: calls.append((oid,action,uid)) or {'ok':True}
app.config['PD_TRIP_AUTH_V4']=lambda: (123456, {})
secure_legacy_status_route(app)
assert app.config['PD_TRIP_LEGACY_STATUS_SECURED'] is True
with app.test_client() as client:
    response=client.post('/api/driver/work/42/status',json={'status':'В пути'})
    assert response.status_code==200,(response.status_code,response.get_data(as_text=True))
    assert calls==[(42,'start',123456)],calls
    response=client.post('/api/driver/work/42/status',json={'status':'Выполнена'})
    assert response.status_code==200
    assert calls[-1]==(42,'finish',123456)
    for status in ('Подтверждена','Отменена','UNKNOWN'):
        try:
            client.post('/api/driver/work/42/status',json={'status':status})
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid state was not rejected')
print('PASS legacy pilot endpoint delegates to unified V4 transition')
print('PASS unrecognized pilot state changes rejected')
missing=Flask('missing')
missing.config['PD_TRIP_TRANSITION_V4']=lambda *args: {}
try:
    secure_legacy_status_route(missing)
except RuntimeError:
    pass
else:
    raise AssertionError('Missing route did not fail closed')
print('PASS route initialization fails closed if endpoint missing')

# Postdeployment isolated regression rerun 2026-11-16
