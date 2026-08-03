"""
Minimal DDNS updater.

DuckDNS is the default provider because it's free, needs no account beyond a
token, and is a reasonable zero-setup default for a self-hosted tool that
shouldn't force a particular DNS vendor on anyone. Add more providers to
update() as needed - each just needs a domain/token/ip in, ok/message out.
"""
import urllib.request
import urllib.parse


def update_duckdns(domain: str, token: str, ip: str):
    """domain is just the subdomain part, e.g. 'wayne-debug' for
    wayne-debug.duckdns.org - matches what you'd register at duckdns.org."""
    url = "https://www.duckdns.org/update?" + urllib.parse.urlencode({
        "domains": domain, "token": token, "ip": ip,
    })
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            body = r.read().decode().strip()
    except Exception as e:
        return False, str(e)
    if body.startswith("OK"):
        return True, "%s.duckdns.org -> %s" % (domain, ip)
    return False, "DuckDNS rejected the update (check domain/token): %s" % body


def update(provider: str, domain: str, token: str, ip: str):
    if provider == "duckdns":
        return update_duckdns(domain, token, ip)
    return False, "Unsupported DDNS provider: %s" % provider
