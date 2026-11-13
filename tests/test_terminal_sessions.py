import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import terminal_sessions


class FakeProcess:
    def __init__(self, output=b"shell ready\n"):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(output)
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self):
        self.returncode = -9


class TerminalSessionTests(unittest.TestCase):
    def test_output_cursor_and_bounded_input(self):
        manager = terminal_sessions.TerminalSessionManager()
        process = FakeProcess()
        session = terminal_sessions.TerminalSession(
            "session-1", "share-1", "client:1", "container-1",
            Path(tempfile.gettempdir()), set(), process
        )
        manager.sessions[session.id] = session
        manager._append(session, b"first\n")
        first = manager.read(session, 0)
        self.assertEqual(first["events"][0]["data"], "first\n")
        self.assertEqual(manager.read(session, first["next"])["events"], [])
        manager.write(session, "pwd\n")
        self.assertEqual(process.stdin.getvalue(), b"pwd\n")
        with self.assertRaises(terminal_sessions.TerminalSessionError):
            manager.write(session, "x" * (terminal_sessions.MAX_INPUT_BYTES + 1))

    def test_output_buffer_is_bounded_and_reports_truncation(self):
        manager = terminal_sessions.TerminalSessionManager()
        session = terminal_sessions.TerminalSession(
            "session-1", "share-1", "client:1", "container-1",
            Path(tempfile.gettempdir()), set(), FakeProcess()
        )
        manager._append(session, b"x" * (terminal_sessions.MAX_OUTPUT_BYTES + 1))
        result = manager.read(session, 0)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["events"], [])
        self.assertLessEqual(session.output_bytes, terminal_sessions.MAX_OUTPUT_BYTES)

    def test_session_owner_and_share_are_both_required(self):
        manager = terminal_sessions.TerminalSessionManager()
        session = terminal_sessions.TerminalSession(
            "session-1", "share-1", "client:1", "container-1",
            Path(tempfile.gettempdir()), set(), FakeProcess()
        )
        manager.sessions[session.id] = session
        self.assertIs(manager.get("session-1", "share-1", "client:1"), session)
        for share_id, owner_id in (("share-2", "client:1"), ("share-1", "client:2")):
            with self.assertRaises(terminal_sessions.TerminalSessionError):
                manager.get("session-1", share_id, owner_id)

    def test_start_builds_interactive_isolated_shell_with_independent_snapshot(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            (root / "project.txt").write_text("original", encoding="utf-8")
            manager = terminal_sessions.TerminalSessionManager()
            fake = FakeProcess()
            with patch.object(terminal_sessions.sandbox_runner, "sandbox_status",
                              return_value={"available": True}), \
                 patch.object(terminal_sessions.sandbox_runner, "build_docker_argv",
                              return_value=["docker", "run", "--rm", "--interactive=false",
                                            "--network", "none", "image", "/bin/sh", "-lc", ""]), \
                 patch.object(terminal_sessions.subprocess, "Popen", return_value=fake) as popen:
                session = manager.start({"id": "share-1", "folder": str(root)}, root, "basic:share-1")
                args = popen.call_args.args[0]
                self.assertIn("-i", args)
                self.assertNotIn("--interactive=false", args)
                self.assertEqual(args[-1:], ["/bin/sh"])
                self.assertEqual((root / "project.txt").read_text(encoding="utf-8"), "original")
                deadline = time.time() + 3
                while not session.finalized and time.time() < deadline:
                    time.sleep(0.02)
                self.assertTrue(session.finalized)
                self.assertEqual(session.status, "exited")
                self.assertEqual((root / "project.txt").read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
