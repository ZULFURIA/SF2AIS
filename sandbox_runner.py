"""Docker-backed command runner. Never falls back to host-shell execution.

Each job receives a temporary, secret-filtered workspace snapshot. Only that
snapshot is mounted in the container; protected host files and .git metadata
are never mounted into an AI-controlled process.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import workspace as workspace_module

DEFAULT_IMAGE = "sf2ais-workbench:latest"

def docker_binary() -> str | None:
    configured = os.getenv("SF2AIS_DOCKER_BINARY")
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())
    located = shutil.which('docker')
    if located:
        return located
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
        if candidate.is_file():
            return str(candidate)
    return None

MAX_STAGE_FILES = 150_000
MAX_STAGE_BYTES = 2 * 1024 * 1024 * 1024


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _safe_walk(root: Path):
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root).as_posix()
        if rel_dir != "." and workspace_module.is_protected_path(rel_dir):
            dirs[:] = []
            continue
        kept = []
        for name in dirs:
            candidate = current_path / name
            rel = (Path(rel_dir) / name).as_posix() if rel_dir != "." else name
            if not _is_link(candidate) and not workspace_module.is_protected_path(rel):
                kept.append(name)
        dirs[:] = kept
        yield current_path, dirs, files


def _create_stage(root: Path, stage: Path) -> set[str]:
    """Create a safe hard-link snapshot; fall back to copies when hardlinks fail."""
    initial: set[str] = set()
    total_bytes = 0
    for current, dirs, files in _safe_walk(root):
        rel_dir = current.relative_to(root)
        if str(rel_dir) != ".":
            (stage / rel_dir).mkdir(parents=True, exist_ok=True)
        for name in files:
            source = current / name
            relative = (rel_dir / name).as_posix() if str(rel_dir) != "." else name
            if _is_link(source) or workspace_module.is_protected_path(relative):
                continue
            try:
                size = source.stat().st_size
            except OSError:
                continue
            total_bytes += size
            if len(initial) >= MAX_STAGE_FILES or total_bytes > MAX_STAGE_BYTES:
                raise RuntimeError("Share is too large for a safe CLI snapshot. Narrow the share root or reduce its contents.")
            destination = stage / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Never hard-link workspace files into the sandbox stage: writes to
            # a hard link would mutate the original host file before sync/approval.
            shutil.copy2(source, destination)
            initial.add(relative)
    return initial


def _safe_target(root: Path, relative: str) -> Path | None:
    if workspace_module.is_protected_path(relative):
        return None
    target = root / Path(relative)
    current = root
    for part in Path(relative).parts:
        current = current / part
        if _is_link(current):
            return None
    try:
        target.resolve(strict=False).relative_to(root)
    except ValueError:
        return None
    return target


def _sync_stage(root: Path, stage: Path, initial: set[str]) -> None:
    """Apply stage edits to the share while never following links or touching protected paths."""
    staged_files: set[str] = set()
    staged_dirs: set[str] = set()
    for current, dirs, files in _safe_walk(stage):
        rel_dir = current.relative_to(stage)
        if str(rel_dir) != ".":
            staged_dirs.add(rel_dir.as_posix())
        for name in files:
            source = current / name
            relative = (rel_dir / name).as_posix() if str(rel_dir) != "." else name
            if _is_link(source) or workspace_module.is_protected_path(relative):
                continue
            staged_files.add(relative)
            target = _safe_target(root, relative)
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                src_stat = source.stat()
                dst_stat = target.stat() if target.exists() else None
                if dst_stat and src_stat.st_size == dst_stat.st_size and src_stat.st_mtime_ns == dst_stat.st_mtime_ns:
                    continue
                fd, temp_name = tempfile.mkstemp(prefix=".sf2ais-sync-", suffix=".tmp", dir=str(target.parent))
                os.close(fd)
                try:
                    shutil.copy2(source, temp_name)
                    os.replace(temp_name, target)
                finally:
                    try:
                        os.unlink(temp_name)
                    except FileNotFoundError:
                        pass
            except FileNotFoundError:
                continue

    for relative in sorted(staged_dirs, key=lambda value: value.count("/")):
        target = _safe_target(root, relative)
        if target is not None:
            target.mkdir(parents=True, exist_ok=True)

    # Stage deletion is reflected only for regular, previously exposed files.
    for relative in initial - staged_files:
        target = _safe_target(root, relative)
        if target is not None and target.is_file() and not _is_link(target):
            try:
                target.unlink()
            except OSError:
                pass


def sandbox_status(image: str | None = None) -> dict[str, Any]:
    executable = docker_binary()
    if not executable:
        return {"available": False, "runner": "docker", "reason": "Docker is not installed or not on PATH. Host-shell execution is deliberately disabled."}
    image = image or os.getenv("SF2AIS_DOCKER_IMAGE", DEFAULT_IMAGE)
    try:
        daemon = subprocess.run([executable, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=5)
        if daemon.returncode != 0:
            return {"available": False, "runner": "docker", "image": image,
                    "reason": "Docker Engine is not running or is inaccessible. Start Docker Engine before enabling CLI."}
        result = subprocess.run([executable, "image", "inspect", image], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return {"available": False, "runner": "docker", "image": image,
                    "reason": "The Sf2AiS sandbox image is not installed. Build it with Scripts/build-sandbox.ps1 or Scripts/build-sandbox.sh."}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "runner": "docker", "image": image, "reason": "Docker is not ready: " + str(exc)}
    return {"available": True, "runner": "docker", "image": image,
            "reason": "Commands run in a restricted container with a secret-filtered workspace snapshot."}


def cleanup_orphaned_containers() -> dict[str, Any]:
    """Stop containers from a previous Sf2AiS process before accepting new work."""
    executable = docker_binary()
    if not executable:
        return {"cleaned": 0, "available": False}
    try:
        daemon = subprocess.run(
            [executable, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=2,
        )
        if daemon.returncode != 0:
            return {"cleaned": 0, "available": False}
        listed = subprocess.run(
            [executable, "ps", "-aq", "--filter", "label=com.sf2ais.managed=true"],
            capture_output=True, text=True, timeout=3,
        )
        if listed.returncode != 0:
            return {"cleaned": 0, "available": False}
        container_ids = [item.strip() for item in listed.stdout.splitlines() if item.strip()]
        if not container_ids:
            return {"cleaned": 0, "available": True}
        removed = subprocess.run(
            [executable, "rm", "-f", *container_ids[:100]],
            capture_output=True, text=True, timeout=30,
        )
        return {"cleaned": len(container_ids[:100]) if removed.returncode == 0 else 0,
                "available": removed.returncode == 0}
    except (OSError, subprocess.TimeoutExpired):
        return {"cleaned": 0, "available": False}


def build_docker_argv(share: dict[str, Any], command: str, cwd: Path, image: str | None = None, container_name: str | None = None, shell: str = "sh") -> list[str]:
    executable = docker_binary()
    if not executable:
        raise RuntimeError("Docker is unavailable. Host-shell execution is disabled for security.")
    image = image or os.getenv("SF2AIS_DOCKER_IMAGE", DEFAULT_IMAGE)
    root = Path(share["folder"]).resolve(strict=True)
    cwd = Path(cwd).resolve(strict=True)
    try:
        relative = cwd.relative_to(root)
    except ValueError:
        raise RuntimeError("Requested working directory is outside the share.")
    container_cwd = "/workspace" + ("/" + relative.as_posix() if str(relative) != "." else "")
    mount = "type=bind,source=%s,target=/workspace" % str(root)
    if shell not in ("sh", "bash"):
        raise RuntimeError("Only sh and bash are supported inside the isolated container.")
    shell_binary = "/bin/bash" if shell == "bash" else "/bin/sh"
    container_name = container_name or ("sf2ais-job-" + uuid.uuid4().hex[:16])
    return [
        executable, "run", "--rm", "--name", container_name,
        "--label", "com.sf2ais.managed=true", "--interactive=false",
        "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "128", "--memory", "1g", "--memory-swap", "1g",
        "--cpus", "2", "--ulimit", "nofile=1024:1024",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
        "--mount", mount, "--workdir", container_cwd,
        image, shell_binary, "-lc", command,
    ]


MAX_CAPTURE_BYTES = 200_000


def run_sandboxed(share: dict[str, Any], command: str, cwd: Path, timeout: int = 600,
                  shell: str = "sh", sync_changes: bool = True) -> dict[str, Any]:
    root = Path(share["folder"]).resolve(strict=True)
    cwd = Path(cwd).resolve(strict=True)
    relative_cwd = cwd.relative_to(root)
    container_name = "sf2ais-job-" + uuid.uuid4().hex[:16]
    executable = docker_binary()
    if not executable:
        return {"stdout": "", "stderr": "Docker is unavailable. Host-shell execution is disabled.", "exit_code": None, "status": "failed"}

    try:
        with tempfile.TemporaryDirectory(prefix=".sf2ais-stage-", dir=str(root.parent)) as stage_name:
            stage = Path(stage_name)
            initial = _create_stage(root, stage)
            staged_cwd = stage / relative_cwd
            if not staged_cwd.exists():
                raise RuntimeError("Requested working directory is not present in the safe workspace snapshot.")
            staged_share = dict(share)
            staged_share["folder"] = str(stage)
            argv = build_docker_argv(staged_share, command, staged_cwd, container_name=container_name, shell=shell)
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            buffers = {"stdout": bytearray(), "stderr": bytearray()}
            truncated = {"stdout": False, "stderr": False}

            def drain(pipe, key):
                while True:
                    chunk = pipe.read(8192)
                    if not chunk:
                        break
                    remaining = MAX_CAPTURE_BYTES - len(buffers[key])
                    if remaining > 0:
                        buffers[key].extend(chunk[:remaining])
                    if len(chunk) > max(remaining, 0):
                        truncated[key] = True

            readers = [
                threading.Thread(target=drain, args=(proc.stdout, "stdout"), daemon=True),
                threading.Thread(target=drain, args=(proc.stderr, "stderr"), daemon=True),
            ]
            for reader in readers:
                reader.start()
            status = "completed"
            try:
                exit_code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                status = "timeout"
                try:
                    subprocess.run([executable, "kill", container_name], capture_output=True, timeout=10)
                except Exception:
                    pass
                try:
                    subprocess.run([executable, "rm", "-f", container_name], capture_output=True, timeout=10)
                except Exception:
                    pass
                try:
                    proc.kill()
                except OSError:
                    pass
                proc.wait(timeout=10)
                exit_code = None
            for reader in readers:
                reader.join(timeout=10)
            stdout = buffers["stdout"].decode(errors="replace")
            stderr = buffers["stderr"].decode(errors="replace")
            if truncated["stdout"]:
                stdout += "\\n[stdout truncated at 200 KB]"
            if truncated["stderr"]:
                stderr += "\\n[stderr truncated at 200 KB]"
            if status == "timeout":
                stderr += "\\n[container stopped: job timeout]"
            outcome = {"stdout": stdout, "stderr": stderr, "exit_code": exit_code, "status": status}
            sync_applied = bool(sync_changes and status == "completed" and exit_code == 0)
            if sync_applied:
                _sync_stage(root, stage, initial)
            outcome["workspace_sync_enabled"] = bool(sync_changes)
            outcome["workspace_sync"] = "applied" if sync_applied else "discarded"
            return outcome
    except Exception as exc:
        return {"stdout": "", "stderr": str(exc), "exit_code": None, "status": "failed"}
