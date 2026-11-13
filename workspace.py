"""Safe, share-scoped workspace filesystem operations for Sf2AiS."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_LIST_ENTRIES = 500
MAX_TREE_DEPTH = 5
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".next",
}
PROTECTED_NAMES = {
    ".env", ".env.local", ".env.production", ".npmrc", ".pypirc", ".netrc",
    "id_rsa", "id_ed25519", "authorized_keys", "credentials", "credentials.json",
    "secrets", "secrets.json", ".aws", ".ssh", ".kube", ".docker",
}
PROTECTED_SUFFIXES = {".pem", ".p12", ".pfx", ".key", ".kdb", ".keystore"}


class WorkspaceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _normalise_relative(value: str | None) -> str:
    value = (value or "").strip().replace("\\", "/")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise WorkspaceError("Control characters are not allowed in workspace paths.", 400)
    if value in ("", "."):
        return ""
    p = PurePosixPath(value)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        raise WorkspaceError("Path must be relative to the shared workspace.", 403)
    if any(":" in part for part in p.parts):
        raise WorkspaceError("Drive-qualified paths are not allowed.", 403)
    return p.as_posix()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def is_protected_path(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    for part in parts:
        lower = part.lower()
        if lower in PROTECTED_NAMES or lower in EXCLUDED_DIRS or lower.startswith(".env"):
            return True
        if Path(lower).suffix in PROTECTED_SUFFIXES:
            return True
    if len(parts) >= 2 and any(part.lower() == "data" for part in parts[:-1]) and parts[-1].lower() in {"config.json", "config.yaml", "config.yml"}:
        return True
    return False


def resolve_path(share: dict[str, Any], relative: str | None = None, *, allow_root: bool = True) -> Path:
    base = Path(share["folder"]).expanduser().resolve(strict=True)
    if not base.is_dir():
        raise WorkspaceError("The configured share is not a directory.", 404)
    rel = _normalise_relative(relative)
    if not rel and not allow_root:
        raise WorkspaceError("A file or directory path is required.", 400)
    if rel and is_protected_path(rel):
        raise WorkspaceError("This path is protected and is not available to AI clients.", 403)

    candidate = base
    for part in PurePosixPath(rel).parts:
        candidate = candidate / part
        if _is_link(candidate):
            raise WorkspaceError("Symbolic links are not accessible through the workspace API.", 403)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base)
    except ValueError:
        raise WorkspaceError("Path escapes the shared workspace.", 403)
    return resolved


def list_directory(share: dict[str, Any], relative: str = "", *, depth: int = 2) -> dict[str, Any]:
    root = resolve_path(share, relative)
    if not root.exists() or not root.is_dir():
        raise WorkspaceError("Directory not found.", 404)
    depth = max(1, min(int(depth), MAX_TREE_DEPTH))
    entries: list[dict[str, Any]] = []
    truncated = False

    def walk(folder: Path, prefix: str, level: int) -> None:
        nonlocal truncated
        try:
            children = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
        except OSError as exc:
            raise WorkspaceError("Unable to read directory: " + str(exc), 403)
        for child in children:
            if len(entries) >= MAX_LIST_ENTRIES:
                truncated = True
                return
            rel = (prefix + "/" + child.name).strip("/")
            if child.name.startswith(".") or child.name.lower() in EXCLUDED_DIRS or is_protected_path(rel):
                continue
            if _is_link(child):
                continue
            try:
                stat = child.stat()
            except OSError:
                continue
            is_dir = child.is_dir()
            entries.append({
                "name": child.name,
                "path": rel,
                "type": "directory" if is_dir else "file",
                "size": None if is_dir else stat.st_size,
                "modified_at": stat.st_mtime,
            })
            if is_dir and level < depth:
                walk(child, rel, level + 1)
            if truncated:
                return

    walk(root, _normalise_relative(relative), 1)
    return {"path": _normalise_relative(relative), "entries": entries, "truncated": truncated}


def read_text_file(share: dict[str, Any], relative: str) -> dict[str, Any]:
    target = resolve_path(share, relative, allow_root=False)
    if not target.exists() or not target.is_file():
        raise WorkspaceError("File not found.", 404)
    if target.stat().st_size > MAX_TEXT_BYTES:
        raise WorkspaceError("File exceeds the 2 MiB text-editing limit.", 413)
    try:
        data = target.read_bytes()
        if b"\x00" in data:
            raise WorkspaceError("Binary files cannot be read through the text editor.", 415)
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise WorkspaceError("File is not valid UTF-8 text.", 415)
    return {"path": _normalise_relative(relative), "content": text, "size": len(data)}


def write_text_file(share: dict[str, Any], relative: str, content: str) -> dict[str, Any]:
    target = resolve_path(share, relative, allow_root=False)
    if not isinstance(content, str):
        raise WorkspaceError("Content must be a UTF-8 text string.", 400)
    data = content.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise WorkspaceError("File exceeds the 2 MiB text-editing limit.", 413)
    if target.exists() and not target.is_file():
        raise WorkspaceError("Target is not a file.", 400)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Re-resolve after directory creation to catch path substitution/symlink races.
    target = resolve_path(share, relative, allow_root=False)
    fd, temp_name = tempfile.mkstemp(prefix=".sf2ais-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return {"path": _normalise_relative(relative), "size": len(data), "saved": True}


def create_directory(share: dict[str, Any], relative: str) -> dict[str, Any]:
    target = resolve_path(share, relative, allow_root=False)
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise WorkspaceError("Directory already exists.", 409)
    except OSError as exc:
        raise WorkspaceError("Could not create directory: " + str(exc), 403)
    return {"path": _normalise_relative(relative), "created": True}


def move_path(share: dict[str, Any], source: str, destination: str) -> dict[str, Any]:
    src = resolve_path(share, source, allow_root=False)
    dst = resolve_path(share, destination, allow_root=False)
    if not src.exists():
        raise WorkspaceError("Source does not exist.", 404)
    if dst.exists():
        raise WorkspaceError("Destination already exists.", 409)
    if src.is_dir():
        try:
            dst.relative_to(src)
            raise WorkspaceError("A directory cannot be moved into itself.", 400)
        except ValueError:
            pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    return {"source": _normalise_relative(source), "destination": _normalise_relative(destination), "moved": True}


def delete_path(share: dict[str, Any], relative: str) -> dict[str, Any]:
    import shutil
    target = resolve_path(share, relative, allow_root=False)
    if not target.exists():
        raise WorkspaceError("Path not found.", 404)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"path": _normalise_relative(relative), "deleted": True}


MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def write_binary_file(share: dict[str, Any], relative: str, data: bytes) -> dict[str, Any]:
    target = resolve_path(share, relative, allow_root=False)
    if len(data) > MAX_UPLOAD_BYTES:
        raise WorkspaceError("Upload exceeds the 50 MiB limit.", 413)
    if target.exists() and not target.is_file():
        raise WorkspaceError("Target is not a file.", 400)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = resolve_path(share, relative, allow_root=False)
    fd, temp_name = tempfile.mkstemp(prefix=".sf2ais-upload-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return {"path": _normalise_relative(relative), "size": len(data), "saved": True}
