import unittest

from elda_qgis.core.net.redact import scrub

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJpZCI6MX0.sig_nature-1"


class ScrubTest(unittest.TestCase):
    def test_password(self):
        self.assertNotIn("s3cr3t", scrub('{"username":"a","password":"s3cr3t"}'))
        self.assertIn('"username":"a"', scrub('{"username":"a","password":"s3cr3t"}'))

    def test_token_keys(self):
        for key in ("token", "accessToken", "refreshToken"):
            with self.subTest(key=key):
                self.assertNotIn("abc123", scrub('{"%s": "abc123"}' % key))

    def test_escaped_quote_in_value(self):
        self.assertNotIn("tail", scrub('{"password":"pa\\"tail"}'))

    def test_dict_repr(self):
        self.assertNotIn("s3cr3t", scrub("{'password': 's3cr3t'}"))

    def test_form_encoded(self):
        out = scrub("password=s3cr3t&user=a")
        self.assertNotIn("s3cr3t", out)
        self.assertIn("user=a", out)

    def test_key_case(self):
        self.assertNotIn("s3cr3t", scrub('{"Password":"s3cr3t"}'))

    def test_amz_url_encoded(self):
        self.assertNotIn("s3cr3t", scrub("X-Amz-Signature%3Ds3cr3t"))

    def test_bearer(self):
        self.assertNotIn("eyJhbGciOi", scrub("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.e30.abc"))
        self.assertNotIn("opaque", scrub("authorization: bearer opaque-token"))

    def test_bare_jwt(self):
        self.assertNotIn("eyJhbGciOi", scrub("token was " + JWT + " ok"))

    def test_amz_query(self):
        out = scrub("https://b.s3.amazonaws.com/k?X-Amz-Signature=deadbeef&x=1&X-Amz-Credential=AKIA%2F1&X-Amz-Security-Token=tok")
        for secret in ("deadbeef", "AKIA", "=tok"):
            self.assertNotIn(secret, out)
        self.assertIn("x=1", out)

    def test_plain_text_untouched(self):
        self.assertEqual(scrub("hello world"), "hello world")


if __name__ == "__main__":
    unittest.main()
