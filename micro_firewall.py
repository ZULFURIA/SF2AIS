"""
Windows-native micro-segmentation for temporary debug tunnels.

Binds a throwaway /32 alias IP to a chosen NIC, scopes Windows Firewall
inbound/outbound rules to that alias + port + an explicit remote allowlist,
and relays raw bytes from the alias IP to 127.0.0.1:<local_port> so it works
regardless of what address the target dev server itself binds to.

Everything here goes through native OS interfaces directly from Python:
- Alias IP: IP Helper API (iphlpapi.dll) via ctypes - AddIPAddress/DeleteIPAddress.
  Non-persistent by design: if this process dies, Windows drops the alias on
  its own, unlike a netsh-configured address.
- Firewall rules: COM (HNetCfg.FwPolicy2 / HNetCfg.FWRule) via pywin32 - the
  same interface the Firewall GUI and netsh advfirewall use under the hood.
- Interface listing: WMI (Win32_NetworkAdapterConfiguration) via pywin32.

No .ps1 files, no subprocess calls to netsh or powershell. Windows-only;
is_supported() reports False elsewhere so callers can fall back gracefully.
"""
import ctypes
import ipaddress
import platform
import socket
import struct
import threading


def is_supported() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Alias IP (IP Helper API)
# ---------------------------------------------------------------------------

def _ip_to_uint(ip: str) -> int:
    return struct.unpack("<L", socket.inet_aton(ip))[0]


def add_alias_ip(alias_ip: str, if_index: int) -> int:
    """Binds alias_ip/32 to the given interface. Returns an NTE context that
    must be passed to remove_alias_ip() later."""
    iphlpapi = ctypes.windll.iphlpapi
    nte_context = ctypes.c_ulong(0)
    nte_instance = ctypes.c_ulong(0)
    result = iphlpapi.AddIPAddress(
        ctypes.c_ulong(_ip_to_uint(alias_ip)),
        ctypes.c_ulong(_ip_to_uint("255.255.255.255")),
        ctypes.c_ulong(if_index),
        ctypes.byref(nte_context),
        ctypes.byref(nte_instance),
    )
    if result != 0:
        raise RuntimeError(
            "AddIPAddress failed (Win32 error %d - commonly means: not running "
            "as Administrator, or the IP is already in use on this segment)." % result
        )
    return nte_context.value


def remove_alias_ip(nte_context: int):
    iphlpapi = ctypes.windll.iphlpapi
    result = iphlpapi.DeleteIPAddress(ctypes.c_ulong(nte_context))
    if result != 0:
        raise RuntimeError("DeleteIPAddress failed (Win32 error %d)." % result)


# ---------------------------------------------------------------------------
# Interface enumeration (WMI) - for the "detected list to choose from" picker
# ---------------------------------------------------------------------------

def list_interfaces() -> list:
    import win32com.client
    wmi = win32com.client.GetObject("winmgmts:")
    interfaces = []
    for cfg in wmi.ExecQuery(
        "SELECT * FROM Win32_NetworkAdapterConfiguration WHERE IPEnabled = True"
    ):
        ips = list(cfg.IPAddress or [])
        ipv4 = next((ip for ip in ips if "." in ip), None)
        if not ipv4:
            continue
        interfaces.append({
            "index": cfg.InterfaceIndex,
            "description": cfg.Description,
            "ip": ipv4,
        })
    return interfaces


# ---------------------------------------------------------------------------
# Firewall rules (COM: HNetCfg.FwPolicy2)
# ---------------------------------------------------------------------------

NET_FW_RULE_DIR_IN = 1
NET_FW_RULE_DIR_OUT = 2
NET_FW_ACTION_ALLOW = 1
NET_FW_IP_PROTOCOL_TCP = 6


def add_firewall_rules(name_prefix: str, alias_ip: str, port: int, trusted_remotes: list):
    """trusted_remotes: list of IPs and/or CIDR subnets. Empty list falls back
    to 'LocalSubnet' (matches the isolation script's original intent of
    still not being wide-open, even without an explicit allowlist)."""
    import win32com.client
    fw_policy = win32com.client.Dispatch("HNetCfg.FwPolicy2")
    remote = ",".join(trusted_remotes) if trusted_remotes else "LocalSubnet"

    in_rule = win32com.client.Dispatch("HNetCfg.FWRule")
    in_rule.Name = "%s_Inbound" % name_prefix
    in_rule.Description = "Sf2AiS temporary debug tunnel - isolated inbound."
    in_rule.Protocol = NET_FW_IP_PROTOCOL_TCP
    in_rule.LocalPorts = str(port)
    in_rule.LocalAddresses = alias_ip
    in_rule.RemoteAddresses = remote
    in_rule.Direction = NET_FW_RULE_DIR_IN
    in_rule.Action = NET_FW_ACTION_ALLOW
    in_rule.Enabled = True
    fw_policy.Rules.Add(in_rule)

    out_rule = win32com.client.Dispatch("HNetCfg.FWRule")
    out_rule.Name = "%s_Outbound" % name_prefix
    out_rule.Description = "Sf2AiS temporary debug tunnel - isolated outbound."
    out_rule.Protocol = NET_FW_IP_PROTOCOL_TCP
    out_rule.LocalPorts = str(port)
    out_rule.LocalAddresses = alias_ip
    out_rule.RemoteAddresses = remote
    out_rule.Direction = NET_FW_RULE_DIR_OUT
    out_rule.Action = NET_FW_ACTION_ALLOW
    out_rule.Enabled = True
    fw_policy.Rules.Add(out_rule)


def remove_firewall_rules(name_prefix: str):
    import win32com.client
    fw_policy = win32com.client.Dispatch("HNetCfg.FwPolicy2")
    for suffix in ("_Inbound", "_Outbound"):
        try:
            fw_policy.Rules.Remove("%s%s" % (name_prefix, suffix))
        except Exception:
            pass  # already gone


# ---------------------------------------------------------------------------
# Raw byte relay: alias_ip:listen_port -> 127.0.0.1:target_port
# ---------------------------------------------------------------------------

def start_relay(alias_ip: str, listen_port: int, target_port: int,
                 trusted_remotes: list, stop_event: threading.Event):
    """Blocking - run in its own daemon thread. Works regardless of whether
    the target dev server binds to 127.0.0.1, 0.0.0.0, or anything else,
    since we connect to it over loopback ourselves. Also enforces the same
    allowlist at the app layer as a second check alongside the firewall rule."""
    import socketserver

    allowed_nets = (
        [ipaddress.ip_network(r, strict=False) for r in trusted_remotes]
        if trusted_remotes else None
    )

    def is_allowed(peer_ip: str) -> bool:
        if not allowed_nets:
            return True
        try:
            addr = ipaddress.ip_address(peer_ip)
        except ValueError:
            return False
        return any(addr in net for net in allowed_nets)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            peer_ip = self.client_address[0]
            if not is_allowed(peer_ip):
                self.request.close()
                return
            try:
                upstream = socket.create_connection(("127.0.0.1", target_port), timeout=5)
            except OSError:
                self.request.close()
                return

            def pump(src, dst):
                try:
                    while True:
                        data = src.recv(4096)
                        if not data:
                            break
                        dst.sendall(data)
                except OSError:
                    pass
                finally:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass

            t1 = threading.Thread(target=pump, args=(self.request, upstream), daemon=True)
            t2 = threading.Thread(target=pump, args=(upstream, self.request), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            upstream.close()

    class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = ThreadingTCPServer((alias_ip, listen_port), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    stop_event.wait()
    server.shutdown()
    server.server_close()
