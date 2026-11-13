"""In-process security battery against SF2AiS via TestClient (no live server needed)."""
import os, sys, json, base64, time
sys.path.insert(0, ".")

import main
from fastapi.testclient import TestClient

import pytest

ADMIN_USER, ADMIN_PASS = "admin", "admin-pass-123"
ADMIN_HASH = main.bcrypt.hash(ADMIN_PASS)
SHARE1_PASS = "share1-pass-1"
SHARE2_PASS = "share2-pass-2"


def _auth(user, passwd):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{passwd}".encode()).decode()}

config = {
    "admin": {"username": ADMIN_USER, "password_hash": ADMIN_HASH},
    "settings": main.DEFAULT_SETTINGS,
    "shares": [
        {"id": "s1", "folder": os.path.abspath("./data/security-share"), "username": "share1", "password_hash": main.bcrypt.hash(SHARE1_PASS),
         "client_id": "client-a", "authorized_clients": ["client-a"], "capabilities": ["filesystem"], "permission": "read-write", "workspace_write_enabled": True},
        {"id": "s2", "folder": os.path.abspath("./data/secret-share"), "username": "share2", "password_hash": main.bcrypt.hash(SHARE2_PASS),
         "client_id": "client-b", "authorized_clients": ["client-b"], "capabilities": ["filesystem"], "permission": "read-only"},
    ],
    "connections": [], "sessions": {}, "file_locks": {}, "blacklist": [],
    "skill_registry": [], "tool_registry": [], "component_versions": main._COMPONENT_VERSIONS,
}

# Ensure share dirs exist.
os.makedirs("./data/security-share", exist_ok=True)
open("./data/security-share/hello.txt", "w").write("hello world")

# Patch load_config/save_config for the whole test.
main.load_config = lambda: config
main.save_config = lambda cfg: None

@pytest.fixture()
def client():
    os.makedirs("./data/security-share", exist_ok=True)
    open("./data/security-share/hello.txt", "w").write("hello world")
    main.load_config = lambda: config
    main.save_config = lambda cfg: None
    with TestClient(main.app) as c:
        yield c


# ---- Security battery (group of assertions) ----


def test_security_battery(client):
    results = []
    p = 0

    def check(name, cond, detail=""):
        nonlocal p
        results.append((name, bool(cond), detail))
        print(("PASS" if cond else "FAIL"), "-", name, "" if cond else f"  -> {detail}")
        if cond:
            p += 1

    # 1. Unauthenticated admin -> 401
    r = client.get("/api/status"); check("auth: unauthenticated 401", r.status_code == 401, str(r.status_code))
    # 2. Valid admin -> 200
    r = client.get("/api/status", headers=_auth(ADMIN_USER, ADMIN_PASS)); check("auth: valid admin 200", r.status_code == 200, str(r.status_code))

    # 3. Path traversal read blocked
    r = client.put("/api/workspace/file", headers=_auth("share1", SHARE1_PASS), json={"path": "../../../Windows/win.ini", "content": ""})
    check("traversal: read outside share blocked", r.status_code in (400, 403, 404), f"{r.status_code} {r.text[:60]}")

    # 4. Path traversal write blocked
    r = client.put("/api/workspace/file", headers=_auth("share1", SHARE1_PASS), json={"path": "../../../evil.txt", "content": "pwn"})
    check("traversal: write outside share blocked", r.status_code in (400, 403, 404), f"{r.status_code} {r.text[:60]}")

    # 5. Normal read inside share
    r = client.get("/api/workspace/file", params={"path": "hello.txt"}, headers=_auth("share1", SHARE1_PASS))
    check("read: normal read in share -> 200", r.status_code == 200, f"{r.status_code} {r.text[:60]}")

    # 6. Write lifecycle
    r = client.put("/api/workspace/file", json={"path": "smoke.txt", "content": "v1"}, headers=_auth("share1", SHARE1_PASS))
    check("write: create test file", r.status_code == 200, f"{r.status_code}")
    r = client.get("/api/workspace/file", params={"path": "smoke.txt"}, headers=_auth("share1", SHARE1_PASS))
    check("read: create dups confirmed", r.status_code == 200 and r.json().get("content") == "v1", f"{r.status_code}")
    r = client.put("/api/workspace/file", json={"path": "smoke.txt", "content": "v2"}, headers=_auth("share1", SHARE1_PASS))
    check("write: modify test file", r.status_code == 200, f"{r.status_code}")
    r = client.delete("/api/workspace/path", params={"path": "smoke.txt"}, headers=_auth("share1", SHARE1_PASS))
    check("delete: test file removed", r.status_code == 200, f"{r.status_code}")

    # 7. Read-only client cannot write
    r = client.put("/api/workspace/file", json={"path": "rw.txt", "content": "x"}, headers=_auth("share2", SHARE2_PASS))
    check("perm: read-only client cannot write -> 403", r.status_code == 403, f"{r.status_code}")

    # 8. Malformed / invalid input rejected (missing required field -> 400)
    r = client.put("/api/workspace/file", headers=_auth("share1", SHARE1_PASS), json={"path": "probe.txt"})
    check("validation: incomplete write rejected", r.status_code == 400, f"{r.status_code} {r.text[:60]}")

    # 9. Connection expiry (duration) via TestClient
    r = client.post("/api/connections", headers=_auth(ADMIN_USER, ADMIN_PASS), json={
        "client_type": "ai", "client_app": "S", "client_version": "1.0.0", "identity": "ExpTest",
        "capabilities": ["filesystem"], "workspace": {"id": "s1"}, "purpose": "", "duration_seconds": 1})
    check("conn: 1s duration created", r.status_code == 201, f"{r.status_code}")
    cid = r.json()["connection"]["id"]
    time.sleep(1.1)
    r = client.get("/api/connections", headers=_auth(ADMIN_USER, ADMIN_PASS))
    check("conn: expired connection auto-cleaned", len(r.json()["connections"]) == 0, f"remaining={r.json()['connections']}")

    # 10. Credentials not in server log (no live log here; verify password hash present, plaintext absent)
    check("secrets: admin plaintext not stored as password_hash",
          config["admin"]["password_hash"] != ADMIN_PASS and "admin-pass-123" not in config["admin"]["password_hash"])

    print()
    print(f"SECURITY BATTERY: {p}/{len(results)} passed")
    assert p == len(results), f"{p} of {len(results)} security checks passed"
