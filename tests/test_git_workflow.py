import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import git_workflow


class GitWorkflowTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("Git is not installed")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.share = {"folder": str(self.root)}
        self.run_git("init", "-b", "main")
        self.run_git("config", "user.name", "Sf2AiS Test")
        self.run_git("config", "user.email", "sf2ais-test@example.invalid")
        (self.root / "README.md").write_text("initial\n", encoding="utf-8")
        self.run_git("add", "README.md")
        self.run_git("commit", "-m", "initial")
        (self.root / "README.md").write_text("changed\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def run_git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.root, check=True,
                              capture_output=True, text=True).stdout

    def test_stage_only_explicit_regular_files_and_commit(self):
        staged = git_workflow.stage_files(self.share, ["README.md"])
        self.assertEqual(staged["staged"], ["README.md"])
        committed = git_workflow.commit_staged(self.share, "update readme")
        self.assertTrue(committed["committed"])
        self.assertTrue(committed["commit"])
        self.assertIn("update readme", self.run_git("log", "-1", "--pretty=%s"))

    def test_protected_and_directory_paths_are_rejected(self):
        (self.root / ".env").write_text("SECRET=x", encoding="utf-8")
        with self.assertRaises(git_workflow.GitWorkflowError):
            git_workflow.stage_files(self.share, [".env"])
        with self.assertRaises(git_workflow.GitWorkflowError):
            git_workflow.stage_files(self.share, ["."])

    def test_commit_requires_staged_changes(self):
        with self.assertRaises(git_workflow.GitWorkflowError):
            git_workflow.commit_staged(self.share, "nothing to commit")

    def test_commit_refuses_protected_paths_already_in_index(self):
        (self.root / ".env").write_text("SECRET=value", encoding="utf-8")
        self.run_git("add", ".env")
        with self.assertRaises(git_workflow.GitWorkflowError):
            git_workflow.commit_staged(self.share, "must not commit secret")

    def test_push_requires_https_remote_and_named_branch(self):
        bare = self.root.parent / (self.root.name + "-remote.git")
        subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                       capture_output=True, text=True)
        self.run_git("remote", "add", "origin", str(bare))
        with self.assertRaises(git_workflow.GitWorkflowError):
            git_workflow.push_branch(self.share, "origin", "main")
        with self.assertRaises(git_workflow.GitWorkflowError):
            git_workflow.push_branch(self.share, "bad remote", "main")

    def test_staged_changes_returns_reviewable_patch_and_hides_protected_paths(self):
        (self.root / ".env").write_text("SECRET=value", encoding="utf-8")
        self.run_git("add", "README.md", ".env")
        result = git_workflow.staged_changes(self.share)
        self.assertEqual(result["files"], ["README.md"])
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["hidden_protected_count"], 1)
        self.assertIn("+changed", result["diff"])
        self.assertNotIn("SECRET", result["diff"])

    def test_lists_local_and_remote_branches_without_confusing_slash_names(self):
        self.run_git("branch", "feature/ui")
        self.run_git("update-ref", "refs/remotes/origin/release/v1", "HEAD")
        result = git_workflow.list_branches(self.share)
        self.assertEqual(result["current"], "main")
        by_name = {(item["name"], item["remote"]): item for item in result["branches"]}
        self.assertTrue(by_name[("main", False)]["current"])
        self.assertIn(("feature/ui", False), by_name)
        self.assertIn(("origin/release/v1", True), by_name)

    def test_recent_commits_are_bounded_and_have_metadata(self):
        result = git_workflow.recent_commits(self.share, 1)
        self.assertEqual(len(result["commits"]), 1)
        self.assertEqual(result["commits"][0]["subject"], "initial")
        self.assertTrue(result["commits"][0]["hash"])
        for invalid in (0, 51, True, "10"):
            with self.assertRaises(git_workflow.GitWorkflowError):
                git_workflow.recent_commits(self.share, invalid)
