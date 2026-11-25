import unittest
from unittest.mock import patch
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.fernet import Fernet
from PIL import Image
from flask import Flask, session, request
from pd_pilot_qa_intake import register, register_production_form


class PilotIntakeIntegration(unittest.TestCase):
    def test_production_sqlite(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "pilot-intake.key").write_bytes(Fernet.generate_key())
            (directory / "pilot-intake.invite").write_text("x" * 40)
            self.check_enrollment(directory)

    @unittest.skipUnless(os.getenv("PD_TEST_FRESH_POSTGRES"), "requires disposable PostgreSQL")
    def test_enrollment(self):
        self.check_enrollment()

    def check_enrollment(self, directory=None):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.update(
            PD_DISPATCH_STAGING_ONLY="1",
            PD_PILOT_QA_INTAKE_ENABLED="1",
            PD_PILOT_QA_DATABASE_URL=os.getenv("PD_TEST_FRESH_POSTGRES", ""),
            PD_PILOT_QA_INVITE_SECRET="x" * 40,
            PD_PILOT_QA_FERNET_KEY=Fernet.generate_key().decode(),
        )
        app = Flask(__name__)
        app.secret_key = os.urandom(32)
        intake = register_production_form(app, directory) if directory else None
        register(
            app,
            lambda: session.get("owner"),
            lambda: "test-csrf",
            lambda: request.form.get("csrf") == "test-csrf",
            production=intake,
        )
        client = app.test_client()

        def photo():
            f = BytesIO()
            Image.new("RGB", (120, 80), "gold").save(f, "PNG")
            f.seek(0)
            return f, "fixture.png"

        form = dict(
            first_name="Тест",
            last_name="Пилот",
            email="pilot@example.invalid",
            phone="+37000000000",
            plate="TEST 01",
            qa_invitation="x" * 40,
        )

        def submit(**extra):
            return client.post(
                "/pilot-registration",
                data=dict(form, license_front=photo(), car_front=photo(), **extra),
                headers={"Origin": "http://localhost"},
            )

        if directory:
            self.assertIn(b"pilot-shift-v1", client.get("/pilot-registration").data)
        assert submit().status_code == 400
        response = submit(terms_version="pilot-shift-v1")
        assert response.status_code == 201, (response.status_code, response.data)
        key = response.json["application_id"]
        url = "/dispatch/qa-pilot-applications/" + key + "/approve"
        assert client.post(url).status_code == 403
        with client.session_transaction() as s:
            s["owner"] = True
        assert client.post(url).status_code == 403
        for _ in range(2):
            assert client.post(url, data={"csrf": "test-csrf"}).json == {
                "pilot_number": 1
            }
        row = client.get("/dispatch/qa-pilot-applications").json["applications"][0]
        assert (
            row["status"] == "approved"
            and row["plate"] == "TEST 01"
            and row["pilot_number"] == 1
        )
        for doc in ("license_front", "car_front"):
            assert (
                client.get(
                    "/dispatch/qa-pilot-applications/" + key + "/documents/" + doc
                ).mimetype
                == "image/webp"
            )
        print(
            "Verified synthetic pilot #1, contacts, plate, consent, two private photos and repeat approval"
        )
