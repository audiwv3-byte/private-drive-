"""Exercise actual WSGI boot logic without a database or provider communication."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from test_native_closed_invites import FLAGS, STAGING, fallback

WSGI = Path(__file__).resolve().parents[1] / "isolated_sms_wsgi.py"
SYNTHETIC_CREDENTIALS = {
    "TWILIO_ACCOUNT_SID": "synthetic",
    "TWILIO_AUTH_TOKEN": "synthetic",
    "TWILIO_VERIFY_SERVICE_SID": "synthetic",
}
PILOT_ENV = {
    **FLAGS, **SYNTHETIC_CREDENTIALS,
    "PD_NATIVE_PILOT_INVITE_ONBOARDING": "1",
    "DATABASE_URL": STAGING,
}
LIVE_ENV = {"PD_NATIVE_SMS_LIVE": "YES", "TWILIO_VERIFY_ENABLED": "true"}


class ClosedInviteBootTests(unittest.TestCase):
    def boot(self, settings, *, expected=None):
        with patch.dict(os.environ, settings, clear=True), \
             patch("pd_native_auth_postgres_http.make_app", return_value=fallback) as make_app, \
             patch("pd_native_identity_http.make_identity_app", side_effect=lambda app, *a, **kw: app), \
             patch("threading.Thread") as thread:
            if expected is None:
                with self.assertRaisesRegex(RuntimeError, "isolated no-SMS, no-payment"):
                    runpy.run_path(str(WSGI))
                make_app.assert_not_called()
                thread.assert_not_called()
            else:
                loaded = runpy.run_path(str(WSGI))
                self.assertTrue(callable(loaded["application"]))
                self.assertIs(make_app.call_args.kwargs["live"], expected)
                self.assertEqual(thread.called, settings.get("PD_NATIVE_PILOT_INVITE_ONBOARDING") != "1")

    def test_closed_invite_boot_rejects_misconfiguration_before_sms_backend(self):
        for bad in (
            {**PILOT_ENV, **LIVE_ENV},
            {**PILOT_ENV, "PD_NATIVE_SMS_LIVE": "YES"},
            {**PILOT_ENV, "TWILIO_VERIFY_ENABLED": "true"},
            {**PILOT_ENV, "PD_PAYMENT_MODE": "live"},
            {**PILOT_ENV, "PD_NATIVE_CLOSED_PILOT_INVITES": "0"},
            {**PILOT_ENV, "DATABASE_URL": STAGING.replace("private_drive_test", "other")},
        ):
            self.boot(bad)

    def test_valid_invite_boot_forces_sms_off_and_skips_provider_probes(self):
        self.boot(PILOT_ENV, expected=False)

    def test_web_only_photo_review_needs_the_isolated_pilot_invite_opt_in(self):
        with patch.dict(os.environ, {
            **PILOT_ENV, "PD_NATIVE_PILOT_INVITE_ONBOARDING": "0",
            "PD_NATIVE_PHOTO_REVIEW_WEB_ONLY": "1",
        }, clear=True), patch("pd_native_auth_postgres_http.make_app") as make_app:
            with self.assertRaisesRegex(RuntimeError, "Web-only photo review requires"):
                runpy.run_path(str(WSGI))
            make_app.assert_not_called()

        with patch.dict(os.environ, {
            **PILOT_ENV, "PD_NATIVE_PHOTO_REVIEW_WEB_ONLY": "1",
        }, clear=True), patch("pd_native_auth_postgres_http.make_app", return_value=fallback), \
             patch("pd_native_identity_http.make_identity_app", side_effect=lambda app, *a, **kw: app) as identity, \
             patch("threading.Thread"):
            runpy.run_path(str(WSGI))
            self.assertTrue(identity.call_args.kwargs["web_review_only"])
            self.assertTrue(identity.call_args.kwargs["restricted_runtime"])

    def test_without_new_opt_in_legacy_switch_behavior_is_unchanged(self):
        self.boot({**PILOT_ENV, **LIVE_ENV, "PD_NATIVE_PILOT_INVITE_ONBOARDING": "0"},
                  expected=True)


if __name__ == "__main__":
    unittest.main()
