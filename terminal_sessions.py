"""Persistent, bounded interactive shell sessions inside the Sf2AiS Docker sandbox.

Sessions are line-oriented (no pseudo-terminal / full-screen TUI support). Every
session operates on an isolated workspace snapshot and synchronises changes
back only when the session is closed or exits.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import sandbox_runner

MAX_SESSIONS_GLOBAL = 4
MAX_SESSIONS_PER_SHARE = 2
MAX_SESSION_IDLE_SECONDS = 30 * 60
MAX_SESSION_LIFETIME_SECONDS = 4 * 60 * 60
MAX_INPUT_BYTES = 20_000
MAX_OUTPUT_BYTES = 200_000
MAX_OUTPUT_EVENTS = 512


class TerminalSessionError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class TerminalSession:
    def __init__(self, session_id: str, share_id: str, owner_id: str,
                 container_name: str, stage_dir: Path, initial_files: set[str],
                 process: subprocess.Popen):
        self.id = session_id
        self.share_id = share_id
        self.owner_id = owner_id
        self.container_name = container_name
        self.stage_dir = stage_dir
        self.share_root: Path | None = None
        self.initial_files = initial_files
        self.process = process
        self.created_at = time.time()
        self.last_activity = self.created_at
        self.status = "running"
        self.exit_code: int | None = None
        self.error: str | None = None
        self.events: deque[dict[str, Any]] = deque()
        self.output_bytes = 0
        self.sequence = 0
        self.truncated = False
        self.lock = threading.RLock()
        self.finalize_lock = threading.Lock()
        self.finalized = False


class TerminalSessionManager:
    def __init__(self):
        self.sessions: dict[str, TerminalSession] = {}
        self.starting_by_share: dict[str, int] = defaultdict(int)
        self.starting_total = 0
        self.lock = threading.RLock()

    def _append(self, session: TerminalSession, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace")
        if not text:
            return
        encoded_size = len(data)
        with session.lock:
            session.sequence += 1
            session.events.append({"seq": session.sequence, "data": text})
            session.output_bytes += encoded_size
            while session.events and (
                session.output_bytes > MAX_OUTPUT_BYTES or len(session.events) > MAX_OUTPUT_EVENTS
            ):
                removed = session.events.popleft()
                session.output_bytes -= len(removed["data"].encode("utf-8", errors="replace"))
                session.truncated = True
            session.last_activity = time.time()

    def _finalize(self, session: TerminalSession, sync: bool = True) -> None:
        if not session.finalize_lock.acquire(blocking=False):
            return
        try:
            if session.finalized:
                return
            session.finalized = True
            try:
                if sync and session.stage_dir.exists():
                    if session.share_root is None:
                        raise RuntimeError("Session workspace root is unavailable.")
                    root = Path(session.share_root).resolve(strict=True)
                    sandbox_runner._sync_stage(root, session.stage_dir, session.initial_files)
            except Exception as exc:
                session.error = "Workspace synchronisation failed: " + str(exc)
                session.status = "failed"
            finally:
                shutil.rmtree(session.stage_dir, ignore_errors=True)
                if session.status == "running":
                    session.status = "closed"
                session.last_activity = time.time()
        finally:
            session.finalize_lock.release()

    def start(self, share: dict[str, Any], cwd: Path, owner_id: str) -> TerminalSession:
        status = sandbox_runner.sandbox_status()
        if not status.get("available"):
            raise TerminalSessionError(status.get("reason", "Docker sandbox is unavailable."), 503)
        root = Path(share["folder"]).resolve(strict=True)
        cwd = Path(cwd).resolve(strict=True)
        try:
            relative_cwd = cwd.relative_to(root)
        except ValueError:
            raise TerminalSessionError("Requested working directory is outside the share.", 400)

        with self.lock:
            self._prune_locked()
            active = [s for s in self.sessions.values() if s.status == "running"]
            active_for_share = sum(s.share_id == share["id"] for s in active)
            if active_for_share + self.starting_by_share[share["id"]] >= MAX_SESSIONS_PER_SHARE:
                raise TerminalSessionError("This share already has the maximum number of terminal sessions.", 429)
            if len(active) + self.starting_total >= MAX_SESSIONS_GLOBAL:
                raise TerminalSessionError("The server has reached its global terminal session limit.", 429)
            self.starting_by_share[share["id"]] += 1
            self.starting_total += 1

        stage_dir = None
        session_id = str(uuid.uuid4())
        container_name = "sf2ais-term-" + session_id.replace("-", "")[:16]
        process = None
        reservation_released = False
        try:
            stage_dir = Path(tempfile.mkdtemp(prefix=".sf2ais-terminal-", dir=str(root.parent)))
            initial = sandbox_runner._create_stage(root, stage_dir)
            staged_cwd = stage_dir / relative_cwd
            if not staged_cwd.is_dir():
                raise TerminalSessionError("Requested working directory is not present in the safe workspace snapshot.", 400)
            staged_share = dict(share)
            staged_share["folder"] = str(stage_dir)
            argv = sandbox_runner.build_docker_argv(staged_share, "", staged_cwd,
                                                    container_name=container_name)
            argv = [arg for arg in argv if arg != "--interactive=false"]
            insert_at = argv.index("run") + 1
            argv.insert(insert_at, "-i")
            if argv[-3:] == ["/bin/sh", "-lc", ""]:
                argv[-3:] = ["/bin/sh"]
            process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, bufsize=0)
            session = TerminalSession(session_id, share["id"], owner_id, container_name,
                                      stage_dir, initial, process)
            session.share_root = root
            with self.lock:
                self.starting_by_share[share["id"]] -= 1
                self.starting_total -= 1
                reservation_released = True
                self.sessions[session_id] = session
            threading.Thread(target=self._reader, args=(session,), daemon=True,
                             name="sf2ais-terminal-reader").start()
            threading.Thread(target=self._watchdog, args=(session,), daemon=True,
                             name="sf2ais-terminal-watchdog").start()
            return session
        except Exception:
            if not reservation_released:
                with self.lock:
                    self.starting_by_share[share["id"]] = max(0, self.starting_by_share[share["id"]] - 1)
                    self.starting_total = max(0, self.starting_total - 1)
            if process is not None:
                try:
                    subprocess.run([shutil.which("docker") or "docker", "rm", "-f", container_name],
                                   capture_output=True, timeout=8)
                except Exception:
                    try:
                        process.kill()
                    except OSError:
                        pass
            if stage_dir is not None:
                shutil.rmtree(stage_dir, ignore_errors=True)
            raise

    def _reader(self, session: TerminalSession) -> None:
        try:
            stream = session.process.stdout
            while stream is not None:
                chunk = stream.read(4096)
                if not chunk:
                    break
                self._append(session, chunk)
            code = session.process.wait(timeout=10)
            with session.lock:
                session.exit_code = code
                if session.status == "running":
                    session.status = "exited"
        except Exception as exc:
            with session.lock:
                session.error = str(exc)
                if session.status == "running":
                    session.status = "failed"
        finally:
            self._finalize(session, sync=True)

    def _watchdog(self, session: TerminalSession) -> None:
        while True:
            time.sleep(10)
            with session.lock:
                if session.status != "running":
                    return
                idle = time.time() - session.last_activity
                age = time.time() - session.created_at
            if idle > MAX_SESSION_IDLE_SECONDS or age > MAX_SESSION_LIFETIME_SECONDS:
                self.close(session, reason="idle or maximum lifetime limit reached")
                return
            if session.process.poll() is not None:
                return

    def get(self, session_id: str, share_id: str, owner_id: str) -> TerminalSession:
        with self.lock:
            session = self.sessions.get(session_id)
        if not session or session.share_id != share_id or session.owner_id != owner_id:
            raise TerminalSessionError("Terminal session not found.", 404)
        return session

    def write(self, session: TerminalSession, data: str) -> None:
        if not isinstance(data, str) or not data or len(data.encode("utf-8")) > MAX_INPUT_BYTES:
            raise TerminalSessionError("Terminal input must contain 1-20,000 UTF-8 bytes.", 413)
        if "\x00" in data:
            raise TerminalSessionError("NUL characters are not allowed in terminal input.", 400)
        with session.lock:
            if session.status != "running" or session.process.poll() is not None:
                raise TerminalSessionError("Terminal session is no longer running.", 409)
            try:
                session.process.stdin.write(data.encode("utf-8"))
                session.process.stdin.flush()
            except (BrokenPipeError, OSError):
                raise TerminalSessionError("Terminal process is no longer accepting input.", 409)
            session.last_activity = time.time()

    def read(self, session: TerminalSession, after: int = 0) -> dict[str, Any]:
        if after < 0:
            raise TerminalSessionError("Output cursor must be zero or greater.", 400)
        with session.lock:
            oldest = session.events[0]["seq"] if session.events else session.sequence + 1
            events = [event for event in session.events if event["seq"] > after]
            return {
                "session_id": session.id,
                "events": events,
                "next": session.sequence,
                "truncated": session.truncated and after < oldest - 1,
                "status": session.status,
                "exit_code": session.exit_code,
                "error": session.error,
            }

    def close(self, session: TerminalSession, reason: str = "closed by client") -> None:
        with session.lock:
            if session.status != "running":
                self._finalize(session, sync=True)
                return
            session.status = "stopping"
            session.last_activity = time.time()
        docker = shutil.which("docker")
        if docker:
            try:
                subprocess.run([docker, "stop", "--time", "3", session.container_name],
                               capture_output=True, timeout=8)
            except Exception:
                pass
            try:
                subprocess.run([docker, "rm", "-f", session.container_name],
                               capture_output=True, timeout=8)
            except Exception:
                pass
        try:
            session.process.wait(timeout=5)
        except Exception:
            try:
                session.process.kill()
                session.process.wait(timeout=5)
            except Exception:
                pass
        with session.lock:
            if session.status == "stopping":
                session.status = "closed"
        self._finalize(session, sync=True)

    def close_share(self, share_id: str) -> None:
        with self.lock:
            sessions = [s for s in self.sessions.values() if s.share_id == share_id and s.status == "running"]
        for session in sessions:
            self.close(session, reason="share access changed")

    def close_owner(self, owner_id: str) -> None:
        with self.lock:
            sessions = [s for s in self.sessions.values() if s.owner_id == owner_id and s.status == "running"]
        for session in sessions:
            self.close(session, reason="AI client revoked")

    def _prune_locked(self) -> None:
        cutoff = time.time() - 24 * 60 * 60
        for session_id, session in list(self.sessions.items()):
            if session.status != "running" and session.last_activity < cutoff:
                self.sessions.pop(session_id, None)
