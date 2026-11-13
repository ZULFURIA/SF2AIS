import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

import main


class AdminAuthTests(unittest.TestCase):
    def credentials(self, password):
        return HTTPBasicCredentials(username="test-admin", password=password)

    def test_valid_bcrypt_hash_authenticates_without_rewrite(self):
        password_hash = main.bcrypt.hash("Correct-Horse-123!")
        config = {"admin": {"username": "test-admin", "password_hash": password_hash}}

        with patch.object(main, "load_config", return_value=config), patch.object(main, "save_config") as save:
            self.assertEqual(main.admin_auth(self.credentials("Correct-Horse-123!")), "test-admin")
            save.assert_not_called()

    def test_legacy_plaintext_value_is_upgraded_after_successful_auth(self):
        config = {"admin": {"username": "test-admin", "password_hash": "Legacy-Pass-123!"}}

        with patch.object(main, "load_config", return_value=config), patch.object(main, "save_config") as save:
            self.assertEqual(main.admin_auth(self.credentials("Legacy-Pass-123!")), "test-admin")

        upgraded = config["admin"]["password_hash"]
        self.assertNotEqual(upgraded, "Legacy-Pass-123!")
        self.assertTrue(main.bcrypt.identify(upgraded))
        self.assertTrue(main.bcrypt.verify("Legacy-Pass-123!", upgraded))
        save.assert_called_once_with(config)

    def test_wrong_password_for_legacy_value_returns_401_without_rewrite(self):
        config = {"admin": {"username": "test-admin", "password_hash": "Legacy-Pass-123!"}}

        with patch.object(main, "load_config", return_value=config), patch.object(main, "save_config") as save:
            with self.assertRaises(HTTPException) as raised:
                main.admin_auth(self.credentials("Wrong-Pass-123!"))

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(config["admin"]["password_hash"], "Legacy-Pass-123!")
        save.assert_not_called()

    def test_wrong_username_does_not_authenticate(self):
        config = {"admin": {"username": "test-admin", "password_hash": main.bcrypt.hash("Correct-Horse-123!")}}

        with patch.object(main, "load_config", return_value=config):
            with self.assertRaises(HTTPException) as raised:
                main.admin_auth(HTTPBasicCredentials(username="other-user", password="Correct-Horse-123!"))

        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
