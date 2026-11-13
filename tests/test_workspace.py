import tempfile
import unittest
from pathlib import Path

import workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.share = {"folder": str(self.root)}
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=secret", encoding="utf-8")
        (self.root / "data").mkdir()
        (self.root / "data" / "config.json").write_text('{"password":"secret"}', encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_tree_lists_nested_source_but_hides_secrets_and_git(self):
        (self.root / ".git").mkdir()
        result = workspace.list_directory(self.share, "", depth=3)
        paths = {entry["path"] for entry in result["entries"]}
        self.assertIn("src", paths)
        self.assertIn("src/app.py", paths)
        self.assertNotIn(".env", paths)
        self.assertNotIn(".git", paths)
        self.assertNotIn("data/config.json", paths)

    def test_read_and_atomic_write(self):
        result = workspace.read_text_file(self.share, "src/app.py")
        self.assertEqual(result["content"].replace("\r\n", "\n"), "print('hello')\n")
        saved = workspace.write_text_file(self.share, "src/app.py", "print('updated')\n")
        self.assertTrue(saved["saved"])
        self.assertEqual((self.root / "src" / "app.py").read_text(encoding="utf-8"), "print('updated')\n")

    def test_rejects_control_characters_in_paths(self):
        with self.assertRaises(workspace.WorkspaceError):
            workspace._normalise_relative("src/" + chr(0) + "bad.py")

    def test_rejects_parent_and_absolute_paths(self):
        for path in ("../outside.txt", "/etc/passwd", "C:/Windows/win.ini", "src/../../outside"):
            with self.subTest(path=path), self.assertRaises(workspace.WorkspaceError):
                workspace.resolve_path(self.share, path)

    def test_rejects_protected_secrets(self):
        for path in (".env", ".envrc", ".git/config", "SF2AIS/data/config.json", "data/config.json", "private/id_rsa", "certs/client.pem"):
            with self.subTest(path=path), self.assertRaises(workspace.WorkspaceError):
                workspace.resolve_path(self.share, path)

    def test_rejects_symlink_escape(self):
        outside = self.root.parent / (self.root.name + "-outside.txt")
        outside.write_text("private", encoding="utf-8")
        link = self.root / "outside-link"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation is unavailable in this environment.")
        try:
            with self.assertRaises(workspace.WorkspaceError):
                workspace.resolve_path(self.share, "outside-link")
        finally:
            outside.unlink(missing_ok=True)

    def test_create_move_and_delete(self):
        workspace.create_directory(self.share, "new-folder")
        (self.root / "new-folder" / "a.txt").write_text("x", encoding="utf-8")
        moved = workspace.move_path(self.share, "new-folder/a.txt", "src/moved.txt")
        self.assertTrue(moved["moved"])
        self.assertTrue((self.root / "src" / "moved.txt").exists())
        deleted = workspace.delete_path(self.share, "src/moved.txt")
        self.assertTrue(deleted["deleted"])
        self.assertFalse((self.root / "src" / "moved.txt").exists())

    def test_rejects_binary_and_oversized_files(self):
        (self.root / "binary.dat").write_bytes(bytes([97, 0, 98]))
        with self.assertRaises(workspace.WorkspaceError):
            workspace.read_text_file(self.share, "binary.dat")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.write_text_file(self.share, "large.txt", "x" * (workspace.MAX_TEXT_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
