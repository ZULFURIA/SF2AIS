"""Optional DNS-SD/mDNS advertisement for the local Sf2AiS HTTPS endpoint."""
from __future__ import annotations

import socket
from typing import Any

try:
    from zeroconf import IPVersion, ServiceInfo, Zeroconf
except ImportError:  # Keep core service usable when optional dependency is absent.
    IPVersion = ServiceInfo = Zeroconf = None


class MdnsAdvertiser:
    def __init__(self):
        self.zeroconf = None
        self.info = None
        self.state = "unavailable"

    def start(self, address: str | None, port: int) -> dict[str, Any]:
        if Zeroconf is None:
            self.state = "dependency-missing"
            return self.status()
        if not address or not 1 <= int(port) <= 65535:
            self.state = "not-advertised"
            return self.status()
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.8)
        try:
            if probe.connect_ex((address, int(port))) != 0:
                self.state = "endpoint-not-listening"
                return self.status()
        finally:
            probe.close()
        try:
            self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self.info = ServiceInfo(
                "_sf2ais._tcp.local.",
                "Sf2AiS._sf2ais._tcp.local.",
                addresses=[socket.inet_aton(address)],
                port=int(port),
                properties={
                    "product": "Sf2AiS",
                    "path": "/browse",
                    "tls": "required",
                    "version": "1",
                },
                server="sf2ais.local.",
            )
            self.zeroconf.register_service(self.info, allow_name_change=True)
            self.state = "advertised"
        except Exception:
            self.stop()
            self.state = "error"
        return self.status()

    def status(self) -> dict[str, Any]:
        return {"state": self.state, "service_type": "_sf2ais._tcp.local."}

    def stop(self) -> None:
        if self.zeroconf:
            try:
                if self.info:
                    self.zeroconf.unregister_service(self.info)
            except Exception:
                pass
            try:
                self.zeroconf.close()
            except Exception:
                pass
        self.zeroconf = None
        self.info = None
        if self.state == "advertised":
            self.state = "stopped"
