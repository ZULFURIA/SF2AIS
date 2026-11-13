import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
import project_access


class ProjectAccessPolicyTests(unittest.TestCase):
    def test_path_rules_inherit_and_specific_deny_wins(self):
        permissions = {
            "read": True,
            "write": True,
            "upload": False,
            "download": True,
            "deny": False,
            "rules": [
                {"path": "src", "write": False},
                {"path": "src/private", "deny": True},
                {"path": "src/public", "write": True},
            ],
        }
        client = {"project_access": permissions}
        self.assertTrue(project_access.is_allowed(client, "README.md", "read"))
        self.assertFalse(project_access.is_allowed(client, "src/main.py", "write"))
        self.assertTrue(project_access.is_allowed(client, "src/public/main.py", "write"))
        self.assertFalse(project_access.is_allowed(client, "src/private/secret.txt", "read"))
        self.assertTrue(project_access.is_allowed(client, "README.md", "download"))
        self.assertFalse(project_access.is_allowed(client, "README.md", "upload"))

    def test_new_identity_has_no_permissions_by_default(self):
        empty = {"project_access": {"read": False, "write": False, "upload": False,
                                    "download": False, "deny": False, "rules": []}}
        for action in project_access.ACTIONS:
            self.assertFalse(project_access.is_allowed(empty, "src/main.py", action))

    def test_invalid_and_protected_rule_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            project_access.validate_access_config({"read": True, "rules": [{"path": "../outside", "read": True}]})
        clean = project_access.validate_access_config({"rules": [{"path": "src/config.json", "read": True}]})
        self.assertEqual(clean["rules"][0]["path"], "src/config.json")


class ProjectAccessApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "hello.py").write_text("print('hello')\\n", encoding="utf-8")
        (self.root / "src" / "private.txt").write_text("private", encoding="utf-8")
        self.token = "project-access-test-token"
        self.client_record = {
            "id": "client-1",
            "name": "Test AI",
            "token_hash": hashlib.sha256(self.token.encode()).hexdigest(),
            "permissions": {
                "read": False,
                "write": False,
                "project_access": {
                    "read": False, "write": False, "upload": False,
                    "download": False, "deny": False,
                    "rules": [{"path": "src", "read": True},
                              {"path": "src/private.txt", "deny": True}],
                },
            },
        }
        self.share = {
            "id": "share-1", "username": "project",
            "password_hash": main.bcrypt.hash("Legacy-Pass-123!"),
            "folder": str(self.root), "last_seen": None,
            "workspace_write_enabled": True,
            "clients": [self.client_record],
        }
        self.config = {
            "admin": {"username": "admin", "password_hash": main.bcrypt.hash("Admin-Pass-123!")},
            "network": {"method": "static", "value": "127.0.0.1", "port": 8000},
            "shares": [self.share],
        }
        self.config_patch = patch.object(main, "load_config", side_effect=lambda: self.config)
        self.save_patch = patch.object(main, "save_config")
        self.config_patch.start()
        self.save_patch.start()
        self.client = TestClient(main.app)
        self.headers = {"X-Sf2AiS-Token": self.token}

    def tearDown(self):
        self.client.close()
        self.config_patch.stop()
        self.save_patch.stop()
        self.temp.cleanup()

    def test_ai_token_is_authenticated_but_project_access_is_denied_by_default(self):
        response = self.client.get("/api/workspace/tree", headers=self.headers)
        self.assertEqual(response.status_code, 403)
        allowed = self.client.get("/api/workspace/tree", params={"path": "src"}, headers=self.headers)
        self.assertEqual(allowed.status_code, 200, allowed.text)
        paths = {entry["path"] for entry in allowed.json()["entries"]}
        self.assertIn("src/hello.py", paths)
        self.assertNotIn("src/private.txt", paths)
        private = self.client.get("/api/workspace/file", params={"path": "src/private.txt"}, headers=self.headers)
        self.assertEqual(private.status_code, 403)

    def test_read_write_upload_and_download_are_independent(self):
        read = self.client.get("/api/workspace/file", params={"path": "src/hello.py"}, headers=self.headers)
        self.assertEqual(read.status_code, 200)
        download = self.client.get("/api/workspace/download", params={"path": "src/hello.py"}, headers=self.headers)
        self.assertEqual(download.status_code, 403)
        write = self.client.put("/api/workspace/file", json={"path": "src/hello.py", "content": "changed"}, headers=self.headers)
        self.assertEqual(write.status_code, 403)

        self.client_record["permissions"]["write"] = True
        self.client_record["permissions"]["project_access"].update({"write": True, "download": True})
        private_write = self.client.put("/api/workspace/file", json={"path": "src/private.txt", "content": "bad"}, headers=self.headers)
        self.assertEqual(private_write.status_code, 403)
        write = self.client.put("/api/workspace/file", json={"path": "src/hello.py", "content": "changed"}, headers=self.headers)
        self.assertEqual(write.status_code, 200, write.text)
        download = self.client.get("/api/workspace/download", params={"path": "src/hello.py"}, headers=self.headers)
        self.assertEqual(download.status_code, 200)

        upload = self.client.post("/api/workspace/upload", data={"path": "src/upload.bin"},
                                  files={"file": ("upload.bin", b"abc", "application/octet-stream")},
                                  headers=self.headers)
        self.assertEqual(upload.status_code, 403)
        self.client_record["permissions"]["project_access"]["upload"] = True
        upload = self.client.post("/api/workspace/upload", data={"path": "src/upload.bin"},
                                  files={"file": ("upload.bin", b"abc", "application/octet-stream")},
                                  headers=self.headers)
        self.assertEqual(upload.status_code, 200, upload.text)

    def test_new_desktop_share_uses_per_identity_tokens_not_shared_passwords(self):
        folder = self.root / "new-project"
        response = self.client.post(
            "/api/desktop/shares",
            json={"folder": str(folder)},
            auth=("admin", "Admin-Pass-123!"),
        )
        self.assertEqual(response.status_code, 201, response.text)
        saved = next(item for item in self.config["shares"] if item["id"] == response.json()["share"]["id"])
        self.assertTrue(saved["legacy_auth_disabled"])
        self.assertNotIn("password_hash", saved)
        basic = self.client.get("/api/workspace/tree", auth=(saved["username"], "not-a-shared-password"))
        self.assertEqual(basic.status_code, 401)

    def test_new_ai_client_token_is_created_without_project_file_access(self):
        response = self.client.post(
            "/api/desktop/shares/share-1/clients",
            json={"name": "Fresh AI", "permissions": {"cli": False, "ide": False}},
            auth=("admin", "Admin-Pass-123!"),
        )
        self.assertEqual(response.status_code, 201, response.text)
        token = response.json()["token"]
        client = next(item for item in self.share["clients"] if item["name"] == "Fresh AI")
        self.assertFalse(client["permissions"]["project_access"]["read"])
        denied = self.client.get("/api/workspace/tree", headers={"X-Sf2AiS-Token": token})
        self.assertEqual(denied.status_code, 403)

    def test_admin_can_update_per_identity_path_rules(self):
        response = self.client.patch(
            "/api/desktop/shares/share-1/clients/client-1/project-access",
            json={"project_access": {"read": True, "write": False, "upload": False,
                                     "download": True, "deny": False,
                                     "rules": [{"path": "src/private.txt", "deny": True}]}},
            auth=("admin", "Admin-Pass-123!"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.client_record["permissions"]["read"])
        self.assertTrue(self.client_record["permissions"]["project_access"]["read"])
        invalid = self.client.patch(
            "/api/desktop/shares/share-1/clients/client-1/project-access",
            json={"project_access": {"rules": [{"path": "../outside", "read": True}]}},
            auth=("admin", "Admin-Pass-123!"),
        )
        self.assertEqual(invalid.status_code, 400)


if __name__ == "__main__":
    unittest.main()
