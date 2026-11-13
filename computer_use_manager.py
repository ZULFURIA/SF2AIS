"""Permission-gated Cua Driver bridge for Sf2AiS.

The Cua Driver process is private to this service and speaks MCP only over
stdin/stdout. It is never exposed as a raw network endpoint.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any


OBSERVATION_TOOLS = frozenset({
    "list_apps", "list_windows", "get_window_state",
    "get_desktop_state", "get_screen_size", "verify_state",
})
ACTION_TOOLS = frozenset({
    "click", "double_click", "right_click", "type_text",
    "press_key", "hotkey", "scroll", "drag", "move_cursor",
})
ALLOWED_TOOLS = OBSERVATION_TOOLS | ACTION_TOOLS | frozenset({"start_session", "end_session"})


class CuaDriverError(RuntimeError):
    pass


class CuaDriverBridge:
    def __init__(self, base_dir: Path, binary_path: str | None = None):
        self.base_dir = Path(base_dir).resolve()
        self.data_dir = self.base_dir / "data" / "cua-driver"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.binary_path = self._resolve_binary(binary_path)
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._messages: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._request_id = 0
        self._tools: set[str] = set()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._version: str | None = None

    def _resolve_binary(self, explicit: str | None) -> str | None:
        if explicit is not None:
            path = Path(explicit)
            return str(path.resolve()) if path.is_file() else None
        configured = os.environ.get("SF2AIS_CUA_DRIVER_BINARY")
        if configured:
            path = Path(configured)
            return str(path.resolve()) if path.is_file() else None
        candidates = [
            self.base_dir / ".venv-cua" / "Scripts" / "cua-driver.exe",
            self.base_dir / "resources" / "cua-driver" / "cua-driver.exe",
            self.base_dir / "probe-app" / "resources" / "cua-driver.exe",
            self.base_dir / "third_party" / "cua-upstream" / "libs" / "cua-driver" / "rust" / "target" / "release" / "cua-driver.exe",
            Path.home() / "AppData" / "Local" / "Programs" / "Cua" / "cua-driver" / "bin" / "cua-driver.exe",
        ]
        for path in candidates:
            if path.is_file():
                return str(path.resolve())
        return shutil.which("cua-driver")

    def status(self) -> dict[str, Any]:
        running = bool(self._process and self._process.poll() is None)
        available = bool(self.binary_path and Path(self.binary_path).is_file())
        if available and not self._version:
            try:
                probe = subprocess.run([self.binary_path, "--version"], capture_output=True,
                                       text=True, timeout=3, check=False)
                if probe.returncode == 0:
                    self._version = (probe.stdout or probe.stderr).strip()[:80]
            except (OSError, subprocess.TimeoutExpired):
                pass
        return {
            "provider": "Cua Driver",
            "available": available,
            "running": running,
            "version": self._version,
            "binary": Path(self.binary_path).name if self.binary_path else None,
            "transport": "private-stdio-mcp",
            "permission_mode": "bounded",
            "network_listener": False,
            "telemetry": "disabled",
        }

    def _write_policy(self) -> tuple[Path, Path]:
        manifest = self.data_dir / "capability-manifest.yaml"
        policy = self.data_dir / "tool-policy.yaml"
        manifest.write_text(
            """version: 3
expires_after: 30m
idle_timeout: 5m
allow:
  tools:
    - start_session
    - end_session
    - list_apps
    - list_windows
    - get_window_state
    - get_desktop_state
    - get_screen_size
    - verify_state
    - click
    - double_click
    - right_click
    - type_text
    - press_key
    - hotkey
    - scroll
    - drag
    - move_cursor
resources:
  desktop:
    display: true
""",
            encoding="utf-8",
        )
        policy.write_text(
            """allow:
  tools:
    - start_session
    - end_session
    - list_apps
    - list_windows
    - get_window_state
    - get_desktop_state
    - get_screen_size
    - verify_state
    - click
    - double_click
    - right_click
    - press_key
    - hotkey
    - scroll
    - drag
    - move_cursor
  rules:
    - tool: type_text
      constraints:
        text:
          max_length: 1000
deny:
  tools:
    - shell_execute
    - run_script
    - clipboard_read
    - clipboard_write
    - file_delete
""",
            encoding="utf-8",
        )
        return manifest, policy

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._messages.put(message)
        finally:
            self._messages.put(None)

    def _request(self, method: str, params: dict | None = None, timeout: float = 20.0) -> dict:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise CuaDriverError("Cua Driver is not running.")
        self._request_id += 1
        request_id = self._request_id
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (OSError, BrokenPipeError) as exc:
            raise CuaDriverError(f"Could not send request to Cua Driver: {exc}") from exc
        while True:
            try:
                message = self._messages.get(timeout=timeout)
            except queue.Empty as exc:
                raise CuaDriverError(f"Cua Driver timed out during {method}.") from exc
            if message is None:
                raise CuaDriverError("Cua Driver exited unexpectedly.")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                raise CuaDriverError(str(error.get("message", "Cua Driver request failed.")))
            result = message.get("result")
            if not isinstance(result, dict):
                raise CuaDriverError("Cua Driver returned an invalid response.")
            return result

    def start(self) -> dict:
        with self._lock:
            if self._process and self._process.poll() is None:
                return self.status()
            if self._process is not None:
                self._process = None
                self._sessions.clear()
                self._tools.clear()
            if not self.binary_path or not Path(self.binary_path).is_file():
                raise CuaDriverError(
                    "Cua Driver is not installed or built. Build the pinned upstream source or set SF2AIS_CUA_DRIVER_BINARY."
                )
            manifest, policy = self._write_policy()
            env = os.environ.copy()
            env.update({
                "CUA_DRIVER_PERMISSION_MODE": "bounded",
                "CUA_DRIVER_CAPABILITY_MANIFEST_FILE": str(manifest),
                "CUA_DRIVER_CAPABILITY_MANIFEST_APPROVED": "1",
                "CUA_DRIVER_POLICY_FILE": str(policy),
                "CUA_DRIVER_RS_HOME": str(self.data_dir / "runtime-home"),
                "DO_NOT_TRACK": "1",
                "CUA_TELEMETRY": "0",
            })
            Path(env["CUA_DRIVER_RS_HOME"]).mkdir(parents=True, exist_ok=True)
            try:
                telemetry = subprocess.run(
                    [self.binary_path, "telemetry", "disable"],
                    capture_output=True, text=True, timeout=8, env=env,
                    cwd=str(self.data_dir),
                )
                if telemetry.returncode != 0:
                    raise CuaDriverError("Could not disable Cua Driver telemetry; refusing to start the provider.")
                self._process = subprocess.Popen(
                    [self.binary_path, "mcp"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                    env=env,
                    cwd=str(self.data_dir),
                )
            except OSError as exc:
                self._process = None
                raise CuaDriverError(f"Could not start Cua Driver: {exc}") from exc
            self._messages = queue.Queue()
            self._reader = threading.Thread(target=self._read_stdout, daemon=True, name="sf2ais-cua-stdout")
            self._reader.start()
            try:
                initialized = self._request("initialize", {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "Sf2AiS", "version": "0.1.0"},
                })
                self._process.stdin.write(json.dumps({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }, separators=(",", ":")) + "\n")
                self._process.stdin.flush()
                listed = self._request("tools/list", {})
                tools = listed.get("tools", [])
                self._tools = {item.get("name") for item in tools if isinstance(item, dict)}
                required = {"start_session", "end_session", "get_desktop_state", "click", "type_text"}
                missing = required - self._tools
                if missing:
                    raise CuaDriverError("Cua Driver is missing required tools: " + ", ".join(sorted(missing)))
                info = initialized.get("serverInfo", {})
                self._version = info.get("version") if isinstance(info, dict) else None
                return self.status()
            except Exception:
                self.stop()
                raise

    def create_session(self, owner: str, allow_control: bool = False) -> str:
        with self._lock:
            self.start()
            session_id = "sf2ais-" + uuid.uuid4().hex
            self._call_tool("start_session", {
                "session": session_id,
                "capture_scope": None,
                "cursor_theme": None,
            })
            self._sessions[session_id] = {
                "owner": owner,
                "control_allowed": bool(allow_control),
            }
            return session_id

    def _call_tool(self, name: str, arguments: dict) -> dict:
        if name not in ALLOWED_TOOLS or name not in self._tools:
            raise CuaDriverError(f"Cua tool is not enabled by Sf2AiS policy: {name}")
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            content = result.get("content", [])
            message = "Cua Driver tool failed."
            if content and isinstance(content[0], dict):
                message = str(content[0].get("text") or message)
            raise CuaDriverError(message)
        return result

    def call(self, session_id: str, owner: str, tool: str, arguments: dict | None = None) -> dict:
        with self._lock:
            self.start()
            session = self._sessions.get(session_id)
            if not session or session.get("owner") != owner:
                raise CuaDriverError("Computer-use session not found for this client.")
            if tool not in OBSERVATION_TOOLS and tool not in ACTION_TOOLS:
                raise CuaDriverError("This Cua tool is not exposed through the Sf2AiS HTTP bridge.")
            if tool in ACTION_TOOLS and not session.get("control_allowed", False):
                raise CuaDriverError("This session was started without mouse and keyboard control consent.")
            args = dict(arguments or {})
            if tool not in {"list_apps", "list_windows", "get_screen_size"}:
                args["session"] = session_id
            if tool == "get_desktop_state":
                args.setdefault("screenshot_out_file", None)
            return self._call_tool(tool, args)

    def end_session(self, session_id: str, owner: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.get("owner") != owner:
                return False
            try:
                if self._process and self._process.poll() is None:
                    self._call_tool("end_session", {"session": session_id})
            finally:
                self._sessions.pop(session_id, None)
            return True

    def close_owner(self, owner: str) -> int:
        with self._lock:
            ids = [sid for sid, session in self._sessions.items() if session.get("owner") == owner]
            for sid in ids:
                try:
                    self.end_session(sid, owner)
                except CuaDriverError:
                    self._sessions.pop(sid, None)
            return len(ids)

    def close_share(self, share_id: str) -> int:
        with self._lock:
            prefix = share_id + ":"
            owners = {session["owner"] for session in self._sessions.values()
                      if str(session.get("owner", "")).startswith(prefix)}
            return sum(self.close_owner(owner) for owner in owners)

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._tools.clear()
            self._sessions.clear()
            if process is None:
                return
            try:
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass
