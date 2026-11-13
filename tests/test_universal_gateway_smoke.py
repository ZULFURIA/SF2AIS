"""Smoke test for the SF2AiS universal gateway routes (no external services)."""
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or ".")

import pytest
from fastapi.testclient import TestClient

import main

ADMIN_USER = "test-admin"
ADMIN_PASS = "Correct-Horse-123!"
ADMIN_HASH = main.bcrypt.hash(ADMIN_PASS)

TEST_SHARE = os.path.abspath("./data/test-share")

# One shared config object for the whole test session; in-memory mutation must survive.
CONFIG = {
    "admin": {"username": ADMIN_USER, "password_hash": ADMIN_HASH},
    "settings": main.DEFAULT_SETTINGS,
    "shares": [{
        "id": "share-1",
        "folder": TEST_SHARE,
        "username": "test-share",
        "client_id": "client-1",
        "authorized_clients": ["client-1"],
        "capabilities": ["filesystem"],
        "permission": "read-write",
    }],
    "connections": [],
    "sessions": {},
    "file_locks": {},
    "blacklist": [],
    "skill_registry": [],
    "tool_registry": [],
    "component_versions": main._COMPONENT_VERSIONS,
}


def _admin_header():
    token = base64.b64encode(f"{ADMIN_USER}:{ADMIN_PASS}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _config():
    return {
        "admin": {"username": ADMIN_USER, "password_hash": ADMIN_HASH},
        "settings": main.DEFAULT_SETTINGS,
        "shares": [{
            "id": "share-1",
            "folder": TEST_SHARE,
            "username": "test-share",
            "client_id": "client-1",
            "authorized_clients": ["client-1"],
            "capabilities": ["filesystem"],
            "permission": "read-write",
        }],
        "connections": [],
        "sessions": {},
        "file_locks": {},
        "blacklist": [],
        "skill_registry": [],
        "tool_registry": [],
        "component_versions": main._COMPONENT_VERSIONS,
    }


@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


def test_status_and_capabilities(client, monkeypatch):
    monkeypatch.setattr(main, "load_config", lambda: CONFIG)
    monkeypatch.setattr(main, "save_config", lambda cfg: None)
    r = client.get("/api/capabilities")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "tool_registry" in body["capabilities"]


def test_connection_lifecycle(client, monkeypatch):
    monkeypatch.setattr(main, "load_config", lambda: CONFIG)
    monkeypatch.setattr(main, "save_config", lambda cfg: None)
    headers = _admin_header()
    # Create a pending connection request.
    r = client.post("/api/connections", json={
        "client_type": "ai", "client_app": "TestAgent", "client_version": "1.0.0",
        "identity": "TestAI", "capabilities": ["filesystem", "cli"], "workspace": {"id": "share-1"},
        "purpose": "smoke", "duration_seconds": 3600,
    }, headers=headers)
    assert r.status_code == 201, r.text
    conn = r.json()["connection"]
    cid = conn["id"]
    assert conn["status"] == "pending"

    # Status shows pending (POST with a JSON body as the route requires).
    r = client.post(f"/api/connections/{cid}/status", json={"status": "pending"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["connection"]["status"] == "pending"

    # Denying before approval is allowed.
    r = client.post(f"/api/connections/{cid}/deny", headers=headers)
    assert r.status_code == 200

    # Re-create the connection so we can test approval.
    r = client.post("/api/connections", json={
        "client_type": "ai", "client_app": "TestAgent", "client_version": "1.0.0",
        "identity": "TestAI-2", "capabilities": ["filesystem"], "workspace": {"id": "share-1"},
        "purpose": "approve", "duration_seconds": 3600,
    }, headers=headers)
    conn = r.json()["connection"]
    cid = conn["id"]
    assert conn["status"] == "pending"

    # Approve.
    r = client.post(f"/api/connections/{cid}/approve", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["connection"]["status"] == "approved"

    # Create a session against the approved connection.
    r = client.post("/api/sessions", json={"connection_id": cid}, headers=headers)
    assert r.status_code == 201, r.text
    session = r.json()["session"]
    sid = session["session_id"]
    assert session["permissions_manifest"]["write"] is True

    # Acknowledge the initialization package.
    r = client.post(f"/api/sessions/{sid}/ack", json={
        "sf2ais_law_version": "1.0.0",
        "tools_discovered": ["fs_read", "fs_write"],
        "skills_discovered": [],
        "permissions_understood": True,
        "unsupported_capabilities": [],
        "operational_ready": True,
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["session"]["state"] == "initialized"

    # Monitor sees the session.
    r = client.get("/api/monitor/sessions", headers=headers)
    assert r.status_code == 200
    assert any(s["session_id"] == sid for s in r.json()["sessions"])


def test_file_locks_api(client, monkeypatch):
    monkeypatch.setattr(main, "load_config", lambda: CONFIG)
    monkeypatch.setattr(main, "save_config", lambda cfg: None)
    headers = _admin_header()
    headers["X-Sf2AiS-Session"] = "session-1"
    r = client.post("/api/files/locks", json={
        "path": TEST_SHARE + "/work.txt", "session_id": "session-1", "identity": "TestAI",
    }, headers=headers)
    assert r.status_code == 201, r.text
    lock = r.json()["lock"]
    assert lock["path"] == TEST_SHARE + "/work.txt"
    assert lock["owner_identity"] == "TestAI"

    # The same session may release its lock.
    r = client.delete(f"/api/files/locks/{TEST_SHARE}/work.txt", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["lock"]["owner_session"] is None


def test_monitor_events_feed(client, monkeypatch):
    monkeypatch.setattr(main, "load_config", lambda: CONFIG)
    monkeypatch.setattr(main, "save_config", lambda cfg: None)
    headers = _admin_header()
    r = client.get("/api/monitor/events", headers=headers)
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["events"], list)
