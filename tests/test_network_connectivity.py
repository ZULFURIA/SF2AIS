import pytest

import network_connectivity as network


def test_private_ip_validation():
    assert network._private_ip("192.168.1.1")
    assert network._private_ip("10.0.0.1")
    assert not network._private_ip("8.8.8.8")
    assert not network._private_ip("127.0.0.1")
    assert not network._private_ip("not-an-ip")


def test_dns_sd_query_has_question_section():
    packet = network._dns_query("_services._dns-sd._udp.local")
    assert len(packet) > 12
    assert packet[4:6] == b"\x00\x01"
    assert packet[-4:] == b"\x00\x0c\x00\x01"


def test_apply_mapping_rejects_invalid_ports_before_network(monkeypatch):
    monkeypatch.setattr(network, "default_route_ip", lambda: "192.168.1.20")
    router = {"router_address": "192.168.1.1", "control_url": "http://192.168.1.1/upnp/control", "service_type": network.WAN_SERVICE_TYPES[0]}
    with pytest.raises(network.NetworkSetupError):
        network.apply_mapping(router, 0, 443)
    with pytest.raises(network.NetworkSetupError):
        network.apply_mapping(router, 443, 70000)


def test_apply_mapping_requires_supported_protocol(monkeypatch):
    monkeypatch.setattr(network, "default_route_ip", lambda: "192.168.1.20")
    router = {"router_address": "192.168.1.1", "control_url": "http://192.168.1.1/upnp/control", "service_type": network.WAN_SERVICE_TYPES[0]}
    with pytest.raises(network.NetworkSetupError, match="Only TCP or UDP"):
        network.apply_mapping(router, 443, 443, protocol="SCTP")


def test_apply_mapping_builds_expected_soap_request(monkeypatch):
    captured = {}
    monkeypatch.setattr(network, "default_route_ip", lambda: "192.168.1.20")

    def fake_soap(url, service, action, arguments):
        captured.update({"url": url, "service": service, "action": action, "arguments": arguments})
        return None

    monkeypatch.setattr(network, "_soap", fake_soap)
    router = {"router_address": "192.168.1.1", "control_url": "http://192.168.1.1/upnp/control", "service_type": network.WAN_SERVICE_TYPES[0]}
    result = network.apply_mapping(router, 443, 8443, lease_seconds=90000)
    assert result["created"] is True
    assert captured["action"] == "AddPortMapping"
    assert captured["arguments"]["NewInternalClient"] == "192.168.1.20"
    assert captured["arguments"]["NewExternalPort"] == "8443"
    assert captured["arguments"]["NewLeaseDuration"] == "86400"


def test_description_rejects_non_private_router_url():
    with pytest.raises(network.NetworkSetupError, match="private local"):
        network._fetch_description("http://example.com/device.xml", "192.168.1.1")


def test_nat_pmp_mapping_request_and_response(monkeypatch):
    import struct
    captured = {}
    monkeypatch.setattr(network, "_udp_exchange", lambda gateway, payload, expected: (
        captured.update({"gateway": gateway, "payload": payload, "expected": expected})
        or struct.pack("!BBHIHHI", 0, 130, 0, 12, 4444, 8443, 86400)
    ))
    result = network.nat_pmp_map("192.168.1.1", 4444, 8443)
    assert result["created"] is True
    assert result["method"] == "nat-pmp"
    assert captured["payload"] == struct.pack("!BBHHHI", 0, 2, 0, 4444, 8443, 86400)


def test_nat_pmp_remove_uses_zero_lease(monkeypatch):
    import struct
    captured = {}
    monkeypatch.setattr(network, "_udp_exchange", lambda gateway, payload, expected: (
        captured.update({"payload": payload})
        or struct.pack("!BBHIHHI", 0, 130, 0, 15, 4444, 8443, 0)
    ))
    result = network.nat_pmp_remove("192.168.1.1", 8443, "TCP", internal_port=4444)
    assert result["removed"] is True
    assert captured["payload"] == struct.pack("!BBHHHI", 0, 2, 0, 4444, 8443, 0)


def test_pcp_announce_response(monkeypatch):
    response = bytearray(24)
    response[0] = 2
    response[1] = 0x80
    response[4] = 0
    monkeypatch.setattr(network, "default_route_ip", lambda: "192.168.1.20")
    monkeypatch.setattr(network, "_udp_exchange", lambda *args, **kwargs: bytes(response))
    assert network.pcp_announce("192.168.1.1")["available"] is True


def test_pcp_map_builds_rfc_sized_request_and_validates_nonce(monkeypatch):
    import struct
    captured = {}
    monkeypatch.setattr(network, "default_route_ip", lambda: "192.168.1.20")

    def exchange(gateway, payload, expected):
        captured["payload"] = payload
        response = bytearray(60)
        response[0] = 2
        response[1] = 0x81
        response[4] = 0
        response[8:12] = struct.pack("!I", 86400)
        response[24:36] = payload[24:36]
        response[36] = 6
        response[40:44] = struct.pack("!HH", 4444, 8443)
        response[44:60] = ipaddress.ip_address("203.0.113.5").packed
        return bytes(response)

    import ipaddress
    monkeypatch.setattr(network, "_udp_exchange", exchange)
    result = network.pcp_map("192.168.1.1", 4444, 8443)
    assert result["created"] is True
    assert result["method"] == "pcp"
    assert len(captured["payload"]) == 60
    assert captured["payload"][0:2] == b"\x02\x01"


def test_mapping_protocol_discovery_reports_no_gateway(monkeypatch):
    monkeypatch.setattr(network, "default_gateway", lambda: None)
    result = network.discover_mapping_protocols(None)
    assert result["gateway"] is None
    assert result["nat_pmp"] is False
    assert result["pcp"] is False


def test_pcp_remove_reuses_original_nonce(monkeypatch):
    import struct
    import ipaddress
    captured = {}
    monkeypatch.setattr(network, "default_route_ip", lambda: "192.168.1.20")
    nonce = bytes.fromhex("00112233445566778899aabb")
    def exchange(gateway, payload, expected):
        captured["payload"] = payload
        response = bytearray(60)
        response[0], response[1], response[4] = 2, 0x81, 0
        response[24:36] = nonce
        response[36] = 6
        response[40:44] = struct.pack("!HH", 4444, 8443)
        return bytes(response)
    monkeypatch.setattr(network, "_udp_exchange", exchange)
    result = network.pcp_remove("192.168.1.1", 4444, 8443, "TCP", nonce.hex())
    assert result["removed"] is True
    assert captured["payload"][24:36] == nonce
    assert struct.unpack("!I", captured["payload"][4:8])[0] == 0



def test_description_rejects_private_host_different_from_ssdp_peer():
    with pytest.raises(network.NetworkSetupError, match="SSDP responder"):
        network._fetch_description("http://192.168.1.99/device.xml", "192.168.1.1")


def test_probe_https_endpoint_rejects_non_private_target():
    assert network.probe_https_endpoint("8.8.8.8", 443) is False
