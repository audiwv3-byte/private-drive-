import io
import json
import unittest
from urllib.error import HTTPError

from pd_twilio_setup_diagnostics import inspect_setup


class SetupDiagnosticsTests(unittest.TestCase):
    def test_missing_configuration_does_not_make_any_request(self):
        result = inspect_setup({'PD_NATIVE_SMS_ISOLATED': 'YES'},
            open_url=lambda *args, **kwargs: self.fail('No provider request allowed'))
        self.assertEqual(result['status'], 'missing_configuration')
        self.assertEqual(len(result['missing']), 3)
        self.assertFalse(result['sms_sent'])

    def test_only_read_endpoints_and_no_secret_output_or_flag_changes(self):
        env = {'PD_NATIVE_SMS_ISOLATED': 'YES', 'TWILIO_ACCOUNT_SID': 'AC' + 'a' * 32,
            'TWILIO_AUTH_TOKEN': 'synthetic-secret', 'TWILIO_VERIFY_SERVICE_SID': 'VA' + 'b' * 32}
        original = dict(env)
        responses = [{'status': 'active', 'type': 'Trial', 'auth_token': 'synthetic-secret'},
            {'balance': '12.34', 'currency': 'USD'}, {'account_sid': env['TWILIO_ACCOUNT_SID'], 'code_length': 6}]
        urls = []
        def read(request, timeout):
            self.assertEqual(request.get_method(), 'GET')
            self.assertIsNone(request.data)
            urls.append(request.full_url)
            return io.BytesIO(json.dumps(responses[len(urls) - 1]).encode())
        result = inspect_setup(env, open_url=read)
        self.assertEqual(result['status'], 'read_only_checks_completed')
        self.assertEqual(result['balance'], '12.34')
        self.assertEqual(len(urls), 3)
        self.assertTrue(result['service_matches_account'])
        self.assertFalse(result['sms_live_flag'])
        self.assertEqual(env, original)
        self.assertNotIn('synthetic-secret', json.dumps(result))
        self.assertNotIn(env['TWILIO_ACCOUNT_SID'], json.dumps(result))
        self.assertNotIn(env['TWILIO_VERIFY_SERVICE_SID'], json.dumps(result))
        self.assertTrue(urls[-1].endswith('/Services/' + env['TWILIO_VERIFY_SERVICE_SID']))

    def test_authentication_error_is_sanitized(self):
        env = {'PD_NATIVE_SMS_ISOLATED': 'YES', 'TWILIO_ACCOUNT_SID': 'AC' + 'a' * 32,
            'TWILIO_AUTH_TOKEN': 'synthetic-secret', 'TWILIO_VERIFY_SERVICE_SID': 'VA' + 'b' * 32}
        def denied(request, timeout):
            raise HTTPError(request.full_url, 401, 'synthetic-secret', {}, None)
        result = inspect_setup(env, open_url=denied)
        self.assertEqual(result['status'], 'provider_http_401')
        self.assertNotIn('synthetic-secret', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
