"""Explicit, scoped Git write operations for Sf2AiS workspaces."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

import workspace

MAX_PATHS = 100
MAX_COMMIT_MESSAGE = 200


class GitWorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _repo(share: dict[str, Any]) -> tuple[Path, str]:
    root = Path(share["folder"]).expanduser().resolve(strict=True)
    if not root.is_dir() or not (root / ".git").exists():
        raise GitWorkflowError("This share is not a Git working tree.", 404)
    git = shutil.which("git")
    if not git:
        raise GitWorkflowError("Git is not installed on the server.", 503)
    return root, git


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
    })
    return env


def _run(root: Path, git: str, args: list[str], timeout: int = 20) -> str:
    try:
        result = subprocess.run(
            [git, "-C", str(root), "-c", "core.hooksPath=" + os.devnull,
             "-c", "commit.gpgSign=false", *args],
            capture_output=True, text=True, timeout=timeout, env=_env(),
        )
    except subprocess.TimeoutExpired:
        raise GitWorkflowError("Git operation timed out.", 504)
    if result.returncode:
        detail = (result.stderr or result.stdout or "Git operation failed.").strip()
        raise GitWorkflowError(detail[:1200], 409)
    return result.stdout[:12000]


def stage_files(share: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    if not isinstance(paths, list) or not paths or len(paths) > MAX_PATHS:
        raise GitWorkflowError("Provide between 1 and 100 explicit file paths.")
    root, git = _repo(share)
    safe_paths: list[str] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise GitWorkflowError("Every staged path must be a non-empty string.")
        rel = workspace._normalise_relative(raw)
        if not rel or workspace.is_protected_path(rel):
            raise GitWorkflowError("Protected or workspace-root paths cannot be staged.", 403)
        target = workspace.resolve_path(share, rel, allow_root=False)
        if not target.exists() or not target.is_file():
            raise GitWorkflowError("Only existing regular files can be staged: " + rel, 400)
        safe_paths.append(rel)
    if len(set(safe_paths)) != len(safe_paths):
        raise GitWorkflowError("Duplicate paths are not allowed.")
    output = _run(root, git, ["add", "--", *safe_paths])
    return {"staged": safe_paths, "output": output}


def commit_staged(share: dict[str, Any], message: str) -> dict[str, Any]:
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_COMMIT_MESSAGE:
        raise GitWorkflowError("Commit message must contain 1 to 200 characters.")
    root, git = _repo(share)
    staged = _run(root, git, ["diff", "--cached", "--name-only", "-z"])
    staged_paths = [item for item in staged.split(chr(0)) if item]
    if not staged_paths:
        raise GitWorkflowError("There are no staged changes to commit.", 409)
    protected = [item for item in staged_paths if workspace.is_protected_path(item)]
    if protected:
        raise GitWorkflowError("Commit blocked because protected paths are staged: " + ", ".join(protected[:10]), 403)
    output = _run(root, git, ["commit", "--no-verify", "-m", message.strip()], timeout=45)
    head = _run(root, git, ["rev-parse", "--short", "HEAD"]).strip()
    return {"committed": True, "commit": head, "output": output}


def push_branch(share: dict[str, Any], remote: str, branch: str) -> dict[str, Any]:
    if not isinstance(remote, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", remote):
        raise GitWorkflowError("Remote name is invalid.")
    if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", branch):
        raise GitWorkflowError("Branch name is invalid.")
    if branch.startswith("-") or ".." in branch or branch.endswith("/") or "//" in branch:
        raise GitWorkflowError("Branch name is invalid.")
    root, git = _repo(share)
    _run(root, git, ["check-ref-format", "--branch", branch])
    remotes = _run(root, git, ["remote"]).splitlines()
    if remote not in remotes:
        raise GitWorkflowError("The requested Git remote does not exist.", 404)
    remote_url = _run(root, git, ["remote", "get-url", "--", remote]).strip()
    parsed = urlsplit(remote_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise GitWorkflowError("Git push is limited to HTTPS remotes without embedded credentials.", 403)
    output = _run(root, git, ["push", "--porcelain", remote, "HEAD:refs/heads/" + branch], timeout=90)
    return {"pushed": True, "remote": remote, "branch": branch, "output": output}


def staged_changes(share: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded review of staged files and their patch."""
    root, git = _repo(share)
    raw = _run(root, git, ["diff", "--cached", "--name-only", "-z"])
    paths = [item for item in raw.split(chr(0)) if item]
    visible = [item for item in paths if not workspace.is_protected_path(item)]
    hidden_count = len(paths) - len(visible)
    diff = _run(root, git, ["diff", "--cached", "--no-ext-diff", "--no-color", "--", *visible], timeout=20) if visible else ""
    return {"files": visible[:100], "hidden_protected_count": hidden_count,
            "diff": diff[:20000], "truncated": len(diff) > 20000,
            "file_count": len(visible)}


def list_branches(share: dict[str, Any]) -> dict[str, Any]:
    """Return local and remote branch metadata without changing checkout state."""
    root, git = _repo(share)
    current = _run(root, git, ["branch", "--show-current"]).strip()
    raw = _run(root, git, ["for-each-ref", "--format=%(refname)%1f%(objectname:short)%1f%(subject)", "refs/heads", "refs/remotes"])
    branches = []
    for line in raw.splitlines():
        parts = line.split(chr(31), 2)
        if len(parts) != 3:
            continue
        refname, commit, subject = parts
        if refname.endswith("/HEAD"):
            continue
        remote = refname.startswith("refs/remotes/")
        prefix = "refs/remotes/" if remote else "refs/heads/"
        name = refname[len(prefix):] if refname.startswith(prefix) else refname
        branches.append({"name": name, "commit": commit, "subject": subject[:240],
                         "current": not remote and name == current, "remote": remote})
    branches.sort(key=lambda item: (not item["current"], item["remote"], item["name"].casefold()))
    return {"current": current or None, "branches": branches[:200]}


def recent_commits(share: dict[str, Any], limit: int = 20) -> dict[str, Any]:
    """Return a bounded, read-only recent commit list for the current branch."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise GitWorkflowError("Commit history limit must be between 1 and 50.")
    root, git = _repo(share)
    fmt = "%H%x1f%h%x1f%an%x1f%aI%x1f%s"
    raw = _run(root, git, ["log", "-n", str(limit), "--format=" + fmt, "--no-show-signature"])
    commits = []
    for line in raw.splitlines():
        parts = line.split(chr(31), 4)
        if len(parts) != 5:
            continue
        full_hash, short_hash, author, authored_at, subject = parts
        commits.append({"hash": full_hash, "short_hash": short_hash,
                        "author": author[:120], "date": authored_at[:40], "subject": subject[:240]})
    return {"commits": commits}
