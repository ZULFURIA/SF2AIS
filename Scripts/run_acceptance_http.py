from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
USERNAME, PASSWORD = base64.b64decode(sys.argv[1]).decode().split(":", 1)
TOKEN = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()


def request(method: str, path: str, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Authorization": f"Basic {TOKEN}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = raw.decode("utf-8", "replace")
        return exc.code, parsed


def check(condition: bool, label: str):
    if not condition:
        raise RuntimeError("FAIL: " + label)
    print("PASS: " + label)


status, tree = request("GET", "/api/workspace/tree?depth=3")
check(status == 200, "authenticated share tree")
paths = {entry.get("path") for entry in tree.get("entries", [])}
check("app.js" in paths and "app.py" in paths, "test application files visible")
check(".env" not in paths and ".git" not in paths, "secret and VCS paths excluded")

status, file_data = request("GET", "/api/workspace/file?" + urllib.parse.urlencode({"path": "app.js"}))
check(status == 200 and "RESULT: PASS" in file_data.get("content", ""), "read existing JavaScript test app")

status, _ = request("GET", "/api/workspace/file?" + urllib.parse.urlencode({"path": ".env"}))
check(status in (403, 404), "secret file read denied")
status, _ = request("GET", "/api/workspace/file?" + urllib.parse.urlencode({"path": "../outside.txt"}))
check(status in (403, 404), "path traversal denied")

write_path = "acceptance-web-write.txt"
status, _ = request("PUT", "/api/workspace/file", {"path": write_path, "content": "web-write-pass\n"})
check(status == 200, "write scoped workspace file")
status, written = request("GET", "/api/workspace/file?" + urllib.parse.urlencode({"path": write_path}))
check(status == 200 and written.get("content") == "web-write-pass\n", "read back workspace write")
status, _ = request("DELETE", "/api/workspace/path?" + urllib.parse.urlencode({"path": write_path}))
check(status == 200, "delete test artifact after verification")

status, ide = request("GET", "/api/ide/status")
check(status == 200 and ide.get("enabled") is True, "IDE integration permission enabled")
check(ide.get("write") is True and ide.get("host_terminal") is False, "IDE write scope enabled without host terminal")
status, ide_tree = request("GET", "/api/ide/tree?depth=2")
check(status == 200 and "app.py" in {e.get("path") for e in ide_tree.get("entries", [])}, "IDE scoped file tree")
ide_write = "acceptance-ide-write.txt"
status, _ = request("PUT", "/api/ide/file", {"path": ide_write, "content": "ide-write-pass\\n"})
check(status == 200, "IDE scoped write")
status, ide_file = request("GET", "/api/ide/file?" + urllib.parse.urlencode({"path": ide_write}))
check(status == 200 and ide_file.get("content") == "ide-write-pass\\n", "IDE read back")
status, _ = request("DELETE", "/api/ide/path?" + urllib.parse.urlencode({"path": ide_write}))
check(status == 200, "IDE test artifact cleanup")

status, cua = request("GET", "/api/computer-use/status")
check(status == 200, "CUA provider status endpoint")
check(cua.get("enabled") is False and cua.get("observe_allowed") is False and cua.get("control_allowed") is False,
      "CUA is disabled by default for acceptance share")
check(cua.get("exposed_tools") == [], "no CUA tools exposed without explicit grants")
print("CUA provider status:", cua.get("provider"))
status, denied_cua = request("POST", "/api/computer-use/sessions", {"confirm": "START"})
check(status == 403, "CUA session start denied without observation grant")

def run_cli(command: str, expected: str):
    status, created = request("POST", "/cli/jobs", {"command": command, "shell": "bash", "cwd": ""})
    check(status == 200 and created.get("job_id"), "submit Docker-isolated CLI job")
    job_id = created["job_id"]
    deadline = time.time() + 90
    job = None
    while time.time() < deadline:
        status, job = request("GET", "/cli/jobs/" + urllib.parse.quote(job_id))
        if status != 200:
            raise RuntimeError(f"CLI poll failed: HTTP {status}: {job}")
        if job.get("status") != "running":
            break
        time.sleep(0.5)
    check(job is not None and job.get("status") == "completed", f"CLI job completed: {job}")
    check(job.get("exit_code") == 0, f"CLI exit code 0: {job.get('stderr')}")
    check(expected in (job.get("stdout") or ""), "CLI output matched expected marker")
    return job

node_job = run_cli("node app.js", "RESULT: PASS")
status, sandbox_file = request("GET", "/api/workspace/file?" + urllib.parse.urlencode({"path": "sandbox-output.txt"}))
check(status == 200 and "filesystem write succeeded" in sandbox_file.get("content", ""), "Docker sandbox writeback visible in share")

python_job = run_cli("python3 app.py", "sandbox test application: OK")
isolation_job = run_cli("test ! -S /var/run/docker.sock && test ! -d /mnt/c/Windows && echo ISOLATION_PASS", "ISOLATION_PASS")
network_job = run_cli("python3 -c 'import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex((\"1.1.1.1\",53)); print(\"NETWORK_BLOCKED\" if r else \"NETWORK_OPEN\"); raise SystemExit(9 if r == 0 else 0)'", "NETWORK_BLOCKED")
readonly_job = run_cli("if touch /etc/sf2ais-write-test 2>/dev/null; then rm -f /etc/sf2ais-write-test; exit 9; else echo ROOTFS_READ_ONLY; fi", "ROOTFS_READ_ONLY")
print("ACCEPTANCE_RESULT=PASS")
print("Node CLI status:", node_job.get("status"), "exit:", node_job.get("exit_code"))
print("Python CLI status:", python_job.get("status"), "exit:", python_job.get("exit_code"))
print("Isolation status:", isolation_job.get("status"), "exit:", isolation_job.get("exit_code"))
print("Network isolation status:", network_job.get("status"), "exit:", network_job.get("exit_code"))
print("Read-only rootfs status:", readonly_job.get("status"), "exit:", readonly_job.get("exit_code"))
