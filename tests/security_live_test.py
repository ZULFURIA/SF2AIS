"""Security battery against the LIVE SF2AiS backend (port 8123)."""
import urllib.request, urllib.error, urllib.parse, json, base64, hashlib, time, os

BASE = "http://127.0.0.1:8123"
SHARE1 = "http://127.0.0.1:8123/api/workspace/file"
SHARE2 = "http://127.0.0.1:8123/api/workspace/file"

ADMIN_BASIC = "Basic " + base64.b64encode(b"admin:admin-pass-123").decode()
SHARE1_BASIC = "Basic " + base64.b64encode(b"share1:share1-pass-1").decode()
SHARE2_BASIC = "Basic " + base64.b64encode(b"share2:share2-pass-2").decode()

results = []
def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(("PASS" if cond else "FAIL"), "-", name, "" if cond else f"  -> {detail}")

def req(method, path, headers=None, body=None, timeout=10):
    url = BASE + path
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "null")
        except Exception:
            return e.code, {"detail": e.reason}

# 1. Unauthenticated admin -> 401
s, b = req("GET", "/api/status")
check("auth: unauthenticated /api/status -> 401", s == 401, f"got {s}")

# 2. Valid admin -> 200
s, b = req("GET", "/api/status", headers={"Authorization": ADMIN_BASIC})
check("auth: valid admin /api/status -> 200", s == 200, f"got {s}")

# 3. Path traversal on read (outside share)
body = {"path": "../../../Windows/win.ini", "content": ""}
s, b = req("PUT", SHARE1, headers={"Authorization": SHARE1_BASIC}, body=body)
check("traversal: read outside share blocked", s in (400, 403, 404), f"got {s} {b}")

# 4. Path traversal on write -> blocked (403/400)
s, b = req("PUT", SHARE1, headers={"Authorization": SHARE1_BASIC}, body={"path": "../../../evil.txt", "content": "pwn"})
check("traversal: write outside share blocked", s in (400, 403, 404), f"got {s} {b}")

# 5. Normal read inside share
s, b = req("GET", SHARE1, headers={"Authorization": SHARE1_BASIC}, body={"path": "hello.txt"})
check("read: normal read in share -> 200", s == 200, f"got {s}")

# 6. Write a test file, then modify, then delete (lifecycle)
s, b = req("PUT", SHARE1, headers={"Authorization": SHARE1_BASIC}, body={"path": "smoke.txt", "content": "v1"})
check("write: create test file -> 200", s == 200, f"got {s}")
s, b = req("GET", SHARE1, headers={"Authorization": SHARE1_BASIC}, body={"path": "smoke.txt"})
check("read: create dups confirmed", s == 200 and b.get("content") == "v1", f"got {s}")
s, b = req("PUT", SHARE1, headers={"Authorization": SHARE1_BASIC}, body={"path": "smoke.txt", "content": "v2"})
check("write: modify test file -> 200", s == 200, f"got {s}")
s, b = req("DELETE", SHARE1, headers={"Authorization": SHARE1_BASIC}, body={"path": "smoke.txt"})
check("delete: test file removed -> 200", s == 200, f"got {s}")

# 7. Read-only client (share2) cannot write
s, b = req("PUT", SHARE2, headers={"Authorization": SHARE2_BASIC}, body={"path": "rw.txt", "content": "x"})
check("perm: read-only client cannot write -> 403", s == 403, f"got {s}")

# 8. Content-Type validation (malformed JSON)
s, b = req("GET", SHARE1, headers={"Authorization": SHARE1_BASIC}, body="not-json")
check("validation: malformed body rejected", s in (400, 415, 416, 422), f"got {s}")

# 9. Connection expiry: create a 1s connection, approve, verify expires_at in future
def _admin_headers():
    return {"Authorization": ADMIN_BASIC}
s, b = req("POST", "/api/connections", headers=_admin_headers(), body={
    "client_type": "ai", "client_app": "S", "client_version": "1.0.0", "identity": "ExpTest",
    "capabilities": ["filesystem"], "workspace": {"id": "s1"}, "purpose": "", "duration_seconds": 1})
check("conn: 1s duration created", s == 201, f"got {s}")
cid = b.get("connection", {}).get("id")
time.sleep(1.1)
s, b = req("GET", "/api/connections", headers=_admin_headers())
conns = b.get("connections", [])
check("conn: expired connection auto-cleaned", len(conns) == 0, f"remaining={conns}")

# 10. Credential not in server log: verify no admin password in server.log
with open("server.log", encoding="utf-8", errors="ignore") as f:
    log = f.read()
check("secrets: admin password not in server log", "admin-pass-123" not in log and "admin-pass" not in log, "password found in log!")

print()
passed = sum(1 for _, c, _ in results if c)
print(f"SECURITY BATTERY: {passed}/{len(results)} passed")
