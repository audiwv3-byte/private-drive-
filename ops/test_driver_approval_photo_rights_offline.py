"""Offline regression for pilot approval + document ownership.
Synthetic users, images, SQLite. No PythonAnywhere, real drivers or payments.
"""
import contextlib,datetime,io,pathlib,sqlite3,sys,tempfile
from PIL import Image
from flask import Flask,jsonify,request
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pd_onboarding

class FakeCore:
    def __init__(self,path):
        self.USERS_DB=str(path)
        self.admins={700}
    @contextlib.contextmanager
    def db(self,path):
        with sqlite3.connect(path) as conn:
            conn.row_factory=sqlite3.Row
            yield conn
    def initialize(self):pass
    def now(self):return datetime.datetime(2026,11,16,15,0)
    def clean_phone(self,number):return number if str(number).startswith("+") and len(number)>=8 else None
    def is_admin(self,uid):return uid in self.admins

def img(i):
    out=io.BytesIO()
    Image.new("RGB",(1200,800),(i*27%255,i*43%255,i*61%255)).save(out,format="JPEG")
    return out.getvalue()

def verify(condition,name):
    if not condition:raise AssertionError(name)
    print("PASS",name,flush=True)
def main():
    with tempfile.TemporaryDirectory(prefix="pd-approval-fixtures-") as td:
        core=FakeCore(pathlib.Path(td)/"users.sqlite")
        app=Flask("pd-approval-synthetic")
        app.config["TESTING"]=True
        @app.errorhandler(ValueError)
        def handle_value(exc):return jsonify(error=str(exc)),400
        @app.errorhandler(PermissionError)
        def handle_perm(exc):return jsonify(error=str(exc)),403
        @app.get("/api/me")
        def me():
            return jsonify(id=int(request.headers["X-Test-UID"]),name="Synthetic",registered=True)
        def auth():
            return int(request.headers.get("X-Test-UID","101")),"synthetic"
        pd_onboarding.register(app,core,auth)
        client=app.test_client()
        def call(method,url,uid=101,**kw):
            return client.open(url,method=method,headers={"X-Test-UID":str(uid)},**kw)
        def application(photo_sides=None,uid=101):
            body={"name":"Demo Pilot","phone":"+37060000000","city":"Vilnius","vehicle":"RAV4",
                  "vehicle_year":2020,"plate":"AAA123","seats":4}
            photos={name:(io.BytesIO(img(i+1)),name+".jpg") for i,name in enumerate(photo_sides or [])}
            return call("POST","/api/driver/application",uid,data={"application":__import__("json").dumps(body),**photos},
                        content_type="multipart/form-data")
        def decision(status,uid=700):
            return call("POST","/api/admin/driver-applications/101/decision",uid,json={"status":status})
        # Incomplete applicant cannot be silently approved.
        r=application(["license_front","license_back","car_front","car_rear"])
        verify(r.status_code==400,"MISSING_INITIAL_PHOTO_REJECTED")
        r=application(pd_onboarding.ACTIVE_SIDES)
        verify(r.status_code==200,"SYNTHETIC_INITIAL_DOCUMENT_UPLOAD")
        r=decision("approved",uid=101)
        verify(r.status_code==403,"PILOT_CANNOT_APPROVE_HIMSELF")
        r=decision("approved")
        verify(r.status_code==200,"DISPATCHER_APPROVES_COMPLETE_PILOT")
        with core.db(core.USERS_DB) as c:
            status=c.execute("SELECT status FROM pd_driver_applications WHERE telegram_id=101").fetchone()[0]
            original=c.execute("SELECT image FROM pd_driver_documents WHERE telegram_id=101 AND side='car_front'").fetchone()[0]
        verify(status=="approved","STATUS_PERSISTED_APPROVED")
        verify(application(["car_front"]).status_code==400,"APPROVED_PILOT_CANNOT_RESET_STATUS")
        with core.db(core.USERS_DB) as c:
            verify(c.execute("SELECT status FROM pd_driver_applications WHERE telegram_id=101").fetchone()[0]=="approved",
                   "APPROVAL_NOT_REVOKED_BY_RESUBMISSION")
        # Unapproved pilot with all five stored also must never replace.
        verify(decision("pending").status_code==200,"DISPATCHER_CAN_SET_REVIEW")
        verify(application(["car_front"]).status_code==403,"PENDING_PILOT_CANNOT_REPLACE_SAVED_PHOTO")
        with core.db(core.USERS_DB) as c:
            verify(c.execute("SELECT image FROM pd_driver_documents WHERE telegram_id=101 AND side='car_front'").fetchone()[0]==original,
                   "REJECTED_PHOTO_UPLOAD_PRESERVES_BLOB")
        replace_path="/api/admin/driver-applications/101/documents/car_front/replace"
        photo=img(8)
        verify(call("POST",replace_path,uid=101,data={"car_front":(io.BytesIO(photo),"new.jpg")},
                    content_type="multipart/form-data").status_code==403,"PILOT_CANNOT_USE_ADMIN_REPLACE_ENDPOINT")
        response=call("POST",replace_path,uid=700,data={"car_front":(io.BytesIO(photo),"new.jpg")},
                      content_type="multipart/form-data")
        verify(response.status_code==200,"DISPATCHER_REPLACES_ONE_PHOTO")
        with core.db(core.USERS_DB) as c:
            verify(c.execute("SELECT image FROM pd_driver_documents WHERE telegram_id=101 AND side='car_front'").fetchone()[0]!=original,
                   "DISPATCHER_REPLACEMENT_SAVED")
            verify(c.execute("SELECT count(*) FROM pd_driver_document_replacements WHERE telegram_id=101").fetchone()[0]==1,
                   "DISPATCHER_REPLACEMENT_AUDITED")
        verify(decision("approved").status_code==200,"DISPATCHER_APPROVES_AFTER_REPLACEMENT")
        report=call("GET","/api/admin/driver-applications",uid=700)
        verify(report.status_code==200 and report.json["applications"][0]["missing_document_sides"]==[],
               "DISPATCHER_GETS_MISSING_DOCS_FIELD")
        verify(call("GET","/api/admin/driver-applications",uid=101).status_code==403,"ADMIN_APPLICATION_LIST_PRIVATE")
        print("PILOT_PHOTO_APPROVAL_SYNTHETIC_TESTS_PASS",flush=True)
        print("NO_REAL_DRIVERS_USERS_ORDERS_OR_PROVIDER_CALLS",flush=True)
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("TEST_FAILED",type(e).__name__,str(e)[:200],flush=True)
        raise SystemExit(1)
