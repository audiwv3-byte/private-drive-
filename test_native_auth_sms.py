import unittest
from pd_native_auth_sms import make_sms_delivery, SMSDeliveryDisabled


class SMSDeliveryTests(unittest.TestCase):
    def test_disabled_by_default(self):
        sent = []
        deliver = make_sms_delivery(lambda to, msg: sent.append((to, msg)))
        with self.assertRaises(SMSDeliveryDisabled):
            deliver("phone", "+37060000000", "123456")
        self.assertEqual(sent, [])

    def test_opt_in_uses_injected_transport(self):
        sent = []
        deliver = make_sms_delivery(lambda to, msg: sent.append((to, msg)), enabled=True)
        deliver("phone", " +37060000000 ", "000123")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "+37060000000")
        self.assertIn("000123", sent[0][1])

    def test_rejects_invalid_channel_and_code(self):
        deliver = make_sms_delivery(lambda to, msg: None, enabled=True)
        with self.assertRaises(ValueError):
            deliver("email", "test@example.com", "123456")
        with self.assertRaises(ValueError):
            deliver("phone", "+37060000000", "123")


if __name__ == "__main__":
    unittest.main()
