from fastapi.testclient import TestClient

import main


def _admin_client(monkeypatch):
    monkeypatch.setitem(main.app.dependency_overrides, main.admin_auth, lambda: "test-admin")
    return TestClient(main.app)


def _patch_network_snapshot(monkeypatch, config=None):
    monkeypatch.setattr(main, "load_config", lambda: config if config is not None else {})
    monkeypatch.setattr(main, "network_online_status", lambda cfg: (True, "online"))
    monkeypatch.setattr(main, "build_share_link", lambda cfg: "https://workspace.example.test")
    monkeypatch.setattr(main, "resolve_public_host", lambda cfg: "workspace.example.test")
    monkeypatch.setattr(main.network_connectivity, "default_route_ip", lambda: "192.168.1.20")
    monkeypatch.setattr(main.network_connectivity, "probe_https_endpoint", lambda *args, **kwargs: False)
    monkeypatch.setattr(main, "CLOUDFLARE_RELAY", type("Relay", (), {"status": staticmethod(lambda: {"provider": "cloudflare", "available": False, "state": "disabled"})})())


def test_workspace_page_uses_shared_renderer_and_native_network_controls(monkeypatch):
    client = _admin_client(monkeypatch)
    response = client.get("/workspace")

    assert response.status_code == 200
    assert 'href="/workspace/styles.css"' in response.text
    assert '<script src="/workspace/web-adapter.js"></script>' in response.text
    assert '<script src="/workspace/app.js"></script>' in response.text
    assert "data-runtime=\"web\"" in response.text or "document.documentElement.dataset.runtime" in (
        client.get("/workspace/web-adapter.js").text
    )
    assert 'id="btn-router-discover"' in response.text
    assert 'id="ddns-form"' in response.text
    assert 'id="router-mapping-form"' in response.text
    assert 'data-page="monitor"' in response.text
    assert 'data-page="downloads"' in response.text
    assert 'id="page-downloads"' in response.text
    assert 'id="btn-open-router-admin"' in response.text
    assert 'class="router-manual-guide"' in response.text
    assert 'id="page-monitor"' in response.text
    assert 'id="monitor-session-list"' in response.text
    assert "/dashboard?view=network" not in response.text
    assert "LOCAL AGENT CONFIGURATION" not in response.text
    assert "SERVER CONFIGURATION" in response.text


def test_workspace_assets_are_served_from_the_desktop_renderer(monkeypatch):
    client = _admin_client(monkeypatch)
    css = client.get("/workspace/styles.css")
    app_js = client.get("/workspace/app.js")
    adapter_js = client.get("/workspace/web-adapter.js")

    assert css.status_code == 200
    assert "backdrop-filter" in css.text
    assert app_js.status_code == 200
    assert "refreshDesktopState" in app_js.text
    assert "renderNetworkAdmin" in app_js.text
    assert "/api/monitor/sessions" in app_js.text
    assert "/api/monitor/events?limit=100" in app_js.text
    assert "downloadInstaller" in adapter_js.text
    assert "/probe/desktop-app/" in adapter_js.text
    assert "data-installer-platform" in app_js.text
    assert "setInterval(()=>refreshMonitor(),5000)" in app_js.text
    assert adapter_js.status_code == 200
    assert 'credentials: "same-origin"' in adapter_js.text
    assert 'runtime: "web"' in adapter_js.text
    assert 'location.assign("/dashboard"' not in adapter_js.text


def test_desktop_installer_route_serves_exact_windows_architecture(monkeypatch):
    client = _admin_client(monkeypatch)

    response = client.get("/probe/desktop-app/windows?arch=x64")

    assert response.status_code == 200
    assert "SF2AiS-Desktop-Setup-1.1.3-x64.exe" in response.headers["content-disposition"]
    assert len(response.content) > 1024 * 1024


def test_workspace_requires_admin_authentication():
    client = TestClient(main.app)
    page = client.get("/workspace")
    asset = client.get("/workspace/app.js")
    assert page.status_code == 401
    assert asset.status_code == 401


def test_ai_realtime_monitor_api_returns_session_and_activity_metadata(monkeypatch):
    monkeypatch.setattr(main, "_load_state", lambda: {
        "sessions": {
            "session-1": {
                "client_id": "client-1",
                "client_type": "ChatGPT",
                "identity": "Test AI",
                "share_id": "share-1",
                "share_path": "C:/workspace",
                "capabilities": ["workspace.read"],
                "state": "active",
                "expires_at": "2026-11-12T20:00:00+00:00",
                "last_seen": "2026-11-12T19:00:00+00:00",
                "activity": [{"at": "2026-11-12T19:00:00+00:00", "action": "file.read", "detail": {"path": "README.md"}}],
            }
        }
    })
    client = _admin_client(monkeypatch)

    sessions = client.get("/api/monitor/sessions")
    events = client.get("/api/monitor/events?limit=100&session_id=session-1")

    assert sessions.status_code == 200
    assert sessions.json()["sessions"][0]["identity"] == "Test AI"
    assert sessions.json()["sessions"][0]["capabilities"] == ["workspace.read"]
    assert events.status_code == 200
    assert events.json()["events"][0]["action"] == "file.read"


def test_ai_realtime_monitor_api_requires_admin_authentication():
    client = TestClient(main.app)
    assert client.get("/api/monitor/sessions").status_code == 401
    assert client.get("/api/monitor/events").status_code == 401


def test_desktop_state_exposes_safe_network_snapshot_without_ddns_secret(monkeypatch):
    config = {"network": {"ddns": {"provider": "duckdns", "domain": "workspace.duckdns.org", "token": "never-return-this"}}}
    _patch_network_snapshot(monkeypatch, config)
    client = _admin_client(monkeypatch)

    response = client.get("/api/desktop/state")

    assert response.status_code == 200
    network = response.json()["network"]
    assert network["public_host"] == "workspace.example.test"
    assert network["local_lan_ip"] == "192.168.1.20"
    assert network["ddns_configured"] is True
    assert "never-return-this" not in response.text
    assert network["relay"]["provider"] == "cloudflare"


def test_network_port_and_ddns_settings_validate_and_persist(monkeypatch):
    config = {"network": {"port": 443, "ddns": {"provider": "duckdns", "domain": "", "token": ""}}, "shares": []}
    _patch_network_snapshot(monkeypatch, config)
    monkeypatch.setattr(main, "save_config", lambda value: None)
    monkeypatch.setattr(main, "audit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "MDNS_ADVERTISER", type("MDNS", (), {"stop": lambda self: None})())
    client = _admin_client(monkeypatch)

    invalid_port = client.patch("/api/desktop/network", json={"port": 70000})
    assert invalid_port.status_code == 400
    saved_port = client.patch("/api/desktop/network", json={"port": 8443})
    assert saved_port.status_code == 200
    assert config["network"]["port"] == 8443

    invalid_domain = client.patch("/api/desktop/network/ddns", json={"domain": "https://bad.example", "token": "secret"})
    assert invalid_domain.status_code == 400
    saved_ddns = client.patch("/api/desktop/network/ddns", json={"domain": "workspace.duckdns.org", "token": "test-token"})
    assert saved_ddns.status_code == 200
    assert config["network"]["ddns"]["token"] == "test-token"
    assert saved_ddns.json()["network"]["ddns_configured"] is True
    assert "test-token" not in saved_ddns.text


def test_router_mapping_requires_explicit_approval_after_auth(monkeypatch):
    client = _admin_client(monkeypatch)
    response = client.post("/api/desktop/network/mapping", json={
        "method": "upnp-igd", "internal_port": 443, "external_port": 443,
        "approve": False, "confirm": "",
    })
    assert response.status_code == 400
    assert "Explicit router-forwarding approval" in response.json()["detail"]


def test_router_discovery_is_read_only_and_returns_protocol_diagnostics(monkeypatch):
    _patch_network_snapshot(monkeypatch, {"network": {}, "shares": []})
    monkeypatch.setattr(main.network_connectivity, "discover_router", lambda timeout=1.5: {"available": True, "router_address": "192.168.1.1"})
    monkeypatch.setattr(main.network_connectivity, "discover_mapping_protocols", lambda router: {"gateway": "192.168.1.1", "upnp_igd": True, "nat_pmp": False, "pcp": False})
    monkeypatch.setattr(main.network_connectivity, "diagnose_nat", lambda router: {"external_reachability": "unverified"})
    monkeypatch.setattr(main, "audit_event", lambda *args, **kwargs: None)
    client = _admin_client(monkeypatch)

    response = client.post("/api/desktop/network/discover")

    assert response.status_code == 200
    network = response.json()["network"]
    assert network["router_discovery"]["available"] is True
    assert network["mapping_protocols"]["upnp_igd"] is True
    assert network["nat_diagnostics"]["external_reachability"] == "unverified"
    assert network.get("router_mapping") is None


def test_legacy_dashboard_redirects_to_shared_workspace_and_monitor(monkeypatch):
    client = _admin_client(monkeypatch)

    dashboard = client.get("/dashboard", follow_redirects=False)
    realtime = client.get("/dashboard?view=realtime", follow_redirects=False)

    assert dashboard.status_code == 307
    assert dashboard.headers["location"] == "/workspace"
    assert realtime.status_code == 307
    assert realtime.headers["location"] == "/workspace#monitor"


def test_web_adapter_uses_authenticated_backend_api_for_health():
    from pathlib import Path

    adapter = (Path(main.__file__).parent / "probe-app" / "renderer" / "web-adapter.js").read_text(encoding="utf-8")

    assert 'path: "/api/desktop/state"' in adapter
    assert "backendHealthy: true" in adapter
    assert "running: true" not in adapter
    assert 'currentIp: "Server session"' not in adapter
