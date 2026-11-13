import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import main


class WorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "hello.py").write_text("print('hello')\n", encoding="utf-8")
        (self.root / ".env").write_text("SECRET=value", encoding="utf-8")
        self.share = {
            "id": "share-1", "username": "tester",
            "password_hash": main.bcrypt.hash("Share-Pass-123!"),
            "folder": str(self.root), "last_seen": None,
            "cli_enabled": True, "tunnel_enabled": True, "workspace_write_enabled": False,
        }
        self.config = {
            "admin": {"username": "admin", "password_hash": main.bcrypt.hash("Admin-Pass-123!")},
            "network": {"method": "static", "value": "127.0.0.1", "port": 8000},
            "shares": [self.share],
        }
        self.config_patch = patch.object(main, "load_config", side_effect=lambda: self.config)
        self.save_patch = patch.object(main, "save_config")
        self.sandbox_patch = patch.object(main.sandbox_runner, "sandbox_status",
                                           return_value={"available": False, "reason": "Docker Engine is unavailable."})
        self.config_patch.start()
        self.save_patch.start()
        self.sandbox_patch.start()
        self.client = TestClient(main.app)
        self.auth = ("tester", "Share-Pass-123!")

    def tearDown(self):
        self.client.close()
        self.config_patch.stop()
        self.save_patch.stop()
        self.sandbox_patch.stop()
        self.temp.cleanup()

    def test_dashboard_is_an_authenticated_compatibility_redirect(self):
        self.share["username"] = "<script>alert(1)</script>"
        self.config["network"]["value"] = "<img src=x onerror=alert(1)>"
        response = self.client.get("/dashboard", auth=("admin", "Admin-Pass-123!"), follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers.get("location"), "/workspace")
        self.assertNotIn("<script>alert(1)</script>", response.text)
        self.assertNotIn("<img src=x", response.text)
        realtime = self.client.get("/dashboard?view=realtime", auth=("admin", "Admin-Pass-123!"), follow_redirects=False)
        self.assertEqual(realtime.status_code, 307)
        self.assertEqual(realtime.headers.get("location"), "/workspace#monitor")

    def test_workbench_requires_share_auth(self):
        response = self.client.get("/workbench")
        self.assertEqual(response.status_code, 401)
        response = self.client.get("/workbench", auth=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Remote Workbench", response.text)
        self.assertIn("upload-file", response.text)
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_no_javascript_browse_and_edit_forms(self):
        listing = self.client.get("/browse", auth=self.auth)
        self.assertEqual(listing.status_code, 200)
        self.assertIn("No JavaScript required", listing.text)
        file_page = self.client.get("/browse/file", params={"path": "src/hello.py"}, auth=self.auth)
        self.assertEqual(file_page.status_code, 200)
        self.assertIn("<pre", file_page.text)
        denied = self.client.post("/browse/save", data={"path": "src/hello.py", "content": "changed"}, auth=self.auth)
        self.assertEqual(denied.status_code, 403)
        self.share["workspace_write_enabled"] = True
        editable_page = self.client.get("/browse/file", params={"path": "src/hello.py"}, auth=self.auth)
        self.assertIn("textarea", editable_page.text)
        saved = self.client.post("/browse/save", data={"path": "src/hello.py", "content": "changed"}, auth=self.auth)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual((self.root / "src" / "hello.py").read_text(encoding="utf-8"), "changed")

    def test_workspace_tree_and_read(self):
        response = self.client.get("/api/workspace/tree", auth=self.auth)
        self.assertEqual(response.status_code, 200)
        paths = {entry["path"] for entry in response.json()["entries"]}
        self.assertIn("src/hello.py", paths)
        self.assertNotIn(".env", paths)
        response = self.client.get("/api/workspace/file", params={"path": "src/hello.py"}, auth=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertIn("hello", response.json()["content"])

    def test_write_requires_admin_enabled_permission(self):
        denied = self.client.put("/api/workspace/file", json={"path": "src/hello.py", "content": "changed"}, auth=self.auth)
        self.assertEqual(denied.status_code, 403)
        self.share["workspace_write_enabled"] = True
        allowed = self.client.put("/api/workspace/file", json={"path": "src/hello.py", "content": "changed"}, auth=self.auth)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual((self.root / "src" / "hello.py").read_text(encoding="utf-8"), "changed")

    def test_upload_and_download_binary_file(self):
        self.share["workspace_write_enabled"] = True
        response = self.client.post(
            "/api/workspace/upload",
            data={"path": "assets/logo.bin"},
            files={"file": ("logo.bin", bytes([0, 1, 2]), "application/octet-stream")},
            auth=self.auth,
        )
        self.assertEqual(response.status_code, 200, response.text)
        downloaded = self.client.get("/api/workspace/download", params={"path": "assets/logo.bin"}, auth=self.auth)
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, bytes([0, 1, 2]))

    def test_remote_http_requires_tls_for_authenticated_api(self):
        with TestClient(main.app, client=("203.0.113.9", 12345)) as remote:
            response = remote.get("/api/workspace/status", auth=self.auth)
            self.assertEqual(response.status_code, 426)
            probe = remote.post("/api/ip-update", json={})
            self.assertEqual(probe.status_code, 426)

    def test_cross_origin_state_change_is_rejected(self):
        response = self.client.put("/api/workspace/file", json={"path": "src/hello.py", "content": "bad"},
                                   headers={"Origin": "https://attacker.example"}, auth=self.auth)
        self.assertEqual(response.status_code, 403)

    def test_secret_file_and_path_traversal_denied(self):
        for path in (".env", "../outside.txt"):
            response = self.client.get("/api/workspace/file", params={"path": path}, auth=self.auth)
            self.assertIn(response.status_code, (403, 404))

    def test_workspace_operations_write_jsonl_audit_events(self):
        audit_path = self.root / "audit.jsonl"
        with patch.object(main, "AUDIT_PATH", audit_path):
            response = self.client.get("/api/workspace/tree", auth=self.auth)
        self.assertEqual(response.status_code, 200)
        lines = audit_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        event = __import__("json").loads(lines[0])
        self.assertEqual(event["action"], "workspace.list")
        self.assertNotIn("content", event)

    def test_legacy_file_endpoint_rejects_dotfiles(self):
        response = self.client.get("/files/download/.env", auth=self.auth)
        self.assertEqual(response.status_code, 403)

    def test_unisolated_tunnel_is_rejected(self):
        response = self.client.post("/tunnel/open", json={"local_port": 3000}, auth=self.auth)
        self.assertEqual(response.status_code, 403)
        self.assertIn("isolated mode", response.json()["detail"])

    def test_cli_refuses_host_shell_when_sandbox_unavailable(self):
        response = self.client.post("/cli/jobs", json={"command": "whoami", "shell": "bash"}, auth=self.auth)
        self.assertEqual(response.status_code, 503)
        self.assertIn("Docker", response.json()["detail"])
        browser_form = self.client.post("/browse/command", data={"command": "whoami", "cwd": ""}, auth=self.auth)
        self.assertEqual(browser_form.status_code, 503)
        browser_terminal = self.client.get("/browse/terminal", auth=self.auth)
        self.assertEqual(browser_terminal.status_code, 200)
        self.assertIn("terminal unavailable", browser_terminal.text.lower())
        browser_terminal_start = self.client.post("/browse/terminal/start", data={"cwd": ""}, auth=self.auth)
        self.assertEqual(browser_terminal_start.status_code, 503)

    def test_persistent_terminal_session_api_lifecycle(self):
        from types import SimpleNamespace
        session = SimpleNamespace(id="term-1", status="running", exit_code=None)
        output = {"session_id": "term-1", "events": [{"seq": 1, "data": "ready\n"}],
                  "next": 1, "truncated": False, "status": "running",
                  "exit_code": None, "error": None}
        with patch.object(main.sandbox_runner, "sandbox_status",
                          return_value={"available": True}), \
             patch.object(main.TERMINAL_SESSIONS, "start", return_value=session) as start, \
             patch.object(main.TERMINAL_SESSIONS, "get", return_value=session), \
             patch.object(main.TERMINAL_SESSIONS, "write") as write, \
             patch.object(main.TERMINAL_SESSIONS, "read", return_value=output), \
             patch.object(main.TERMINAL_SESSIONS, "close") as close:
            created = self.client.post("/cli/sessions", json={"cwd": ""}, auth=self.auth)
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()["mode"], "line-oriented")
            self.assertEqual(start.call_args.args[2], "basic:share-1")

            sent = self.client.post("/cli/sessions/term-1/input",
                                    json={"data": "pwd\n"}, auth=self.auth)
            self.assertEqual(sent.status_code, 200, sent.text)
            write.assert_called_once_with(session, "pwd\n")

            received = self.client.get("/cli/sessions/term-1/output?after=0&wait=0",
                                       auth=self.auth)
            self.assertEqual(received.status_code, 200)
            self.assertEqual(received.json()["events"][0]["data"], "ready\n")

            ended = self.client.delete("/cli/sessions/term-1", auth=self.auth)
            self.assertEqual(ended.status_code, 200)
            close.assert_called_once_with(session, reason="closed by client")

    def test_terminal_session_endpoint_rejects_owner_mismatch(self):
        from types import SimpleNamespace
        session = SimpleNamespace(id="term-1", status="running", exit_code=None)
        with patch.object(main.sandbox_runner, "sandbox_status",
                          return_value={"available": True}), \
             patch.object(main.TERMINAL_SESSIONS, "start", return_value=session):
            created = self.client.post("/cli/sessions", json={"cwd": ""}, auth=self.auth)
            self.assertEqual(created.status_code, 201)
        with patch.object(main.TERMINAL_SESSIONS, "get",
                          side_effect=main.TerminalSessionError("Terminal session not found.", 404)):
            response = self.client.get("/cli/sessions/term-1/output", auth=("another", "Wrong-Pass-123!"))
            self.assertEqual(response.status_code, 401)

    def test_read_only_git_status(self):
        subprocess.run(["git", "init", str(self.root)], check=True, capture_output=True)
        response = self.client.get("/api/workspace/git/status", auth=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("##", response.json()["status"])
        self.assertNotIn(".env", response.json()["status"])


if __name__ == "__main__":
    unittest.main()
