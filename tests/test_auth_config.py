import sys
import types
import unittest
from unittest.mock import patch

from estadias_app.auth import authenticate, users_missing


class AuthenticationConfigTest(unittest.TestCase):
    def test_no_configured_users_denies_login(self):
        streamlit = types.ModuleType("streamlit")
        streamlit.secrets = {}
        with patch.dict(sys.modules, {"streamlit": streamlit}):
            self.assertTrue(users_missing())
            self.assertFalse(authenticate("admin", "admin"))

    def test_configured_user_does_not_enable_implicit_admin(self):
        streamlit = types.ModuleType("streamlit")
        streamlit.secrets = {"users": {"operator": "test-secret"}}
        with patch.dict(sys.modules, {"streamlit": streamlit}):
            self.assertFalse(users_missing())
            self.assertTrue(authenticate("operator", "test-secret"))
            self.assertFalse(authenticate("admin", "admin"))


if __name__ == "__main__":
    unittest.main()
