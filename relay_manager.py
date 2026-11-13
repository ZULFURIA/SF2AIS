"""Optional Cloudflare Tunnel supervisor for outbound-only gateway access.

The tunnel is remotely managed in Cloudflare. Its ingress/public hostname is
configured there to forward to this local Sf2AiS HTTP service. The token is
passed to cloudflared through TUNNEL_TOKEN, never through command-line args.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections import deque
from typing import Any


class CloudflareTunnelManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.process: subprocess.Popen | None = None
        self.state = "disabled"
        self.last_error: str | None = None
        self.last_exit_code: int | None = None
        self.logs: deque[str] = deque(maxlen=30)
        self.started_at: float | None = None

    def _token(self) -> str:
        return os.getenv("SF2AIS_CLOUDFLARED_TOKEN", "").strip()

    def _executable(self) -> str | None:
        configured = os.getenv("SF2AIS_CLOUDFLARED_BIN", "cloudflared").strip()
        return shutil.which(configured) or (configured if os.path.isfile(configured) else None)

    def status(self) -> dict[str, Any]:
        with self.lock:
            token_present = bool(self._token())
            executable = self._executable()
            state = self.state
            if not token_present:
                state = "disabled"
            elif not executable and state in ("disabled", "starting"):
                state = "unavailable"
            return {
                "provider": "cloudflare-tunnel",
                "enabled": token_present,
                "available": bool(executable),
                "state": state,
                "pid": self.process.pid if self.process and self.process.poll() is None else None,
                "last_error": self.last_error,
                "last_exit_code": self.last_exit_code,
                "recent_logs": list(self.logs)[-10:],
                "started_at": self.started_at,
            }

    def start(self) -> dict[str, Any]:
        if not self._token():
            with self.lock:
                self.state = "disabled"
            return self.status()
        executable = self._executable()
        if not executable:
            with self.lock:
                self.state = "unavailable"
                self.last_error = "cloudflared was not found. Install it and ensure it is on PATH."
            return self.status()
        with self.lock:
            if self.thread and self.thread.is_alive():
                return self.status()
            self.stop_event.clear()
            self.state = "starting"
            self.last_error = None
            self.started_at = time.time()
            self.thread = threading.Thread(
                target=self._run_loop, args=(executable,), daemon=True,
                name="sf2ais-cloudflare-tunnel",
            )
            self.thread.start()
        return self.status()

    def _record_log(self, line: str) -> None:
        token = self._token()
        safe_line = line.rstrip()
        if token:
            safe_line = safe_line.replace(token, "[redacted]")
        with self.lock:
            self.logs.append(safe_line[:1000])
            lowered = safe_line.lower()
            if "registered tunnel connection" in lowered or "connection registered" in lowered:
                self.state = "connected"
                self.last_error = None
            elif " error " in lowered or lowered.startswith("err"):
                self.last_error = safe_line[:500]

    def _run_loop(self, executable: str) -> None:
        backoff = (5, 10, 20, 30, 60)
        attempt = 0
        while not self.stop_event.is_set():
            token = self._token()
            if not token:
                with self.lock:
                    self.state = "disabled"
                return
            env = os.environ.copy()
            env["TUNNEL_TOKEN"] = token
            env["TUNNEL_LOGLEVEL"] = "info"
            env["NO_AUTOUPDATE"] = "true"
            try:
                process = subprocess.Popen(
                    [executable, "tunnel", "--no-autoupdate", "run"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=env,
                )
                with self.lock:
                    self.process = process
                    self.state = "connecting"
                if process.stdout:
                    for line in process.stdout:
                        self._record_log(line)
                        if self.stop_event.is_set():
                            break
                code = process.wait(timeout=10)
                with self.lock:
                    self.process = None
                    self.last_exit_code = code
                if self.stop_event.is_set():
                    break
                with self.lock:
                    self.state = "reconnecting"
                    if code != 0 and not self.last_error:
                        self.last_error = "cloudflared exited with code %s." % code
            except Exception as exc:
                with self.lock:
                    self.process = None
                    self.state = "reconnecting"
                    self.last_error = str(exc)[:500]
            delay = backoff[min(attempt, len(backoff) - 1)]
            attempt += 1
            if self.stop_event.wait(delay):
                break
        with self.lock:
            self.process = None
            self.state = "stopped"

    def stop(self) -> None:
        self.stop_event.set()
        with self.lock:
            process = self.process
            thread = self.thread
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=10)
            except Exception:
                try:
                    process.kill()
                except OSError:
                    pass
        if thread and thread.is_alive():
            thread.join(timeout=12)
        with self.lock:
            self.process = None
            self.state = "stopped" if self._token() else "disabled"
