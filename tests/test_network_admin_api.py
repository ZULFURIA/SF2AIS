from fastapi.testclient import TestClient

import main


def _client(monkeypatch):
    monkeypatch.setitem(main.app.dependency_overrides, main.admin_auth, lambda: "test-admin")
    return TestClient(main.app)


def _snapshot(monkeypatch, config):
    monkeypatch.setattr(main, "load_config", lambda: config)
    monkeypatch.setattr(main, "network_online_status", lambda cfg: (True, "online"))
    monkeypatch.setattr(main, "build_share_link", lambda cfg: "https://workspace.example.test")
    monkeypatch.setattr(main, "resolve_public_host", lambda cfg: "workspace.example.test")
    monkeypatch.setattr(main.network_connectivity, "default_route_ip", lambda: "192.168.1.20")
    monkeypatch.setattr(main.network_connectivity, "probe_https_endpoint", lambda *args, **kwargs: False)
    monkeypatch.setattr(main, "CLOUDFLARE_RELAY", type("Relay", (), {"status": staticmethod(lambda: {"provider": "cloudflare", "available": False, "state": "disabled"})})())


def test_router_mapping_stays_blocked_when_no_router_protocol_is_discovered(monkeypatch):
    monkeypatch.setattr(main, "ROUTER_DISCOVERY", {"available": False})
    monkeypatch.setattr(main, "MAPPING_PROTOCOLS", {"gateway": None, "upnp_igd": False, "nat_pmp": False, "pcp": False})
    client = _client(monkeypatch)
    response = client.post("/api/desktop/network/mapping", json={
        "method": "upnp-igd", "internal_port": 443, "external_port": 443,
        "approve": True, "confirm": "CREATE",
    })
    assert response.status_code == 409
    assert "UPnP IGD was not discovered" in response.json()["detail"]


def test_external_verification_uses_one_time_hashed_challenge(monkeypatch):
    config = {"network": {"port": 443}, "shares": []}
    _snapshot(monkeypatch, config)
    monkeypatch.setattr(main, "save_config", lambda value: None)
    monkeypatch.setattr(main, "audit_event", lambda *args, **kwargs: None)
    client = _client(monkeypatch)

    response = client.post("/api/desktop/network/verification")

    assert response.status_code == 200
    payload = response.json()
    assert payload["url"].startswith("https://workspace.example.test/network/verify#")
    assert payload["expires_in_seconds"] == 600
    challenge = config["network"]["external_probe"]
    assert challenge["status"] == "pending"
    assert len(challenge["token_hash"]) == 64
    assert payload["url"].split("#", 1)[1] not in str(config)


def test_network_snapshot_explains_tls_prerequisite_for_router_mapping(monkeypatch):
    config = {"network": {"port": 443}, "shares": []}
    _snapshot(monkeypatch, config)
    monkeypatch.setattr(main, "ROUTER_DISCOVERY", {"available": True, "router_address": "192.168.1.1"})
    monkeypatch.setattr(main, "MAPPING_PROTOCOLS", {"gateway": "192.168.1.1", "upnp_igd": True, "nat_pmp": False, "pcp": False})

    snapshot = main.desktop_network_admin_snapshot(config)

    assert snapshot["router_discovery"]["available"] is True
    assert snapshot["mapping_protocols"]["upnp_igd"] is True
    assert snapshot["https_listener_ready"] is False
    assert "reverse proxy" in snapshot["https_listener_status"]
