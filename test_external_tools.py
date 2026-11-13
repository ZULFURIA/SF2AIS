"""Comprehensive external tools test for SF2AiS.

Tests the full external API surface: discovery, connection lifecycle,
session lifecycle, capabilities, file operations, workspace, IDE,
computer-use, monitoring, and audit.
"""
import os
import sys
import json
import base64
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, ".")

import main
from fastapi.testclient import TestClient

# Test credentials
ADMIN_USER, ADMIN_PASS = "admin", "Admin-Pass-123!"
SHARE_USER, SHARE_PASS = "tester", "Share-Pass-123!"

# Create test workspace
temp = tempfile.TemporaryDirectory()
test_root = Path(temp.name)
(test_root / "src").mkdir()
(test_root / "src" / "hello.py").write_text("print('hello')\n", encoding="utf-8")
(test_root / ".env").write_text("SECRET=value", encoding="utf-8")
(test_root / "readme.md").write_text("# Test\n", encoding="utf-8")

config = {
    "admin": {"username": ADMIN_USER, "password_hash": main.bcrypt.hash(ADMIN_PASS)},
    "network": {"method": "static", "value": "127.0.0.1", "port": 8000},
    "shares": [{
        "id": "share-1",
        "username": SHARE_USER,
        "password_hash": main.bcrypt.hash(SHARE_PASS),
        "folder": str(test_root),
        "last_seen": None,
        "cli_enabled": True,
        "tunnel_enabled": True,
        "workspace_write_enabled": False,
        "ide_enabled": True,
        "computer_use_enabled": False,
    }],
}

# Patch config loading
main.load_config = lambda: config
main.save_config = lambda cfg: None

def auth(user, passwd):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{passwd}".encode()).decode()}

def admin_auth():
    return auth(ADMIN_USER, ADMIN_PASS)

def share_auth():
    return auth(SHARE_USER, SHARE_PASS)

results = []

def test(name, method, path, expected_status=None, **kwargs):
    """Run a test and record the result."""
    client = TestClient(main.app)
    try:
        response = client.request(method, path, **kwargs)
        status = response.status_code
        ok = True
        if expected_status is not None:
            ok = (status == expected_status)
        results.append({
            "name": name,
            "method": method,
            "path": path,
            "status": status,
            "expected": expected_status,
            "ok": ok,
            "body": response.text[:200] if status >= 400 else None,
        })
        return response
    except Exception as e:
        results.append({
            "name": name,
            "method": method,
            "path": path,
            "status": "ERROR",
            "expected": expected_status,
            "ok": False,
            "body": str(e),
        })
        return None
    finally:
        client.close()

print("=" * 70)
print("SF2AiS EXTERNAL TOOLS TEST SUITE")
print("=" * 70)

# --- 1. Discovery ---
print("\n[1] DISCOVERY")
r = test("GET /api/connections/discover", "GET", "/api/connections/discover", 200, headers=admin_auth())
if r and r.status_code == 200:
    # Returns HTML page with embedded manifest
    body = r.text
    print(f"  Response length: {len(body)} chars (HTML page with manifest)")
    print(f"  Contains protocol: {'sf2ais.connection-discover' in body}")

# --- 2. Connection Lifecycle ---
print("\n[2] CONNECTION LIFECYCLE")
r = test("POST /api/connections (create)", "POST", "/api/connections", 201,
         json={
             "client_type": "ai",
             "client_app": "ChatGPT",
             "client_version": "1.0.0",
             "identity": "chatgpt-test",
             "identity_verified": True,
             "client_credential": "cred-123",
             "capabilities": ["filesystem", "cli"],
             "workspace": str(test_root),
             "purpose": "Testing",
             "duration_seconds": 3600,
         },
         headers=admin_auth())
if r and r.status_code == 201:
    conn_data = r.json()
    conn = conn_data.get("connection", conn_data)
    conn_id = conn.get("id") or conn.get("connection_id")
    print(f"  Connection created: {conn_id}")

    r = test("GET /api/connections (list)", "GET", "/api/connections", 200, headers=admin_auth())
    r = test(f"GET /api/connections/{conn_id}", "GET", f"/api/connections/{conn_id}", 200, headers=admin_auth())
    r = test(f"POST /api/connections/{conn_id}/approve", "POST", f"/api/connections/{conn_id}/approve", 200,
             headers=admin_auth())
    r = test(f"POST /api/connections/{conn_id}/status", "POST", f"/api/connections/{conn_id}/status", 200,
             json={"status": "approved"},
             headers=admin_auth())
else:
    conn_id = None

# --- 3. Session Lifecycle ---
print("\n[3] SESSION LIFECYCLE")
if conn_id:
    r = test("POST /api/sessions (create)", "POST", "/api/sessions", 201,
             json={"connection_id": conn_id},
             headers=admin_auth())
    if r and r.status_code == 201:
        session_data = r.json()
        sess = session_data.get("session", session_data)
        session_id = sess.get("session_id") or sess.get("id")
        print(f"  Session created: {session_id}")

        r = test(f"GET /api/sessions/{session_id}", "GET", f"/api/sessions/{session_id}", 200,
                 headers=admin_auth())
        if r and r.status_code == 200:
            init_pkg = r.json()
            print(f"  Init package keys: {list(init_pkg.keys())}")

        r = test(f"POST /api/sessions/{session_id}/ack", "POST", f"/api/sessions/{session_id}/ack", 200,
                 json={
                     "sf2ais_law_version": "1.0.0",
                     "tools_discovered": [],
                     "skills_discovered": [],
                     "permissions_understood": True,
                     "unsupported_capabilities": [],
                     "operational_ready": True,
                 },
                 headers=admin_auth())
    else:
        session_id = None
else:
    session_id = None

# --- 4. Capabilities ---
print("\n[4] CAPABILITIES")
r = test("GET /api/capabilities", "GET", "/api/capabilities", 200)
r = test("GET /api/capabilities/tools", "GET", "/api/capabilities/tools", 200)
r = test("GET /api/capabilities/skills", "GET", "/api/capabilities/skills", 200)
r = test("GET /api/capabilities/workspaces", "GET", "/api/capabilities/workspaces", 200, headers=admin_auth())
r = test("GET /api/capabilities/access-types", "GET", "/api/capabilities/access-types", 200)
r = test("GET /api/capabilities/system", "GET", "/api/capabilities/system", 200)

# --- 5. File Operations (Workspace) ---
print("\n[5] WORKSPACE FILE OPERATIONS")
r = test("GET /api/workspace/status", "GET", "/api/workspace/status", 200, headers=share_auth())
r = test("GET /api/workspace/tree", "GET", "/api/workspace/tree", 200, headers=share_auth())
if r and r.status_code == 200:
    tree = r.json()
    print(f"  Tree entries: {len(tree.get('entries', tree.get('items', [])))}")

r = test("GET /api/workspace/file?path=readme.md", "GET", "/api/workspace/file?path=readme.md", 200, headers=share_auth())
if r and r.status_code == 200:
    file_data = r.json()
    print(f"  File content length: {len(file_data.get('content', ''))}")

# Test write (should fail - workspace_write_enabled is False)
r = test("PUT /api/workspace/file (write blocked)", "PUT", "/api/workspace/file", 403,
         json={"path": "readme.md", "content": "modified"},
         headers=share_auth())

# Test directory creation (blocked - workspace_write_enabled is False)
r = test("POST /api/workspace/directory (blocked)", "POST", "/api/workspace/directory", 403,
         json={"path": "newdir"},
         headers=share_auth())

# Test move (blocked)
r = test("POST /api/workspace/move (blocked)", "POST", "/api/workspace/move", 403,
         json={"source": "newdir", "destination": "newdir2"},
         headers=share_auth())

# Test delete (blocked)
r = test("DELETE /api/workspace/path (blocked)", "DELETE", "/api/workspace/path?path=newdir2", 403,
         headers=share_auth())

# --- 6. IDE Operations ---
print("\n[6] IDE OPERATIONS")
r = test("GET /api/ide/status", "GET", "/api/ide/status", 200, headers=share_auth())
r = test("GET /api/ide/tree", "GET", "/api/ide/tree", 200, headers=share_auth())
r = test("GET /api/ide/file?path=src/hello.py", "GET", "/api/ide/file?path=src/hello.py", 200, headers=share_auth())

# --- 7. Computer Use ---
print("\n[7] COMPUTER USE")
r = test("GET /api/computer-use/status", "GET", "/api/computer-use/status", 200, headers=share_auth())
r = test("POST /api/computer-use/sessions (create)", "POST", "/api/computer-use/sessions", 403,
         json={"identity": "test-client", "purpose": "testing"},
         headers=share_auth())
if r and r.status_code == 201:
    cu_session = r.json()
    cu_id = cu_session.get("session_id") or cu_session.get("id")
    print(f"  CU session: {cu_id}")
    r = test(f"POST /api/computer-use/sessions/{cu_id}/observe", "POST", f"/api/computer-use/sessions/{cu_id}/observe", 200,
             headers=share_auth())
    r = test(f"DELETE /api/computer-use/sessions/{cu_id}", "DELETE", f"/api/computer-use/sessions/{cu_id}", 200,
             headers=share_auth())

# --- 8. Monitoring ---
print("\n[8] MONITORING")
r = test("GET /api/monitor/sessions", "GET", "/api/monitor/sessions", 200, headers=admin_auth())
r = test("GET /api/monitor/events", "GET", "/api/monitor/events", 200, headers=admin_auth())
r = test("POST /api/monitor/events (no session_id)", "POST", "/api/monitor/events", 400,
         json={"event_type": "test", "detail": "test event"},
         headers=admin_auth())
if session_id:
    r = test("POST /api/monitor/events", "POST", "/api/monitor/events", 201,
             json={"session_id": session_id, "action": "test", "detail": "test event"},
             headers=admin_auth())

# --- 9. Audit ---
print("\n[9] AUDIT")
r = test("GET /api/audit", "GET", "/api/audit", 200, headers=admin_auth())
if r and r.status_code == 200:
    audit = r.json()
    print(f"  Audit entries: {len(audit.get('events', audit.get('entries', [])))}")

# --- 10. Admin Endpoints ---
print("\n[10] ADMIN ENDPOINTS")
r = test("GET /api/status", "GET", "/api/status", 200, headers=admin_auth())
r = test("GET /api/desktop/state", "GET", "/api/desktop/state", 200, headers=admin_auth())
r = test("GET /api/desktop/activity", "GET", "/api/desktop/activity", 200, headers=admin_auth())
r = test("GET /api/network/status", "GET", "/api/network/status", 200, headers=admin_auth())
r = test("GET /api/relay/status", "GET", "/api/relay/status", 200, headers=admin_auth())

# --- 11. Auth Failure Tests ---
print("\n[11] AUTHENTICATION & AUTHORIZATION")
r = test("GET /api/status (no auth)", "GET", "/api/status", 401)
r = test("GET /api/status (wrong pass)", "GET", "/api/status", 401, headers=auth(ADMIN_USER, "wrong"))
r = test("GET /api/audit (share auth - rejected)", "GET", "/api/audit", 401, headers=share_auth())

# --- Summary ---
print("\n" + "=" * 70)
print("TEST SUMMARY")
print("=" * 70)
passed = sum(1 for r in results if r["ok"])
failed = sum(1 for r in results if not r["ok"])
print(f"Total: {len(results)} | Passed: {passed} | Failed: {failed}")
print()

if failed > 0:
    print("FAILED TESTS:")
    for r in results:
        if not r["ok"]:
            print(f"  ✗ {r['name']}")
            print(f"    {r['method']} {r['path']}")
            print(f"    Status: {r['status']} (expected {r['expected']})")
            if r.get("body"):
                print(f"    Body: {r['body'][:150]}")
            print()

print("\nPASSED TESTS:")
for r in results:
    if r["ok"]:
        print(f"  ✓ {r['name']} [{r['status']}]")

temp.cleanup()
print("\nDone.")
