"""Local multicast discovery and consent-based UPnP IGD port mapping.

No router credentials are requested or stored. Mapping changes are made only
when an administrator explicitly calls apply_mapping().
"""
from __future__ import annotations

import ipaddress
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from typing import Any

SSDP_GROUP = ("239.255.255.250", 1900)
MDNS_GROUP = ("224.0.0.251", 5353)
UPNP_ST = "urn:schemas-upnp-org:device:InternetGatewayDevice:1"
WAN_SERVICE_TYPES = (
    "urn:schemas-upnp-org:service:WANIPConnection:2",
    "urn:schemas-upnp-org:service:WANIPConnection:1",
    "urn:schemas-upnp-org:service:WANPPPConnection:1",
)


class NetworkSetupError(RuntimeError):
    pass


def _private_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        return address.is_private and not address.is_loopback and not address.is_link_local
    except ValueError:
        return False


def default_route_ip() -> str | None:
    """Return the local interface address selected for internet traffic."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        address = sock.getsockname()[0]
        return address if _private_ip(address) else None
    except OSError:
        return None
    finally:
        sock.close()


def multicast_discovery(timeout: float = 1.5) -> dict[str, Any]:
    """Discover IGD devices using SSDP multicast and probe mDNS availability."""
    local_ip = default_route_ip()
    message = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        f"ST: {UPNP_ST}\r\n\r\n"
    ).encode("ascii")
    devices: dict[str, dict[str, str]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.settimeout(0.25)
        sock.sendto(message, SSDP_GROUP)
        deadline = time.monotonic() + max(0.25, min(timeout, 4.0))
        while time.monotonic() < deadline:
            try:
                payload, peer = sock.recvfrom(8192)
            except socket.timeout:
                continue
            text = payload.decode("iso-8859-1", errors="replace")
            headers = {}
            for line in text.splitlines()[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            location = headers.get("location", "")
            if _private_ip(peer[0]) and location:
                parsed = urllib.parse.urlsplit(location)
                try:
                    host = parsed.hostname or ""
                    if parsed.scheme == "http" and _private_ip(host):
                        devices[peer[0]] = {
                            "address": peer[0],
                            "location": location,
                            "server": headers.get("server", "")[:160],
                            "st": headers.get("st", ""),
                        }
                except ValueError:
                    continue
    except OSError:
        pass
    finally:
        sock.close()

    # Send a bounded DNS-SD multicast query. The response is not treated as
    # router capability; it is used for local Sf2AiS/service discovery only.
    mdns_sent = False
    try:
        query = _dns_query("_services._dns-sd._udp.local")
        mdns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        mdns.settimeout(0.1)
        mdns.sendto(query, MDNS_GROUP)
        mdns_sent = True
        mdns.close()
    except OSError:
        pass
    return {
        "local_address": local_ip,
        "ssdp_available": bool(devices),
        "upnp_routers": list(devices.values()),
        "mdns_query_sent": mdns_sent,
        "discovered_at": time.time(),
    }


def _dns_query(name: str) -> bytes:
    import random
    labels = b"".join(bytes([len(part)]) + part.encode("ascii") for part in name.split(".")) + b"\0"
    return (random.randrange(0, 65536).to_bytes(2, "big") + b"\x00\x00\x00\x01"
            + b"\x00\x00\x00\x00\x00\x00" + labels + b"\x00\x0c\x00\x01")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_description(location: str, expected_router_ip: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(location)
    if (parsed.scheme != "http" or not parsed.hostname or not _private_ip(parsed.hostname)
            or parsed.hostname != expected_router_ip or parsed.username or parsed.password):
        raise NetworkSetupError("Router description URL must point directly to the private local SSDP responder.")
    request = urllib.request.Request(location, headers={"User-Agent": "Sf2AiS-NetworkManager/1.0"})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())
        with opener.open(request, timeout=3) as response:
            body = response.read(512 * 1024)
            final = urllib.parse.urlsplit(response.geturl())
    except (OSError, urllib.error.URLError) as exc:
        raise NetworkSetupError("Could not read the local router description: %s" % exc) from exc
    if final.scheme != "http" or not final.hostname or final.hostname != expected_router_ip:
        raise NetworkSetupError("Router description redirected away from the SSDP responder.")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise NetworkSetupError("Router returned invalid device-description XML.") from exc
    base = next((node.text for node in root.iter() if node.tag.endswith("URLBase") and node.text), location)
    base_parts = urllib.parse.urlsplit(base)
    if base_parts.scheme != "http" or base_parts.hostname != expected_router_ip:
        raise NetworkSetupError("Router XML URLBase does not match the SSDP responder.")
    for service in root.iter():
        if not service.tag.endswith("service"):
            continue
        fields = {child.tag.split("}")[-1]: (child.text or "").strip()
                  for child in list(service)}
        service_type = fields.get("serviceType", "")
        if service_type in WAN_SERVICE_TYPES:
            control = urllib.parse.urljoin(base, fields.get("controlURL", ""))
            control_parts = urllib.parse.urlsplit(control)
            if (control_parts.scheme != "http" or control_parts.hostname != expected_router_ip
                    or control_parts.username or control_parts.password):
                raise NetworkSetupError("Router control endpoint does not match the SSDP responder.")
            return service_type, control
    raise NetworkSetupError("Router does not advertise a supported WAN IP/PPP connection service.")


def discover_router(timeout: float = 1.5) -> dict[str, Any]:
    result = multicast_discovery(timeout)
    if not result["upnp_routers"]:
        return {"available": False, "method": "upnp-igd", "reason": "No UPnP Internet Gateway Device replied to SSDP multicast.", **result}
    router = result["upnp_routers"][0]
    service_type, control_url = _fetch_description(router["location"], router["address"])
    return {
        "available": True, "method": "upnp-igd", "router_address": router["address"],
        "server": router.get("server", ""), "service_type": service_type,
        "control_url": control_url, **{k: v for k, v in result.items() if k != "upnp_routers"},
    }


def _soap(control_url: str, service_type: str, action: str, arguments: dict[str, str]) -> ET.Element:
    envelope = ET.Element("{http://schemas.xmlsoap.org/soap/envelope/}Envelope")
    envelope.set("{http://schemas.xmlsoap.org/soap/envelope/}encodingStyle",
                 "http://schemas.xmlsoap.org/soap/encoding/")
    body = ET.SubElement(envelope, "{http://schemas.xmlsoap.org/soap/envelope/}Body")
    operation = ET.SubElement(body, "{%s}%s" % (service_type, action))
    for key, value in arguments.items():
        ET.SubElement(operation, key).text = str(value)
    parsed_control = urllib.parse.urlsplit(control_url)
    if (parsed_control.scheme != "http" or not parsed_control.hostname
            or not _private_ip(parsed_control.hostname) or parsed_control.username
            or parsed_control.password):
        raise NetworkSetupError("Router control URL must be a private local HTTP endpoint.")
    payload = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
    request = urllib.request.Request(
        control_url, data=payload, method="POST",
        headers={"Content-Type": 'text/xml; charset="utf-8"',
                 "SOAPAction": '"%s#%s"' % (service_type, action),
                 "User-Agent": "Sf2AiS-NetworkManager/1.0"},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())
        with opener.open(request, timeout=5) as response:
            response_body = response.read(128 * 1024)
    except urllib.error.HTTPError as exc:
        response_body = exc.read(128 * 1024)
        try:
            root = ET.fromstring(response_body)
            code = next((node.text for node in root.iter() if node.tag.endswith("errorCode")), None)
            description = next((node.text for node in root.iter() if node.tag.endswith("errorDescription")), None)
            raise NetworkSetupError("Router rejected %s (UPnP %s): %s" % (action, code or exc.code, description or exc.reason)) from exc
        except ET.ParseError:
            raise NetworkSetupError("Router rejected %s (HTTP %s)." % (action, exc.code)) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise NetworkSetupError("UPnP %s request failed: %s" % (action, exc)) from exc
    try:
        return ET.fromstring(response_body)
    except ET.ParseError as exc:
        raise NetworkSetupError("Router returned invalid SOAP XML.") from exc


def external_ip(router: dict[str, Any]) -> str | None:
    control_host = urllib.parse.urlsplit(router.get("control_url", "")).hostname
    if not router.get("router_address") or control_host != router["router_address"]:
        raise NetworkSetupError("Router control endpoint does not match the discovered gateway.")
    root = _soap(router["control_url"], router["service_type"], "GetExternalIPAddress", {})
    value = next((node.text for node in root.iter() if node.tag.endswith("NewExternalIPAddress")), None)
    try:
        return str(ipaddress.ip_address(value or ""))
    except ValueError:
        return None


def apply_mapping(router: dict[str, Any], internal_port: int, external_port: int,
                  protocol: str = "TCP", description: str = "Sf2AiS HTTPS gateway",
                  lease_seconds: int = 3600) -> dict[str, Any]:
    """Create a temporary mapping. Caller must obtain explicit user approval."""
    for port in (internal_port, external_port):
        if isinstance(port, bool) or not 1 <= int(port) <= 65535:
            raise NetworkSetupError("Ports must be integers between 1 and 65535.")
    protocol = protocol.upper()
    if protocol not in {"TCP", "UDP"}:
        raise NetworkSetupError("Only TCP or UDP mappings are supported.")
    local_ip = default_route_ip()
    if not local_ip:
        raise NetworkSetupError("Could not determine a private LAN address for this device.")
    if not router.get("control_url") or not router.get("service_type"):
        raise NetworkSetupError("Router has not been discovered in this session.")
    control_host = urllib.parse.urlsplit(router["control_url"]).hostname
    if not router.get("router_address") or control_host != router["router_address"]:
        raise NetworkSetupError("Router control endpoint does not match the discovered gateway.")
    _soap(router["control_url"], router["service_type"], "AddPortMapping", {
        "NewRemoteHost": "", "NewExternalPort": str(external_port), "NewProtocol": protocol,
        "NewInternalPort": str(internal_port), "NewInternalClient": local_ip,
        "NewEnabled": "1", "NewPortMappingDescription": description[:48],
        "NewLeaseDuration": str(max(600, min(int(lease_seconds), 86400))),
    })
    return {"created": True, "internal_address": local_ip, "internal_port": int(internal_port),
            "external_port": int(external_port), "protocol": protocol,
            "lease_seconds": max(600, min(int(lease_seconds), 86400))}


def remove_mapping(router: dict[str, Any], external_port: int, protocol: str = "TCP") -> dict[str, Any]:
    control_host = urllib.parse.urlsplit(router.get("control_url", "")).hostname
    if not router.get("router_address") or control_host != router["router_address"]:
        raise NetworkSetupError("Router control endpoint does not match the discovered gateway.")
    if isinstance(external_port, bool) or not 1 <= int(external_port) <= 65535:
        raise NetworkSetupError("External port must be between 1 and 65535.")
    protocol = protocol.upper()
    if protocol not in {"TCP", "UDP"}:
        raise NetworkSetupError("Only TCP or UDP mappings are supported.")
    _soap(router["control_url"], router["service_type"], "DeletePortMapping", {
        "NewRemoteHost": "", "NewExternalPort": str(external_port), "NewProtocol": protocol,
    })
    return {"removed": True, "external_port": int(external_port), "protocol": protocol}


def default_gateway() -> str | None:
    """Best-effort default IPv4 gateway discovery without third-party tools."""
    import platform
    import subprocess

    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["ipconfig"], capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            lines = result.stdout.splitlines()
            for index, line in enumerate(lines):
                if "Default Gateway" not in line:
                    continue
                candidates = [line.split(":", 1)[-1].strip()]
                if index + 1 < len(lines):
                    candidates.append(lines[index + 1].strip())
                for candidate_text in candidates:
                    match = re.search(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])", candidate_text)
                    if match and _private_ip(match.group(0)):
                        return match.group(0)
        except (OSError, subprocess.SubprocessError):
            return None
        return None
    try:
        with open("/proc/net/route", encoding="ascii") as routes:
            next(routes, None)
            for line in routes:
                fields = line.split()
                if len(fields) > 3 and fields[1] == "00000000" and int(fields[3], 16) & 1:
                    gateway_int = int(fields[2], 16)
                    gateway = socket.inet_ntoa(gateway_int.to_bytes(4, "little"))
                    if _private_ip(gateway):
                        return gateway
    except (OSError, ValueError):
        return None
    return None


def _udp_exchange(gateway: str, payload: bytes, expected: int, timeout: float = 1.5) -> bytes:
    if not _private_ip(gateway):
        raise NetworkSetupError("Gateway must be a private LAN address.")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(payload, (gateway, 5351))
        response, peer = sock.recvfrom(256)
        if peer[0] != gateway or peer[1] != 5351 or len(response) < expected:
            raise NetworkSetupError("Router returned an invalid NAT mapping response.")
        return response
    except socket.timeout as exc:
        raise NetworkSetupError("No NAT-PMP/PCP response from the default gateway.") from exc
    except OSError as exc:
        raise NetworkSetupError("NAT mapping protocol request failed: %s" % exc) from exc
    finally:
        sock.close()


def nat_pmp_external_address(gateway: str) -> str:
    """Query a NAT-PMP gateway for its public IPv4 address (RFC 6886)."""
    response = _udp_exchange(gateway, b"\x00\x00", 12)
    version, opcode, result, epoch = __import__("struct").unpack("!BBHI", response[:8])
    if version != 0 or opcode != 128 or result != 0:
        raise NetworkSetupError("Gateway rejected NAT-PMP external-address discovery (result %s)." % result)
    address = socket.inet_ntoa(response[8:12])
    return address


def nat_pmp_map(gateway: str, internal_port: int, external_port: int,
                lifetime: int = 86400, protocol: str = "TCP") -> dict[str, Any]:
    """Create a consent-gated NAT-PMP mapping (caller owns approval)."""
    import struct
    protocol = protocol.upper()
    if protocol not in {"TCP", "UDP"}:
        raise NetworkSetupError("NAT-PMP supports only TCP and UDP.")
    if not 1 <= int(internal_port) <= 65535 or not 1 <= int(external_port) <= 65535:
        raise NetworkSetupError("Ports must be between 1 and 65535.")
    lifetime = max(600, min(int(lifetime), 86400))
    opcode = 2 if protocol == "TCP" else 1
    request = struct.pack("!BBHHHI", 0, opcode, 0, int(internal_port), int(external_port), lifetime)
    response = _udp_exchange(gateway, request, 16)
    version, reply_opcode, result, epoch, internal, external, granted = struct.unpack("!BBHIHHI", response[:16])
    if version != 0 or reply_opcode != opcode + 128 or result != 0:
        raise NetworkSetupError("Gateway rejected NAT-PMP mapping (result %s)." % result)
    if internal != int(internal_port) or not 1 <= external <= 65535 or (int(lifetime) != 0 and granted <= 0):
        raise NetworkSetupError("Gateway returned an invalid NAT-PMP mapping assignment.")
    return {"created": True, "method": "nat-pmp", "internal_port": internal,
            "external_port": external, "protocol": protocol, "lease_seconds": granted}


def nat_pmp_remove(gateway: str, external_port: int, protocol: str = "TCP",
                   internal_port: int | None = None) -> dict[str, Any]:
    import struct
    protocol = protocol.upper()
    if protocol not in {"TCP", "UDP"} or not 1 <= int(external_port) <= 65535:
        raise NetworkSetupError("Invalid NAT-PMP mapping removal parameters.")
    opcode = 2 if protocol == "TCP" else 1
    request = struct.pack("!BBHHHI", 0, opcode, 0, int(internal_port or external_port), int(external_port), 0)
    response = _udp_exchange(gateway, request, 16)
    version, reply_opcode, result, epoch, internal, external, granted = struct.unpack("!BBHIHHI", response[:16])
    if version != 0 or reply_opcode != opcode + 128 or result != 0 or granted != 0:
        raise NetworkSetupError("Gateway did not confirm NAT-PMP mapping removal.")
    return {"removed": True, "method": "nat-pmp", "external_port": external,
            "protocol": protocol}


def pcp_map(gateway: str, internal_port: int, external_port: int,
            lifetime: int = 86400, protocol: str = "TCP",
            nonce: bytes | None = None) -> dict[str, Any]:
    """Create/refresh a PCP v2 MAP request (RFC 6887); caller owns approval."""
    import struct
    import secrets as _secrets
    protocol = protocol.upper()
    if protocol not in {"TCP", "UDP"}:
        raise NetworkSetupError("PCP supports only TCP and UDP.")
    if not 1 <= int(internal_port) <= 65535 or not 1 <= int(external_port) <= 65535:
        raise NetworkSetupError("Ports must be between 1 and 65535.")
    local_ip = default_route_ip()
    if not local_ip:
        raise NetworkSetupError("Could not determine the local client address for PCP.")
    lifetime = 0 if int(lifetime) == 0 else max(600, min(int(lifetime), 86400))
    packed_ip = ipaddress.IPv6Address("::ffff:" + local_ip).packed
    nonce = nonce or _secrets.token_bytes(12)
    if len(nonce) != 12:
        raise NetworkSetupError("PCP mapping nonce must be exactly 12 bytes.")
    proto_number = 6 if protocol == "TCP" else 17
    # PCP request header is 24 bytes: version/opcode, reserved, lifetime,
    # then the 16-byte client IP. The MAP payload begins immediately after it.
    request = (
        struct.pack("!BB2xI", 2, 1, lifetime) + packed_ip + nonce
        + struct.pack("!B3xHH", proto_number, int(internal_port), int(external_port))
        + b"\x00" * 16
    )
    response = _udp_exchange(gateway, request, 60)
    version, opcode, result = response[0], response[1], response[4]
    granted = struct.unpack("!I", response[8:12])[0]
    if version != 2 or opcode != 0x81 or result != 0:
        raise NetworkSetupError("Gateway rejected PCP MAP (result %s)." % result)
    if response[24:36] != nonce:
        raise NetworkSetupError("PCP response nonce did not match the request.")
    proto, internal, external = struct.unpack("!B3xHH", response[36:44])
    if proto != proto_number or internal != int(internal_port) or not 1 <= external <= 65535 or (int(lifetime) != 0 and granted <= 0):
        raise NetworkSetupError("Gateway returned an invalid PCP mapping assignment.")
    external_address = ipaddress.ip_address(response[44:60])
    return {"created": True, "method": "pcp", "internal_port": internal,
            "external_port": external, "protocol": "TCP" if proto == 6 else "UDP",
            "lease_seconds": granted, "external_address": str(external_address),
            "pcp_nonce": nonce.hex()}


def diagnose_nat(router: dict[str, Any] | None = None, timeout: float = 3.0) -> dict[str, Any]:
    """Compare local/router/public addresses; never claim a port is reachable."""
    gateway = (router or {}).get("router_address") or default_gateway()
    router_public = None
    router_method = None
    if router and router.get("control_url") and router.get("service_type"):
        try:
            router_public = external_ip(router)
            router_method = "upnp-igd"
        except NetworkSetupError:
            pass
    if not router_public and gateway:
        try:
            router_public = nat_pmp_external_address(gateway)
            router_method = "nat-pmp"
        except NetworkSetupError:
            pass
    observed_public = None
    try:
        request = urllib.request.Request(
            "https://api.ipify.org", headers={"User-Agent": "Sf2AiS-NetworkManager/1.0"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            observed_public = str(ipaddress.ip_address(response.read(64).decode("ascii").strip()))
    except (OSError, ValueError, urllib.error.URLError):
        pass

    cgnat = False
    double_nat = False
    if router_public:
        try:
            address = ipaddress.ip_address(router_public)
            cgnat = address.is_private or address.is_link_local or address in ipaddress.ip_network("100.64.0.0/10")
        except ValueError:
            pass
        if observed_public:
            double_nat = router_public != observed_public and not cgnat
    return {
        "gateway": gateway,
        "router_public_ip": router_public,
        "observed_public_ip": observed_public,
        "router_address_method": router_method,
        "cgnat_or_upstream_private_nat": cgnat,
        "possible_double_nat_or_upstream_nat": double_nat,
        "external_reachability": "unverified",
        "explanation": (
            "The router WAN address is private/shared; inbound IPv4 forwarding is unlikely to work."
            if cgnat else
            "The router WAN address differs from the public address observed by this server; another NAT layer may exist."
            if double_nat else
            "Address comparison alone cannot prove that an inbound port is reachable."
        ),
    }



def pcp_announce(gateway: str) -> dict[str, Any]:
    """Probe PCP v2 support using the non-mutating ANNOUNCE opcode."""
    local_ip = default_route_ip()
    if not local_ip:
        raise NetworkSetupError("Could not determine the local client address for PCP.")
    packed_ip = ipaddress.IPv6Address("::ffff:" + local_ip).packed
    request = __import__("struct").pack("!BB2xI", 2, 0, 0) + packed_ip
    response = _udp_exchange(gateway, request, 24)
    version, opcode, result = response[0], response[1], response[4]
    if version != 2 or opcode != 0x80 or result != 0:
        raise NetworkSetupError("Gateway did not accept PCP ANNOUNCE (result %s)." % result)
    return {"available": True, "gateway": gateway, "protocol": "pcp-v2"}


def discover_mapping_protocols(router: dict[str, Any] | None = None) -> dict[str, Any]:
    """Probe available router mapping protocols without creating any mappings."""
    gateway = (router or {}).get("router_address") or default_gateway()
    result: dict[str, Any] = {
        "gateway": gateway,
        "upnp_igd": bool(router and router.get("available")),
        "nat_pmp": False,
        "pcp": False,
    }
    if not gateway:
        result["reason"] = "Default gateway could not be determined."
        return result
    try:
        nat_pmp_external_address(gateway)
        result["nat_pmp"] = True
    except NetworkSetupError:
        pass
    try:
        pcp_announce(gateway)
        result["pcp"] = True
    except NetworkSetupError:
        pass
    return result
def pcp_remove(gateway: str, internal_port: int, external_port: int,
               protocol: str = "TCP", nonce_hex: str | None = None) -> dict[str, Any]:
    try:
        nonce = bytes.fromhex(nonce_hex) if nonce_hex else None
    except ValueError as exc:
        raise NetworkSetupError("Stored PCP nonce is invalid.") from exc
    if nonce is None or len(nonce) != 12:
        raise NetworkSetupError("The original PCP nonce is unavailable; mapping will expire naturally.")
    result = pcp_map(gateway, internal_port, external_port, lifetime=0,
                     protocol=protocol, nonce=nonce)
    if result["lease_seconds"] != 0:
        raise NetworkSetupError("Gateway did not confirm PCP mapping removal.")
    return {"removed": True, "method": "pcp", "external_port": result["external_port"],
            "protocol": result["protocol"]}




def probe_https_endpoint(host: str, port: int, timeout: float = 2.0) -> bool:
    """Confirm that the configured LAN endpoint completes a TLS handshake."""
    import ssl
    if not _private_ip(host) or isinstance(port, bool) or not 1 <= int(port) <= 65535:
        return False
    raw = None
    try:
        raw = socket.create_connection((host, int(port)), timeout=max(0.5, min(timeout, 4.0)))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with context.wrap_socket(raw, server_hostname=None) as secured:
            secured.settimeout(max(0.5, min(timeout, 4.0)))
            secured.sendall(b"HEAD / HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            response = secured.recv(256)
            return response.startswith(b"HTTP/")
    except (OSError, ssl.SSLError, ValueError):
        return False
    finally:
        if raw is not None:
            try:
                raw.close()
            except OSError:
                pass
