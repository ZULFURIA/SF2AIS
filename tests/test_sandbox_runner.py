import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sandbox_runner


class SandboxRunnerTests(unittest.TestCase):
    def test_no_docker_means_unavailable(self):
        with patch.object(sandbox_runner, "docker_binary", return_value=None):
            status = sandbox_runner.sandbox_status()
        self.assertFalse(status["available"])
        self.assertIn("Host-shell", status["reason"])

    def test_orphan_cleanup_is_safe_when_docker_is_missing(self):
        with patch.object(sandbox_runner, "docker_binary", return_value=None):
            result = sandbox_runner.cleanup_orphaned_containers()
        self.assertEqual(result, {"cleaned": 0, "available": False})

    def test_container_arguments_are_restricted(self):
        with tempfile.TemporaryDirectory() as root:
            share = {"folder": root}
            with patch.object(sandbox_runner.shutil, "which", return_value="docker"):
                args = sandbox_runner.build_docker_argv(share, "npm test", Path(root))
        joined = " ".join(args)
        with tempfile.TemporaryDirectory() as root:
            share = {"folder": root}
            with patch.object(sandbox_runner.shutil, "which", return_value="docker"):
                bash_args = sandbox_runner.build_docker_argv(share, "echo ok", Path(root), shell="bash")
        self.assertEqual(bash_args[-4:], ["sf2ais-workbench:latest", "/bin/bash", "-lc", "echo ok"])
        for required in ("--network none", "--read-only", "--cap-drop ALL",
                         "no-new-privileges", "--pids-limit 128",
                         "--memory 1g", "--cpus 2", "target=/workspace",
                         "com.sf2ais.managed=true"):
            self.assertIn(required, joined)
        self.assertNotIn("/var/run/docker.sock", joined)

    def test_stage_excludes_secrets_and_git_and_syncs_workspace_changes(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            (root / "src").mkdir()
            (root / "src" / "keep.txt").write_text("original", encoding="utf-8")
            (root / "src" / "remove.txt").write_text("remove", encoding="utf-8")
            (root / ".env").write_text("SECRET=hidden", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("[remote]", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "package.json").write_text("{}", encoding="utf-8")
            stage = root.parent / (root.name + "-stage")
            stage.mkdir()
            try:
                initial = sandbox_runner._create_stage(root, stage)
                # The snapshot must be independent: edits in the sandbox cannot
                # alter the original host workspace before explicit sync.
                (stage / "src" / "keep.txt").write_text("stage-only", encoding="utf-8")
                self.assertEqual((root / "src" / "keep.txt").read_text(encoding="utf-8"), "original")
                (stage / "src" / "keep.txt").write_text("original", encoding="utf-8")
                self.assertIn("src/keep.txt", initial)
                self.assertNotIn(".env", initial)
                self.assertNotIn(".git/config", initial)
                self.assertNotIn("node_modules/package.json", initial)
                (stage / "src" / "keep.txt").write_text("changed", encoding="utf-8")
                (stage / "src" / "remove.txt").unlink()
                (stage / "src" / "new.txt").write_text("new", encoding="utf-8")
                sandbox_runner._sync_stage(root, stage, initial)
                self.assertEqual((root / "src" / "keep.txt").read_text(encoding="utf-8"), "changed")
                self.assertFalse((root / "src" / "remove.txt").exists())
                self.assertEqual((root / "src" / "new.txt").read_text(encoding="utf-8"), "new")
                self.assertEqual((root / ".env").read_text(encoding="utf-8"), "SECRET=hidden")
            finally:
                import shutil
                shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
