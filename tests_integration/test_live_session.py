import os
import unittest

from elda_qgis.core.errors import AuthError
from elda_qgis.core.net.http import Caller
from elda_qgis.core.session.api import EldaApi
from elda_qgis.core.net.urllib_transport import UrllibTransport

SERVER = os.environ.get("ELDA_TEST_SERVER", "")
USER = os.environ.get("ELDA_TEST_USER")
PASSWORD = os.environ.get("ELDA_TEST_PASSWORD")


def make_api():
    return EldaApi(SERVER, Caller(UrllibTransport()))


@unittest.skipUnless(SERVER and USER and PASSWORD, "ELDA_TEST_SERVER, ELDA_TEST_USER and ELDA_TEST_PASSWORD not set")
class LiveSessionTest(unittest.TestCase):
    def test_login_me_logout(self):
        api = make_api()
        account = api.login(USER, PASSWORD)
        self.assertTrue(account.sites)
        self.assertEqual(api.me().username, account.username)
        api.logout()
        self.assertFalse(api.is_logged_in)

    def test_wrong_password_raises_auth_error(self):
        with self.assertRaises(AuthError):
            make_api().login("cda_nobody_qgis_test", "not-the-password")
