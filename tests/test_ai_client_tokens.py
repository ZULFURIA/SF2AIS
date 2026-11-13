import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import main


class AiClientTokenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = {
            "admin": {"username": "admin", "password_hash": main.bcrypt.hash("Admin-Pass-123!")},
            "network": {"method": "static", "value": "127.0.0.1", "port": 8000},
            "shares": [{
                "id": "share-1", "username": "project",
                "password_hash": main.bcrypt.hash("Share-Pass-123!"),
                "folder": str(self.root), "last_seen": None,
                "workspace_write_enabled": True, "cli_enabled": True,
                "tunnel_enabled": False, "clients": [],
            }],
        }
        self.config_patch = patch.object(main, "load_config", side_effect=lambda: self.config)
        self.save_patch = patch.object(main, "save_config")
        self.sandbox_patch = patch.object(main.sandbox_runner, "sandbox_status",
                                           return_value={"available": False, "reason": "Docker Engine unavailable."})
        self.config_patch.start()
        self.save_patch.start()
        self.sandbox_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.config_patch.stop()
        self.save_patch.stop()
        self.sandbox_patch.stop()
        self.temp.cleanup()

    def create_token(self, **data):
        response = self.client.post("/dashboard/shares/share-1/clients/create",
                                    data={"name": "ChatGPT browser", **data},
                                    auth=("admin", "Admin-Pass-123!"))
        self.assertEqual(response.status_code, 200, response.text)
        token = re.search(r'id="client-token">([^<]+)', response.text).group(1)
        return token

    def test_scoped_token_can_read_but_cannot_write(self):
        token = self.create_token()
        headers = {"X-Sf2AiS-Token": token}
        status = self.client.get("/api/workspace/status", headers=headers)
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["write_enabled"])
        denied = self.client.put("/api/workspace/file", json={"path": "a.txt", "content": "x"}, headers=headers)
        self.assertEqual(denied.status_code, 403)

    def test_write_scope_and_revocation(self):
        token = self.create_token(write="on")
        headers = {"X-Sf2AiS-Token": token}
        status = self.client.get("/api/workspace/status", headers=headers)
        self.assertTrue(status.json()["write_enabled"])
        saved = self.client.put("/api/workspace/file", json={"path": "new.txt", "content": "hello"}, headers=headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        client_id = self.config["shares"][0]["clients"][0]["id"]
        revoked = self.client.post(f"/dashboard/shares/share-1/clients/{client_id}/revoke",
                                   auth=("admin", "Admin-Pass-123!"))
        self.assertIn(revoked.status_code, (200, 303))
        denied = self.client.get("/api/workspace/status", headers=headers)
        self.assertEqual(denied.status_code, 401)

    def test_cli_scope_is_independent(self):
        token = self.create_token()
        response = self.client.post("/cli/jobs", json={"command": "id", "shell": "bash"},
                                    headers={"X-Sf2AiS-Token": token})
        self.assertEqual(response.status_code, 403)
        self.assertIn("CLI permission", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
