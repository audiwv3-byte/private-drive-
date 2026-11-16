"""Read-only assessment: Telegram guards and approved optional-service UI.
Fetches source files, does not read env, database, orders or users.
"""
import os,re,urllib.request,urllib.error
BASE="https://www.pythonanywhere.com/api/v0/user/wilsonpark/files/path/home/wilsonpark/euro_baltic_transfer/PRIVATE_DRIVE_MiniApp_2026_10_18/"
FILES=("miniapp_server.py","pd_trip_runtime_v4.py","pd_pilot_dispatch.py",
       "pd_admin_console_v4.py","miniapp/templates/index.html")
def fetch(f,t):
    req=urllib.request.Request(BASE+f,headers={"Authorization":"Token "+t},method="GET")
    with urllib.request.urlopen(req,timeout=35) as r:return r.read(2000001).decode("utf8")
def show(k,v):
    print("CHECK",k,"PRESENT" if v else "NOT_FOUND",flush=True)
def main():
    token=re.sub(r"^Token\s+","",os.environ["PYTHONANYWHERE_API_TOKEN"].strip(),flags=re.I)
    d={f:fetch(f,token) for f in FILES}
    server=d["miniapp_server.py"];web=d["miniapp/templates/index.html"]
    trip=d["pd_trip_runtime_v4.py"];pilot=d["pd_pilot_dispatch.py"];admin=d["pd_admin_console_v4.py"]
    show("TELEGRAM_AUTH_SERVER_FUNCTION", "def auth():" in server)
    show("TELEGRAM_INIT_DATA_SERVER_REFERENCE", "initData" in server or "init_data" in server)
    show("ORDER_OWNERSHIP_CHECK", bool(re.search(r"telegram_id.{0,90}(uid|user_id)|(?:uid|user_id).{0,90}telegram_id",server,re.S)))
    show("PILOT_ASSIGNMENT_DB", "pd_pilot_assignments" in trip)
    show("PILOT_ROLE_APPROVAL_GUARD","approved" in trip and "pilot" in trip)
    show("ADMIN_ROLE_GUARD","core.is_admin" in admin or "is_admin(" in admin)
    show("TRIP_PAYMENT_STATUS_GUARD","payment_status" in trip)
    show("TRIP_GPS_WATCH", "watchPosition" in web or "watchPosition" in trip)
    # Issue #19: free radio and Wi-Fi are separate opt-in extras in the
    # general list; request must be persistable and visible to pilot.
    combined=server+"\n"+web+"\n"+pilot+"\n"+trip+"\n"+admin
    show("ISSUE19_WIFI_REQUEST_PERSISTENCE","wifi_requested" in combined)
    show("ISSUE19_RADIO_STATION_FIELD", bool(re.search(r"radio_station|radio_frequency|fm_frequency|radio_choice",combined,re.I)))
    show("ISSUE19_FREE_WIFI_LABEL", bool(re.search(r"Wi.?Fi.{0,90}(?:0\s*€|Бесплатн)",web,re.I)))
    show("ISSUE19_FREE_RADIO_LABEL", bool(re.search(r"Радио.{0,90}(?:0\s*€|Бесплатн)",web,re.I)))
    show("ISSUE19_PILOT_WIFI_NOTICE","Включить Wi-Fi перед посадкой" in combined or "Пассажир запросил Wi" in combined)
    print("NOTE_PRESENCE_IS_NOT_AUTHORIZED_END_TO_END_TEST",flush=True)
    print("NO_WRITES_NO_BOOKINGS_NO_PAYMENTS_NO_SECRETS",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("READONLY_FAILED",type(e).__name__,flush=True)
        raise SystemExit(1)
