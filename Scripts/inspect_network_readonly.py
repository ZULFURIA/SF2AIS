import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import network_connectivity as net

router = net.discover_router(timeout=1.5)
protocols = net.discover_mapping_protocols(router)
diagnostics = net.diagnose_nat(router, timeout=2.0)
lan_ip = net.default_route_ip()
result = {
    "router_discovered": bool(router.get("available")),
    "ssdp_responders": len(router.get("upnp_routers", [])),
    "upnp_igd": bool(protocols.get("upnp_igd")),
    "nat_pmp": bool(protocols.get("nat_pmp")),
    "pcp": bool(protocols.get("pcp")),
    "cgnat_or_upstream_private_nat": bool(diagnostics.get("cgnat_or_upstream_private_nat")),
    "possible_double_nat": bool(diagnostics.get("possible_double_nat_or_upstream_nat")),
    "https_reverse_proxy_ready_on_443": bool(lan_ip and net.probe_https_endpoint(lan_ip, 443, timeout=1.5)),
    "external_reachability": "unverified",
}
print(json.dumps(result, indent=2))
