"""Read-only code/route audit of live PRIVATE DRIVE dispatcher passenger card.
Do not read DBs, personal customer data, environment variables or bot credentials.
No writes to production, no test bookings or registrations.
"""
import hashlib,os,re,requests
token=re.sub(r"^Token\s+","",os.environ["PA_API_TOKEN"].strip(),flags=re.I)
token="".join(token.split())
s=requests.Session();s.headers.update({"Authorization":"Token "+token})
api="https://www.pythonanywhere.com/api/v0/user/wilsonpark"
base="/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
files={}
for path in ("miniapp_server.py","pd_service.py","pd_profile_history.py","miniapp/templates/index.html"):
    resp=s.get(api+"/files/path"+base+path,timeout=45)
    resp.raise_for_status()
    files[path]=resp.content.decode("utf-8-sig")
    print("LIVE_SOURCE",path,"bytes",len(resp.content),"sha_prefix",hashlib.sha256(resp.content).hexdigest()[:16])
server=files["miniapp_server.py"]
service=files["pd_service.py"]
history=files["pd_profile_history.py"]
ui=files["miniapp/templates/index.html"]

checks={
"telegram_signed_auth_used": "def auth()" in server and "verify_telegram_user" in server,
"admin_customer_detail_route": "@app.get('/api/admin/customers/<int:customer_id>')" in server,
"admin_customer_detail_requires_admin": bool(re.search(r"def pd_customer_details\(customer_id\):\s+uid,\s*_\s*=\s*auth\(\)\s+if not core\.is_admin\(uid\):",server)),
"admin_customer_list_requires_admin": bool(re.search(r"def admin_customers_pd\(\):\s+uid,\s*_\s*=\s*auth\(\)\s+if not core\.is_admin\(uid\)",server)),
"service_profile_table": "CREATE TABLE IF NOT EXISTS pd_passenger_profile" in service,
"telegram_first_name_storage": "first_name=excluded.first_name" in service,
"telegram_last_name_storage": "last_name=excluded.last_name" in service,
"telegram_username_storage": "username=excluded.username" in service,
"telegram_id_primary_key": "telegram_id INTEGER PRIMARY KEY" in service,
"saved_phone_from_registration": "core.save_user(uid, name, validated_phone)" in server,
"phone_from_telegram_permission_existing": "requestContact" in ui and "pdRegisterPassengerTelegram()" in ui,
"admin_profile_api_attachment": "data['customer']['profile'] = profile(customer_id)" in service,
"admin_profile_list_includes_username": "p.username,p.email,p.home_city" in service,
"admin_profile_history_requires_admin": bool(re.search(r"def pd_profile_history_list\(customer\):[\s\S]{0,150}if not core\.is_admin\(uid\)",history)),
"admin_customer_panel_exists": 'id="pdCustomers"' in ui,
"admin_customer_detail_endpoint_called_in_ui": "api('/api/admin/customers/'+id)" in ui,
"ui_profile_first_name_visible": bool(re.search(r"(?:c|p|profile)\.first_name",ui)),
"ui_profile_last_name_visible": bool(re.search(r"(?:c|p|profile)\.last_name",ui)),
"ui_profile_username_visible": bool(re.search(r"(?:c|p|profile)\.username",ui)),
"ui_telegram_id_visible": bool(re.search(r"Telegram ID:",ui)),
"ui_contact_phone_visible": "c.phone" in ui,
"ui_customer_profile_history": "/profile-history" in ui,
"api_no_store_private": "no-store" in service and "Vary" in service,
}
for key,value in checks.items():print("CHECK",key,str(value).lower())

# Source-only audit: no personal records queried.
# Public unauthenticated route check is permitted and must never show customer data.
for route in ("/api/admin/customers-v2","/api/admin/customers/0"):
    r=requests.get("https://wilsonpark.pythonanywhere.com"+route,timeout=25,
         headers={"Cache-Control":"no-cache"})
    print("UNAUTHENTICATED",route,"status",r.status_code,"cache",r.headers.get("Cache-Control",""),"contains_customers_key",'"customers":' in r.text)
print("AUDIT_DONE changes_to_live=0 database_reads=0 orders_created=0")
