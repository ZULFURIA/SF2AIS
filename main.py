# ==============================================================================
# AI-Gateway-FTP Core Service Terminal
# Copyright (c) 2026 Wayne Thomas Dougall (ZULFURIA). All rights reserved.
# Licensed under the Sf2AiS Noncommercial License v1.0.
# Commercial use requires prior written permission from the copyright holder.
# ==============================================================================
import os
import atexit
import asyncio
import re
import json
import html
import uuid
import secrets
import hashlib
import string
import socket
import platform
import threading
import ipaddress
import subprocess
import shutil
import tempfile
import logging
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from urllib.parse import urlsplit, quote
from pathlib import Path
from datetime import datetime, timedelta, timezone


BASE_DIR = Path(__file__).parent


def load_local_env_file(env_path: Path) -> None:
    """Load simple KEY=value entries without overriding real process environment."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_local_env_file(BASE_DIR / ".env")
from mimetypes import guess_type

from fastapi import FastAPI, Depends, Header, HTTPException, Request, status, UploadFile, File, Form
from fastapi.security import HTTPBasic, HTTPBasicCredentials, APIKeyHeader
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from passlib.hash import bcrypt

try:
    import micro_firewall
    MICRO_FIREWALL_AVAILABLE = micro_firewall.is_supported()
except Exception:
    micro_firewall = None
    MICRO_FIREWALL_AVAILABLE = False

import ddns as ddns_module
import workspace as workspace_module
import project_access as project_access_module
import git_workflow as git_workflow_module
import sandbox_runner
import relay_manager
import network_connectivity
import mdns_service
from terminal_sessions import TerminalSessionManager, TerminalSessionError
from computer_use_manager import CuaDriverBridge, CuaDriverError, OBSERVATION_TOOLS, ACTION_TOOLS

APP_NAME = "Sf2AiS"
APP_TAGLINE = "Secure Files to AI Server"
CLOUDFLARE_RELAY = relay_manager.CloudflareTunnelManager()
ROUTER_DISCOVERY: dict | None = None
MAPPING_PROTOCOLS: dict = {}
NAT_DIAGNOSTICS: dict = {"external_reachability": "unverified"}
MDNS_ADVERTISER = mdns_service.MdnsAdvertiser()
CUA_DRIVER = CuaDriverBridge(BASE_DIR)
atexit.register(CUA_DRIVER.stop)

@asynccontextmanager
async def lifespan(app: FastAPI):
    result = sandbox_runner.cleanup_orphaned_containers()
    if result.get("cleaned"):
        logging.info("Removed %s orphaned Sf2AiS sandbox containers.", result["cleaned"])
    CLOUDFLARE_RELAY.start()
    global ROUTER_DISCOVERY, MAPPING_PROTOCOLS, NAT_DIAGNOSTICS
    try:
        ROUTER_DISCOVERY = await asyncio.to_thread(network_connectivity.discover_router, 1.0)
    except Exception as exc:
        ROUTER_DISCOVERY = {"available": False, "reason": str(exc)[:300]}
        logging.info("UPnP discovery unavailable: %s", exc)
    try:
        MAPPING_PROTOCOLS = await asyncio.to_thread(
            network_connectivity.discover_mapping_protocols, ROUTER_DISCOVERY
        )
        logging.info("Router mapping protocols: %s", MAPPING_PROTOCOLS)
        NAT_DIAGNOSTICS = await asyncio.to_thread(network_connectivity.diagnose_nat, ROUTER_DISCOVERY)
    except Exception as exc:
        MAPPING_PROTOCOLS = {"gateway": network_connectivity.default_gateway(),
                             "upnp_igd": False, "nat_pmp": False, "pcp": False,
                             "reason": str(exc)[:200]}
        NAT_DIAGNOSTICS = {"external_reachability": "unverified", "reason": str(exc)[:200]}
    try:
        config = load_config() or {}
        network = config.get("network", {})
        lan_ip = network_connectivity.default_route_ip()
        lan_port = int(network.get("port", 443))
        mdns_status = await asyncio.to_thread(MDNS_ADVERTISER.start, lan_ip, lan_port)
        logging.info("mDNS service discovery: %s", mdns_status.get("state"))
    except Exception as exc:
        logging.info("mDNS advertisement unavailable: %s", exc)
    renewal_task = asyncio.create_task(router_mapping_renewal_loop())
    try:
        yield
    finally:
        renewal_task.cancel()
        try:
            await renewal_task
        except asyncio.CancelledError:
            pass
        MDNS_ADVERTISER.stop()
        CLOUDFLARE_RELAY.stop()


async def router_mapping_renewal_loop():
    """Renew only mappings previously approved by the administrator."""
    while True:
        await asyncio.sleep(5 * 60)
        try:
            config = load_config() or {}
            network = config.get("network", {})
            mapping = network.get("upnp_mapping")
            if not mapping:
                continue
            try:
                expiry = datetime.fromisoformat(mapping["expires_at"])
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
            except (KeyError, TypeError, ValueError):
                remaining = 0
            if remaining <= 0:
                network.pop("upnp_mapping", None)
                save_config(config)
                audit_event("router_mapping_expired", detail={
                    "method": mapping.get("method", "upnp-igd"),
                    "external_port": mapping.get("external_port"),
                })
                continue
            if remaining > 12 * 60 * 60:
                continue
            method = mapping.get("method", "upnp-igd")
            gateway = mapping.get("router_address") or network_connectivity.default_gateway()
            internal_port = int(mapping["internal_port"])
            external_port = int(mapping["external_port"])
            protocol = mapping.get("protocol", "TCP")
            local_ip = network_connectivity.default_route_ip()
            if not local_ip or not gateway:
                continue
            if not network_connectivity.probe_https_endpoint(local_ip, internal_port, timeout=2.0):
                continue
            if method == "upnp-igd":
                router = await asyncio.to_thread(network_connectivity.discover_router, 1.0)
                if not router.get("available") or router.get("router_address") != gateway:
                    continue
                result = await asyncio.to_thread(
                    network_connectivity.apply_mapping, router, internal_port,
                    external_port, protocol, "Sf2AiS HTTPS gateway", 86400
                )
            elif method == "nat-pmp":
                result = await asyncio.to_thread(
                    network_connectivity.nat_pmp_map, gateway, internal_port,
                    external_port, 86400, protocol
                )
            elif method == "pcp":
                result = await asyncio.to_thread(
                    network_connectivity.pcp_map, gateway, internal_port,
                    external_port, 86400, protocol,
                    bytes.fromhex(mapping["pcp_nonce"])
                )
            else:
                continue
            mapping.update(result)
            mapping["created_at"] = now_iso()
            mapping["expires_at"] = datetime.fromtimestamp(
                time.time() + result["lease_seconds"], timezone.utc
            ).isoformat()
            save_config(config)
            audit_event("router_mapping_renewed", detail={
                "method": method, "router_address": gateway,
                "external_port": external_port, "protocol": protocol,
            })
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Sf2AiS router mapping renewal failed")


app = FastAPI(
    title=APP_NAME,
    description="Secure HTTP workspace bridge for browser-based AI clients.",
    lifespan=lifespan,
)
security = HTTPBasic(auto_error=False)
api_token_header = APIKeyHeader(name="X-Sf2AiS-Token", auto_error=False)

# Per-process brute-force throttling. Deployments with multiple workers should
# place a shared rate limiter at the reverse proxy as well.
_AUTH_FAILURES = defaultdict(deque)
_AUTH_FAILURES_LOCK = threading.Lock()
_AUTH_WINDOW_SECONDS = 300
_AUTH_MAX_FAILURES = 20


@app.middleware("http")
async def request_security_middleware(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        if origin:
            try:
                if urlsplit(origin).netloc.lower() != host.lower():
                    return JSONResponse({"detail": "Cross-origin state changes are not allowed."}, status_code=403)
            except ValueError:
                return JSONResponse({"detail": "Invalid Origin header."}, status_code=403)

    remote = request.client.host if request.client else "unknown"
    try:
        remote_is_loopback = ipaddress.ip_address(remote).is_loopback
    except ValueError:
        remote_is_loopback = remote in {"testclient", "testserver"}
    trusted_proxies = {item.strip() for item in os.getenv("SF2AIS_TRUSTED_PROXY_IPS", "").split(",") if item.strip()}
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    secure_transport = request.url.scheme == "https" or (("*" in trusted_proxies or remote in trusted_proxies) and forwarded_proto == "https")
    authenticated_request = bool(request.headers.get("authorization") or request.headers.get("x-sf2ais-token"))
    sensitive_probe = request.url.path == "/api/ip-update"
    state_change = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    sensitive_download = request.url.path == "/probe/download"
    if (authenticated_request or sensitive_probe or state_change or sensitive_download) and not remote_is_loopback and not secure_transport:
        if os.getenv("SF2AIS_ALLOW_INSECURE_REMOTE", "0") != "1":
            return JSONResponse({"detail": "HTTPS is required for remote authenticated access. Configure a TLS reverse proxy."}, status_code=426)
    now = time_mod.time() if "time_mod" in globals() else __import__("time").time()
    with _AUTH_FAILURES_LOCK:
        attempts = _AUTH_FAILURES[remote]
        while attempts and now - attempts[0] > _AUTH_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) >= _AUTH_MAX_FAILURES:
            return JSONResponse({"detail": "Too many failed authentication attempts. Try again later."}, status_code=429)

    response = await call_next(request)
    if response.status_code == 401:
        with _AUTH_FAILURES_LOCK:
            attempts = _AUTH_FAILURES[remote]
            while attempts and now - attempts[0] > _AUTH_WINDOW_SECONDS:
                attempts.popleft()
            attempts.append(now)

    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith(("/dashboard", "/browse", "/workbench", "/api/", "/files", "/cli/", "/tunnel", "/network/verify")):
        response.headers["Cache-Control"] = "no-store"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "./data/config.json"))
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

SHARE_ONLINE_WINDOW_SECONDS = 5 * 60
PROBE_ONLINE_WINDOW_SECONDS = 15 * 60

# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def external_reachability_verified(record: dict | None, max_age_seconds: int = 86400) -> bool:
    if not record or record.get("status") != "verified":
        return False
    try:
        verified_at = datetime.fromisoformat(record.get("verified_at", ""))
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - verified_at).total_seconds()
        return 0 <= age <= max_age_seconds
    except (TypeError, ValueError):
        return False


def router_mapping_expired(mapping: dict | None) -> bool:
    if not mapping:
        return True
    try:
        expiry = datetime.fromisoformat(mapping.get("expires_at", ""))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry <= datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return True

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            return None
    return None

CONFIG_LOCK = threading.RLock()


def save_config(config: dict):
    """Persist config atomically so concurrent auth updates cannot leave partial JSON."""
    temp_name = None
    with CONFIG_LOCK:
        try:
            fd, temp_name = tempfile.mkstemp(prefix=".sf2ais-config-", suffix=".tmp",
                                             dir=str(CONFIG_PATH.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(config, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, CONFIG_PATH)
            temp_name = None
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass

def is_configured() -> bool:
    return load_config() is not None


AUDIT_PATH = CONFIG_PATH.parent / "audit.jsonl"
AUDIT_LOCK = __import__("threading").Lock()


def audit_event(action: str, share: dict | None = None, request: Request | None = None,
                path: str = "", detail: dict | None = None) -> None:
    """Append a minimal audit record; never log credentials or file contents."""
    record = {
        "at": now_iso(),
        "action": action,
        "share_id": (share or {}).get("id"),
        "share_username": (share or {}).get("username"),
        "client_id": (share or {}).get("_client_id"),
        "client_name": (share or {}).get("_client_name"),
        "remote_ip": getattr(getattr(request, "client", None), "host", None),
        "path": path,
        "detail": detail or {},
    }
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOCK:
            if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size > 10 * 1024 * 1024:
                rotated = AUDIT_PATH.with_name(AUDIT_PATH.name + ".1")
                try:
                    rotated.unlink(missing_ok=True)
                except OSError:
                    pass
                os.replace(AUDIT_PATH, rotated)
            with AUDIT_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        logging.exception("Could not write Sf2AiS audit record")

def generate_share_password(length: int = 16) -> str:
    """Auto-generated passwords always satisfy the complexity policy."""
    alphabet_lower = string.ascii_lowercase
    alphabet_upper = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%^&*-_+="
    all_chars = alphabet_lower + alphabet_upper + digits + special
    while True:
        pw = "".join(secrets.choice(all_chars) for _ in range(length))
        if (re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw)
                and re.search(r"[0-9]", pw) and re.search(r"[^a-zA-Z0-9]", pw)):
            return pw

def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return text or "share"

# ---------------------------------------------------------------------------
# Password complexity policy
# ---------------------------------------------------------------------------

MIN_LENGTH = 12

def validate_password(password: str, username: str = "") -> list:
    problems = []
    if len(password) < MIN_LENGTH:
        problems.append("Must be at least %d characters long." % MIN_LENGTH)
    if not re.search(r"[a-z]", password):
        problems.append("Must include at least one lowercase letter.")
    if not re.search(r"[A-Z]", password):
        problems.append("Must include at least one uppercase letter.")
    if not re.search(r"[0-9]", password):
        problems.append("Must include at least one number.")
    if not re.search(r"[^a-zA-Z0-9]", password):
        problems.append("Must include at least one special character (e.g. ! @ # $ %).")
    if username and username.lower() in password.lower():
        problems.append("Must not contain the username.")
    common_weak = {"password", "changeme", "letmein", "qwerty", "admin123", "welcome1"}
    stripped = re.sub(r"[^a-z]", "", password.lower())
    if any(weak in stripped for weak in common_weak):
        problems.append("Must not be based on a common/weak password.")
    return problems

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def admin_auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required.",
                            headers={"WWW-Authenticate": "Basic"})
    config = load_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Not configured. Visit / to complete setup.")
    admin = config["admin"]
    ok_user = secrets.compare_digest(credentials.username, admin["username"])
    stored_password = admin.get("password_hash", "")
    try:
        ok_pass = bcrypt.verify(credentials.password, stored_password)
    except (TypeError, ValueError):
        # Older/manual configurations may contain the original password in this
        # field instead of a bcrypt hash. Accept it only on an exact constant-time
        # match, then immediately upgrade the stored value to bcrypt.
        ok_pass = isinstance(stored_password, str) and secrets.compare_digest(
            credentials.password, stored_password
        )
        if ok_pass:
            admin["password_hash"] = bcrypt.hash(credentials.password)
            save_config(config)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401, detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def share_auth(
    credentials: HTTPBasicCredentials | None = Depends(security),
    api_token: str | None = Depends(api_token_header),
):
    config = load_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Not configured.")
    match = None
    client_match = None
    if api_token:
        supplied_hash = hashlib.sha256(api_token.encode("utf-8")).hexdigest()
        for candidate in config.get("shares", []):
            for client in candidate.get("clients", []):
                if secrets.compare_digest(supplied_hash, client.get("token_hash", "")):
                    match, client_match = candidate, client
                    break
            if match:
                break
        if not match or not client_match:
            raise HTTPException(status_code=401, detail="Invalid or revoked AI client token.")
    else:
        if credentials is None:
            raise HTTPException(status_code=401, detail="Share authentication required.",
                                headers={"WWW-Authenticate": "Basic"})
        for candidate in config.get("shares", []):
            if not candidate.get("legacy_auth_disabled", False) and secrets.compare_digest(credentials.username, candidate["username"]):
                match = candidate
                break
        valid = False
        if match:
            try:
                valid = bcrypt.verify(credentials.password, match["password_hash"])
            except (TypeError, ValueError):
                valid = False
        if not valid:
            raise HTTPException(status_code=401, detail="Unauthorized",
                                headers={"WWW-Authenticate": "Basic"})

    match["last_seen"] = now_iso()
    if client_match:
        client_match["last_seen"] = now_iso()
    save_config(config)
    result = dict(match)
    if client_match:
        result["_client_id"] = client_match["id"]
        result["_client_name"] = client_match.get("name", "AI client")
        result["_client_permissions"] = dict(client_match.get("permissions", {}))
    return result

# ---------------------------------------------------------------------------
# Network / link helpers
# ---------------------------------------------------------------------------

def build_share_link(config) -> str:
    network = config.get("network", {})
    method = network.get("method")
    mapping = network.get("upnp_mapping") or {}
    port = mapping.get("external_port", network.get("port", 443))

    if method in ("domain", "ddns"):
        host = network.get("value") or "your-domain-not-set"
        return ("https://%s" % host) if str(port) == "443" else ("https://%s:%s" % (host, port))
    if method == "static":
        ip = network.get("value") or "0.0.0.0"
        return ("https://%s" % ip) if str(port) == "443" else ("https://%s:%s" % (ip, port))
    if method == "probe":
        ip = network.get("last_public_ip")
        if ip:
            return ("https://%s" % ip) if str(port) == "443" else ("https://%s:%s" % (ip, port))
        return "(waiting for probe to report your public IP)"
    return "(network not configured)"

def network_online_status(config):
    network = config.get("network", {})
    method = network.get("method")
    if method == "probe":
        last = network.get("last_ip_update")
        if not last:
            return False, "Waiting for the IP probe to check in for the first time."
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
        if age <= PROBE_ONLINE_WINDOW_SECONDS:
            return True, "IP probe last checked in %d min ago." % int(age // 60)
        return False, "IP probe hasn't checked in for %d min - is it still running?" % int(age // 60)
    if method in ("domain", "ddns", "static"):
        return True, "Assumed reachable based on your network configuration (not independently verified)."
    return False, "Network not configured yet."

# ---------------------------------------------------------------------------
# Shared page chrome
# ---------------------------------------------------------------------------

def brand_header():
    return """
        <div class="brand">
            <img src="/static/logo.svg" alt="logo">
            <div>
                <h1>%s</h1>
                <p class="tagline">%s</p>
            </div>
        </div>
    """ % (APP_NAME, APP_TAGLINE)

def step_indicator(current: int, total: int = 4):
    dots = ""
    for i in range(1, total + 1):
        cls = "active" if i == current else ("done" if i < current else "")
        dots += '<div class="dot %s"></div>' % cls
    return '<div class="steps">%s</div>' % dots

def page(title: str, body: str, wide: bool = False) -> str:
    wrap_cls = "wrap wide" if wide else "wrap"
    return """
    <html>
    <head>
        <title>%s - %s</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body>
        <div class="%s">
            <div class="glass">
                %s
            </div>
            <div class="footer">%s &bull; self-hosted file bridge for AI assistants</div>
        </div>
    </body>
    </html>
    """ % (title, APP_NAME, wrap_cls, body, APP_NAME)

# ---------------------------------------------------------------------------
# Setup: Step 0 - Welcome
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def root():
    if is_configured():
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/setup")

@app.get("/setup", response_class=HTMLResponse)
def setup_welcome():
    if is_configured():
        return RedirectResponse(url="/dashboard")
    body = brand_header() + """
        <p class="sub">Turn any folder on this machine into something your AI assistant can securely
        browse and read - no API keys, no MCP setup. Let's get you running in under two minutes.</p>
        <a class="btn" href="/setup/account">Get Started &rarr;</a>
    """
    return page("Welcome", body)

# ---------------------------------------------------------------------------
# Setup: Step 1 - Admin account
# ---------------------------------------------------------------------------

@app.get("/setup/account", response_class=HTMLResponse)
def setup_account_form(error: str = ""):
    if is_configured():
        return RedirectResponse(url="/dashboard")
    error_html = ('<div class="error">%s</div>' % html.escape(error)) if error else ""
    body = brand_header() + step_indicator(1) + """
        <h2>Create your dashboard login</h2>
        <p class="sub">This is YOUR login for the control panel - not what you give to the AI.</p>
        """ + error_html + """
        <form method="post" action="/setup/account">
            <label>Username</label>
            <input type="text" name="username" required placeholder="e.g. wayne">
            <label>Password</label>
            <input type="password" name="password" id="password" required oninput="checkStrength()">
            <label>Confirm password</label>
            <input type="password" name="confirm" required>
            <ul class="reqs" id="reqs">
                <li id="r-len">At least 12 characters</li>
                <li id="r-lower">One lowercase letter</li>
                <li id="r-upper">One uppercase letter</li>
                <li id="r-digit">One number</li>
                <li id="r-special">One special character</li>
            </ul>
            <button type="submit">Continue &rarr;</button>
        </form>
        <script>
        function checkStrength() {
            var pw = document.getElementById('password').value;
            var rules = {
                'r-len': pw.length >= 12,
                'r-lower': /[a-z]/.test(pw),
                'r-upper': /[A-Z]/.test(pw),
                'r-digit': /[0-9]/.test(pw),
                'r-special': /[^a-zA-Z0-9]/.test(pw)
            };
            for (var id in rules) {
                document.getElementById(id).className = rules[id] ? 'ok' : '';
            }
        }
        </script>
    """
    return page("Create Account", body)

@app.post("/setup/account", response_class=HTMLResponse)
async def setup_account_submit(request: Request):
    if is_configured():
        return RedirectResponse(url="/dashboard", status_code=303)
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    confirm = form.get("confirm") or ""

    errors = []
    if not username or len(username) < 3:
        errors.append("Username must be at least 3 characters.")
    if password != confirm:
        errors.append("Passwords do not match.")
    errors.extend(validate_password(password, username))

    if errors:
        return setup_account_form(error="<br>".join(errors))

    password_hash = bcrypt.hash(password)
    body = brand_header() + step_indicator(2) + ("""
        <h2>How will your AI reach this server?</h2>
        <p class="sub">Pick the option that matches your setup. Not sure? Choose the last option - we'll handle it for you.</p>
        <form method="post" action="/setup/network">
            <input type="hidden" name="username" value="%s">
            <input type="hidden" name="password_hash" value="%s">

            <label class="radio-card">
                <input type="radio" name="method" value="domain" checked onclick="showField('domain')">
                <div>
                    <div class="rc-title">I have a custom domain</div>
                    <div class="rc-sub">e.g. files.yourdomain.com - already pointed at this machine</div>
                </div>
            </label>
            <label class="radio-card">
                <input type="radio" name="method" value="ddns" onclick="showField('domain')">
                <div>
                    <div class="rc-title">I use Dynamic DNS</div>
                    <div class="rc-sub">e.g. a DuckDNS / No-IP hostname</div>
                </div>
            </label>
            <label class="radio-card">
                <input type="radio" name="method" value="static" onclick="showField('domain')">
                <div>
                    <div class="rc-title">I have a static IP address</div>
                    <div class="rc-sub">Your public IP never changes</div>
                </div>
            </label>
            <label class="radio-card">
                <input type="radio" name="method" value="probe" onclick="showField('probe')">
                <div>
                    <div class="rc-title">Just use my current IP (recommended for most people)</div>
                    <div class="rc-sub">We'll install a tiny helper that keeps your link working even if your IP changes</div>
                </div>
            </label>

            <div id="field-domain">
                <label>Domain / hostname / static IP</label>
                <input type="text" name="value" placeholder="files.yourdomain.com">
            </div>
            <div id="field-probe" style="display:none;">
                <p class="sub">No input needed - after setup we'll give you a small script to run on
                whichever computer stays online (Windows, Mac, or Linux). It quietly checks your public
                IP every few minutes and updates your link automatically.</p>
            </div>

            <label>Port</label>
            <input type="text" name="port" value="443">

            <button type="submit">Continue &rarr;</button>
        </form>
        <script>
        function showField(which) {
            document.getElementById('field-domain').style.display = which === 'domain' ? 'block' : 'none';
            document.getElementById('field-probe').style.display = which === 'probe' ? 'block' : 'none';
        }
        </script>
    """ % (username, password_hash))
    return page("Network Setup", body)

# ---------------------------------------------------------------------------
# Setup: Step 2 - Network
# ---------------------------------------------------------------------------

@app.post("/setup/network", response_class=HTMLResponse)
async def setup_network_submit(request: Request):
    if is_configured():
        return RedirectResponse(url="/dashboard", status_code=303)
    form = await request.form()
    username = form.get("username")
    password_hash = form.get("password_hash")
    method = form.get("method")
    value = (form.get("value") or "").strip()
    port = (form.get("port") or "8000").strip()

    probe_token = secrets.token_urlsafe(24) if method == "probe" else ""

    body = brand_header() + step_indicator(3) + ("""
        <h2>Which folders should your AI be able to see?</h2>
        <p class="sub">Add one or more folders from this machine. Each folder becomes its own secure share.</p>
        <form method="post" action="/setup/folders">
            <input type="hidden" name="username" value="%s">
            <input type="hidden" name="password_hash" value="%s">
            <input type="hidden" name="method" value="%s">
            <input type="hidden" name="value" value="%s">
            <input type="hidden" name="port" value="%s">
            <input type="hidden" name="probe_token" value="%s">

            <div id="folders">
                <div class="folder-row">
                    <input type="text" name="folder" placeholder="e.g. ./shared_files or /home/you/Documents/AI-Share" required>
                </div>
            </div>
            <button type="button" class="secondary small" onclick="addFolder()">+ Add another folder</button>

            <label style="display:flex; align-items:flex-start; gap:8px; margin-top:16px;">
                <input type="checkbox" name="cli_enabled" style="width:auto; margin-top:3px;">
                <span>Allow command execution (CLI) - lets your AI run shell/PowerShell commands for
                debugging and testing, not just read files. Applies to all folders above; you can turn it
                on/off per folder later from the dashboard. Only enable if you trust this AI environment.</span>
            </label>

            <label style="display:flex; align-items:flex-start; gap:8px; margin-top:10px;">
                <input type="checkbox" name="tunnel_enabled" style="width:auto; margin-top:3px;">
                <span>Allow temporary debug tunnels - lets your AI briefly expose a local dev server
                (e.g. a Vite/webpack server) to the public internet via your router's UPnP, so it can view
                what it built. Requires UPnP support on your router; sessions auto-expire.</span>
            </label>

            <button type="submit">Continue &rarr;</button>
        </form>
        <script>
        function addFolder() {
            var row = document.createElement('div');
            row.className = 'folder-row';
            row.innerHTML = '<input type="text" name="folder" placeholder="e.g. /home/you/Documents/More-Files">';
            document.getElementById('folders').appendChild(row);
        }
        </script>
    """ % (username, password_hash, method, value, port, probe_token))
    return page("Choose Folders", body)

# ---------------------------------------------------------------------------
# Setup: Step 3 - Folders (final save)
# ---------------------------------------------------------------------------

@app.post("/setup/folders", response_class=HTMLResponse)
async def setup_folders_submit(request: Request):
    if is_configured():
        return RedirectResponse(url="/dashboard", status_code=303)
    form = await request.form()
    username = form.get("username")
    password_hash = form.get("password_hash")
    method = form.get("method")
    value = form.get("value")
    port = int(form.get("port") or 443)
    probe_token = form.get("probe_token") or ""

    folders = [f.strip() for f in form.getlist("folder") if f.strip()]
    if not folders:
        folders = ["./shared_files"]
    cli_enabled = (form.get("cli_enabled") == "on")
    tunnel_enabled = (form.get("tunnel_enabled") == "on")

    shares = []
    generated_creds = []
    used_names = set()
    for folder in folders:
        Path(folder).mkdir(parents=True, exist_ok=True)
        base_name = slugify(Path(folder).name)
        share_username = base_name
        n = 2
        while share_username in used_names:
            share_username = "%s-%d" % (base_name, n)
            n += 1
        used_names.add(share_username)

        share_password = generate_share_password()
        share = {
            "id": str(uuid.uuid4()),
            "username": share_username,
            "password_hash": bcrypt.hash(share_password),
            "folder": str(Path(folder).resolve()),
            "last_seen": None,
            "cli_enabled": cli_enabled,
            "tunnel_enabled": tunnel_enabled,
            "workspace_write_enabled": False,
            "ide_enabled": False,
            "computer_use_enabled": False,
        }
        shares.append(share)
        generated_creds.append({"username": share_username, "password": share_password, "folder": folder})

    config = {
        "admin": {"username": username, "password_hash": password_hash},
        "network": {
            "method": method,
            "value": value,
            "port": port,
            "probe_token": probe_token,
            "last_public_ip": None,
            "last_ip_update": None,
        },
        "shares": shares,
    }
    save_config(config)

    creds_html = ""
    for c in generated_creds:
        creds_html += """
        <div class="card-sm" style="margin-top:12px;">
            <div class="label">Folder: %s</div>
            <div class="value">Username: %s</div>
            <div class="copy-row"><code>%s</code></div>
        </div>
        """ % (html.escape(c['folder']), html.escape(c['username']), html.escape(c['password']))

    probe_block = ""
    if method == "probe":
        probe_block = """
        <h2 style="margin-top:28px;">One more step - install the IP updater</h2>
        <p class="sub">Run this on any computer that stays on. It checks your public IP every 5 minutes
        and tells %s when it changes, so your link never breaks.</p>
        <p class="sub">Your probe token (already baked into the download):</p>
        <code>%s</code>
        <div class="grid-2" style="margin-top:14px;">
            <a class="btn secondary" href="/probe/download?token=%s&platform=windows">Windows script</a>
            <a class="btn secondary" href="/probe/download?token=%s&platform=mac">macOS script</a>
        </div>
        <div class="grid-2" style="margin-top:10px;">
            <a class="btn secondary" href="/probe/download?token=%s&platform=linux">Linux script</a>
            <a class="btn secondary" href="/probe/setup-guide">Setup instructions</a>
        </div>
        """ % (APP_NAME, probe_token, probe_token, probe_token, probe_token)

    body = brand_header() + step_indicator(4) + ("""
        <h2>You're set up</h2>
        <p class="sub">Save these credentials now - passwords are shown only once. Give a username/password
        pair to your AI assistant along with your link.</p>
        %s
        %s
        <a class="btn" style="margin-top:26px;" href="/workspace">Open SF2AiS Workspace &rarr;</a>
    """ % (creds_html, probe_block))
    return page("Setup Complete", body)

# ---------------------------------------------------------------------------
# Unified desktop/web workspace renderer
# ---------------------------------------------------------------------------

WORKSPACE_RENDERER_DIR = BASE_DIR / "probe-app" / "renderer"


@app.get("/workspace", response_class=HTMLResponse)
def unified_web_workspace(admin: str = Depends(admin_auth)):
    index_path = WORKSPACE_RENDERER_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=503, detail="The shared workspace renderer is unavailable.")
    document = index_path.read_text(encoding="utf-8")
    required_assets = (
        '<link rel="stylesheet" href="styles.css">',
        '<script src="app.js"></script>',
    )
    if any(asset not in document for asset in required_assets):
        raise HTTPException(status_code=500, detail="The shared workspace asset references are invalid.")

    document = document.replace(
        required_assets[0],
        '<link rel="stylesheet" href="/workspace/styles.css">',
    )
    document = document.replace(
        required_assets[1],
        '<script src="/workspace/web-adapter.js"></script>\n  <script src="/workspace/app.js"></script>',
    )

    local_settings_intro = (
        '<div class="page-intro glass"><span class="eyebrow cyan">LOCAL AGENT CONFIGURATION</span>'
        '<h2>System settings</h2><p>Configure the local desktop probe, gateway connection, dynamic DNS '
        'and Windows startup behaviour.</p></div>'
    )
    server_settings_intro = (
        '<div class="page-intro glass"><span class="eyebrow cyan">SERVER CONFIGURATION</span>'
        '<h2>System settings</h2><p>Local-only probe and Windows startup controls are not available in the browser. '
        'Server network, DDNS, router discovery, relay status and external reachability controls are available '
        'in the shared Network page.</p></div>'
        '<article class="glass detail-panel web-settings-panel">'
        '<h3>Server network and security controls</h3>'
        '<p>Manage HTTPS gateway settings, DuckDNS, router discovery and explicit forwarding approvals in the '
        'same workspace interface. No router mapping or public exposure is applied by opening this page.</p>'
        '<div class="page-actions"><button class="btn primary" type="button" data-open-page="network">'
        'Open network settings</button></div></article>'
    )
    if local_settings_intro not in document:
        raise HTTPException(status_code=500, detail="The shared settings page could not be adapted for web mode.")
    document = document.replace(local_settings_intro, server_settings_intro, 1)

    web_styles = """
<style>
html[data-runtime="web"] .window-chrome{display:none!important}
html[data-runtime="web"] body{overflow:auto!important}
html[data-runtime="web"] .app-shell{height:auto!important;min-height:100vh!important}
html[data-runtime="web"] .main-area{overflow:visible!important}
html[data-runtime="web"] #server-connection-panel,
html[data-runtime="web"] #page-settings .detail-panel:has(.settings-grid),
html[data-runtime="web"] #page-settings .detail-panel:has(#btn-start-probe),
html[data-runtime="web"] #btn-top-check,
html[data-runtime="web"] #btn-check-now,
html[data-runtime="web"] #btn-dash-check-now,
html[data-runtime="web"] #btn-clear-logs,
html[data-runtime="web"] #btn-refresh-logs,
html[data-runtime="web"] #btn-start-probe,
html[data-runtime="web"] #btn-stop-probe,
html[data-runtime="web"] #btn-save,
html[data-runtime="web"] #btn-scheduler,
html[data-runtime="web"] #btn-open-duckdns,
html[data-runtime="web"] .status-art-panel{display:none!important}
html[data-runtime="web"] .web-settings-panel{display:block!important}
</style>
"""
    document = document.replace("</head>", web_styles + "</head>", 1)
    return HTMLResponse(document, headers={"Cache-Control": "no-store"})


@app.get("/workspace/styles.css")
def unified_web_styles(admin: str = Depends(admin_auth)):
    path = WORKSPACE_RENDERER_DIR / "styles.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Workspace stylesheet not found.")
    return FileResponse(path, media_type="text/css", headers={"Cache-Control": "no-store"})


@app.get("/workspace/app.js")
def unified_web_app_script(admin: str = Depends(admin_auth)):
    path = WORKSPACE_RENDERER_DIR / "app.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Workspace application script not found.")
    return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/workspace/web-adapter.js")
def unified_web_adapter_script(admin: str = Depends(admin_auth)):
    path = WORKSPACE_RENDERER_DIR / "web-adapter.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Workspace web adapter not found.")
    return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/workspace/ide-guide", response_class=HTMLResponse)
def unified_web_ide_guide(admin: str = Depends(admin_auth)):
    guide_path = BASE_DIR / "vscode-extension" / "README.md"
    guide = guide_path.read_text(encoding="utf-8") if guide_path.is_file() else "VS Code integration guide is not installed."
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><title>SF2AiS IDE Guide</title>"
        "<style>body{font:14px Segoe UI,sans-serif;background:#0b1025;color:#eef;padding:28px;}"
        "pre{white-space:pre-wrap;line-height:1.6;}</style></head><body><h1>SF2AiS VS Code Guide</h1><pre>"
        + html.escape(guide) + "</pre></body></html>",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/dashboard")
def dashboard(request: Request, admin: str = Depends(admin_auth)):
    """Keep the legacy URL as an authenticated compatibility redirect."""
    target = "/workspace#monitor" if request.query_params.get("view") == "realtime" else "/workspace"
    return RedirectResponse(url=target, status_code=307)


@app.post("/dashboard/shares/add", response_class=HTMLResponse)
async def add_share(request: Request, admin: str = Depends(admin_auth)):
    config = load_config()
    form = await request.form()
    folder = (form.get("folder") or "").strip()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""

    errors = []
    if not folder:
        errors.append("Folder path is required.")
    if not username or len(username) < 3:
        errors.append("Username must be at least 3 characters.")
    if any(s["username"] == username for s in config.get("shares", [])):
        errors.append("That username is already in use by another share.")
    errors.extend(validate_password(password, username))

    if errors:
        body = brand_header() + ("""
            <h2>Couldn't add share</h2>
            <div class="error">%s</div>
            <a class="btn secondary" href="/dashboard">Back to dashboard</a>
        """ % "<br>".join(errors))
        return page("Error", body)

    Path(folder).mkdir(parents=True, exist_ok=True)
    config.setdefault("shares", []).append({
        "id": str(uuid.uuid4()),
        "username": username,
        "password_hash": bcrypt.hash(password),
        "folder": str(Path(folder).resolve()),
        "last_seen": None,
        "cli_enabled": (form.get("cli_enabled") == "on"),
        "tunnel_enabled": (form.get("tunnel_enabled") == "on"),
        "workspace_write_enabled": (form.get("workspace_write_enabled") == "on"),
        "ide_enabled": (form.get("ide_enabled") == "on"),
        "computer_use_enabled": (form.get("computer_use_enabled") == "on"),
    })
    save_config(config)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/dashboard/shares/{share_id}/toggle-cli")
def toggle_cli(share_id: str, admin: str = Depends(admin_auth)):
    config = load_config()
    disabled = False
    for s in config.get("shares", []):
        if s["id"] == share_id:
            s["cli_enabled"] = not s.get("cli_enabled", False)
            disabled = not s["cli_enabled"]
    save_config(config)
    if disabled:
        TERMINAL_SESSIONS.close_share(share_id)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/dashboard/network")
async def set_network_endpoint(request: Request, admin: str = Depends(admin_auth)):
    form = await request.form()
    try:
        port = int(form.get("port") or 443)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="HTTPS port must be an integer.")
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail="HTTPS port must be between 1 and 65535.")
    config = load_config()
    config.setdefault("network", {})["port"] = port
    save_config(config)
    MDNS_ADVERTISER.stop()
    lan_ip = network_connectivity.default_route_ip()
    await asyncio.to_thread(MDNS_ADVERTISER.start, lan_ip, port)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/dashboard/ddns")
async def set_ddns(request: Request, admin: str = Depends(admin_auth)):
    form = await request.form()
    domain = (form.get("domain") or "").strip()
    token = (form.get("token") or "").strip()
    config = load_config()
    network = config.setdefault("network", {})
    existing = network.get("ddns") or {}
    network["ddns"] = {
        "provider": "duckdns",
        "domain": domain or existing.get("domain", ""),
        "token": token or existing.get("token", ""),
        "last_result": existing.get("last_result"),
    }
    save_config(config)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/dashboard/shares/{share_id}/clients/create", response_class=HTMLResponse)
async def create_ai_client(share_id: str, request: Request, admin: str = Depends(admin_auth)):
    config = load_config()
    share = next((item for item in config.get("shares", []) if item.get("id") == share_id), None)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found.")
    form = await request.form()
    name = (form.get("name") or "").strip()[:80]
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="AI client name must be at least two characters.")
    token = secrets.token_urlsafe(40)
    permissions = {
        "read": ("on" in form.getlist("read")) if form.getlist("read") else True,
        "write": form.get("write") == "on",
        "cli": form.get("cli") == "on",
        "tunnel": form.get("tunnel") == "on",
        "git_stage": form.get("git_stage") == "on",
        "git_commit": form.get("git_commit") == "on",
        "git_push": form.get("git_push") == "on",
        "ide": form.get("ide") == "on",
        "computer_use": form.get("computer_use") == "on",
        "computer_use_observe": form.get("computer_use") == "on" and form.get("computer_use_observe") == "on",
        "computer_use_control": form.get("computer_use") == "on" and form.get("computer_use_control") == "on",
    }
    client = {
        "id": str(uuid.uuid4()),
        "name": name,
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "permissions": permissions,
        "created_at": now_iso(),
        "last_seen": None,
    }
    share.setdefault("clients", []).append(client)
    save_config(config)
    audit_event("ai_client.create", share, request, name, {"permissions": permissions})
    body = brand_header() + """
      <h2>AI client token created</h2>
      <p class="sub">Copy this token now. It is stored as a hash and cannot be shown again.</p>
      <div class="card-sm"><code id="client-token">%s</code></div>
      <button class="secondary" onclick="navigator.clipboard.writeText(document.getElementById('client-token').innerText)">Copy token</button>
      <p class="sub">Send it in the <code>X-Sf2AiS-Token</code> HTTP header. Do not put it in a URL.</p>
      <a class="btn" href="/dashboard">Return to dashboard</a>
    """ % html.escape(token)
    return page("AI Client Token", body)


@app.post("/dashboard/shares/{share_id}/clients/{client_id}/revoke")
def revoke_ai_client(share_id: str, client_id: str, request: Request, admin: str = Depends(admin_auth)):
    config = load_config()
    share = next((item for item in config.get("shares", []) if item.get("id") == share_id), None)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found.")
    before = len(share.get("clients", []))
    share["clients"] = [client for client in share.get("clients", []) if client.get("id") != client_id]
    if len(share["clients"]) == before:
        raise HTTPException(status_code=404, detail="AI client not found.")
    save_config(config)
    TERMINAL_SESSIONS.close_owner("client:" + client_id)
    CUA_DRIVER.close_owner(share_id + ":" + client_id)
    audit_event("ai_client.revoke", share, request, client_id)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/dashboard/shares/{share_id}/toggle-workspace-write")
def toggle_workspace_write(share_id: str, admin: str = Depends(admin_auth)):
    config = load_config()
    for item in config.get("shares", []):
        if item["id"] == share_id:
            item["workspace_write_enabled"] = not item.get("workspace_write_enabled", False)
            break
    save_config(config)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/dashboard/shares/{share_id}/permissions")
async def update_share_permissions(share_id: str, request: Request, admin: str = Depends(admin_auth)):
    config = load_config()
    share = next((item for item in config.get("shares", []) if item.get("id") == share_id), None)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found.")
    form = await request.form()
    share["ide_enabled"] = form.get("ide_enabled") == "on"
    share["computer_use_enabled"] = form.get("computer_use_enabled") == "on"
    share["computer_use_observe_enabled"] = form.get("computer_use_observe_enabled") == "on"
    share["computer_use_control_enabled"] = form.get("computer_use_control_enabled") == "on"
    save_config(config)
    if not share["computer_use_enabled"]:
        CUA_DRIVER.close_share(share_id)
    audit_event("share.permissions.updated", share, request, detail={
        "ide_enabled": share["ide_enabled"],
        "computer_use_enabled": share["computer_use_enabled"],
        "computer_use_observe_enabled": share["computer_use_observe_enabled"],
        "computer_use_control_enabled": share["computer_use_control_enabled"],
    })
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/dashboard/shares/{share_id}/toggle-tunnel")
def toggle_tunnel(share_id: str, admin: str = Depends(admin_auth)):
    config = load_config()
    for s in config.get("shares", []):
        if s["id"] == share_id:
            s["tunnel_enabled"] = not s.get("tunnel_enabled", False)
    save_config(config)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/dashboard/shares/{share_id}/delete")
def delete_share(share_id: str, admin: str = Depends(admin_auth)):
    config = load_config()
    config["shares"] = [s for s in config.get("shares", []) if s["id"] != share_id]
    save_config(config)
    TERMINAL_SESSIONS.close_share(share_id)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/api/status")
def api_status(admin: str = Depends(admin_auth)):
    config = load_config()
    net_online, net_msg = network_online_status(config)
    return JSONResponse({
        "network_online": net_online,
        "network_message": net_msg,
        "share_link": build_share_link(config),
        "shares": [
            {
                "id": s["id"], "username": s["username"], "folder": s["folder"],
                "last_seen": s.get("last_seen"),
            } for s in config.get("shares", [])
        ],
    })

# ---------------------------------------------------------------------------
# Native desktop control-plane API
# ---------------------------------------------------------------------------

def desktop_network_admin_snapshot(config: dict | None = None) -> dict:
    config = config or load_config() or {}
    network = config.get("network", {})
    online, message = network_online_status(config)
    try:
        lan_ip = network_connectivity.default_route_ip() or ""
    except Exception:
        lan_ip = ""
    try:
        https_port = int(network.get("port", 443))
        https_listener_ready = bool(lan_ip and network_connectivity.probe_https_endpoint(lan_ip, https_port, timeout=0.75))
    except (TypeError, ValueError, OSError):
        https_listener_ready = False
    try:
        relay = CLOUDFLARE_RELAY.status() or {}
    except Exception:
        relay = {"provider": "cloudflare", "available": False, "state": "error"}
    return {
        "online": online,
        "message": message,
        "share_link": build_share_link(config),
        "method": network.get("method", ""),
        "port": network.get("port", 443),
        "public_host": resolve_public_host(config) or "",
        "local_lan_ip": lan_ip,
        "https_listener_ready": https_listener_ready,
        "https_listener_status": ("TLS handshake succeeded on LAN port %s." % network.get("port", 443)) if https_listener_ready else ("No TLS listener responded on LAN port %s. Configure and start the HTTPS reverse proxy before requesting a router mapping." % network.get("port", 443)),
        "ddns_domain": (network.get("ddns") or {}).get("domain", ""),
        "ddns_provider": (network.get("ddns") or {}).get("provider", ""),
        "ddns_configured": bool((network.get("ddns") or {}).get("token")),
        "router_discovery": ROUTER_DISCOVERY,
        "mapping_protocols": MAPPING_PROTOCOLS,
        "nat_diagnostics": NAT_DIAGNOSTICS,
        "router_mapping": network.get("upnp_mapping"),
        "external_reachability": network.get("external_reachability") or {"status": "unverified"},
        "external_probe_pending": bool(network.get("external_probe")),
        "relay": {key: value for key, value in relay.items()
                  if key in {"provider", "enabled", "available", "state"}},
    }


@app.get("/api/desktop/state")
def desktop_control_state(admin: str = Depends(admin_auth)):
    """Return a safe administrative snapshot for the authenticated native client."""
    config = load_config() or {}
    shares = []
    for share in config.get("shares", []):
        shares.append({
            "id": share.get("id"),
            "username": share.get("username"),
            "folder": share.get("folder"),
            "legacy_auth_disabled": bool(share.get("legacy_auth_disabled", False)),
            "last_seen": share.get("last_seen"),
            "cli_enabled": bool(share.get("cli_enabled", False)),
            "tunnel_enabled": bool(share.get("tunnel_enabled", False)),
            "workspace_write_enabled": bool(share.get("workspace_write_enabled", False)),
            "ide_enabled": bool(share.get("ide_enabled", False)),
            "computer_use_enabled": bool(share.get("computer_use_enabled", False)),
            "computer_use_observe_enabled": bool(share.get("computer_use_observe_enabled", False)),
            "computer_use_control_enabled": bool(share.get("computer_use_control_enabled", False)),
            "clients": [{
                "id": client.get("id"),
                "name": client.get("name"),
                "created_at": client.get("created_at"),
                "last_seen": client.get("last_seen"),
                "permissions": client.get("permissions", {}),
                "project_access": client.get("permissions", {}).get("project_access", {"read": False, "write": False, "upload": False, "download": False, "deny": False, "rules": []}),
            } for client in share.get("clients", [])],
        })
    return JSONResponse({
        "app": {"name": APP_NAME, "version": "desktop-control-api-v1"},
        "network": desktop_network_admin_snapshot(config),
        "shares": shares,
        "capabilities": {
            "sandbox": bool(sandbox_runner.docker_binary()),
            "computer_use_provider": CUA_DRIVER.status(),
        },
    })


@app.post("/api/desktop/network/discover")
async def desktop_network_discover(request: Request, admin: str = Depends(admin_auth)):
    global ROUTER_DISCOVERY, MAPPING_PROTOCOLS, NAT_DIAGNOSTICS
    try:
        ROUTER_DISCOVERY = await asyncio.to_thread(network_connectivity.discover_router, timeout=1.5)
    except network_connectivity.NetworkSetupError as exc:
        ROUTER_DISCOVERY = {"available": False, "reason": str(exc)}
    try:
        MAPPING_PROTOCOLS = await asyncio.to_thread(network_connectivity.discover_mapping_protocols, ROUTER_DISCOVERY)
    except Exception as exc:
        MAPPING_PROTOCOLS = {
            "gateway": network_connectivity.default_gateway(),
            "upnp_igd": False, "nat_pmp": False, "pcp": False, "reason": str(exc)[:200],
        }
    try:
        NAT_DIAGNOSTICS = await asyncio.to_thread(network_connectivity.diagnose_nat, ROUTER_DISCOVERY)
    except Exception as exc:
        NAT_DIAGNOSTICS = {"external_reachability": "unverified", "reason": str(exc)[:200]}
    audit_event("router_discovery", request=request, detail={
        "available": bool(ROUTER_DISCOVERY.get("available")),
        "router_address": ROUTER_DISCOVERY.get("router_address"),
    })
    return {"ok": True, "network": desktop_network_admin_snapshot(load_config())}


@app.patch("/api/desktop/network")
async def desktop_update_network(request: Request, admin: str = Depends(admin_auth)):
    try:
        data = await request.json()
        raw_port = data.get("port") or 443
        if isinstance(raw_port, bool):
            raise ValueError("boolean is not a port")
        port = int(raw_port)
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="HTTPS port must be an integer.")
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail="HTTPS port must be between 1 and 65535.")
    config = load_config() or {}
    config.setdefault("network", {})["port"] = port
    save_config(config)
    mdns_state = "not-started"
    try:
        MDNS_ADVERTISER.stop()
        lan_ip = network_connectivity.default_route_ip()
        if lan_ip:
            started = await asyncio.to_thread(MDNS_ADVERTISER.start, lan_ip, port)
            mdns_state = "started" if started is not False else "unavailable"
    except Exception as exc:
        mdns_state = "error: " + str(exc)[:160]
    audit_event("network.https_port_updated", request=request, detail={"port": port, "mdns": mdns_state})
    return {"ok": True, "mdns": mdns_state, "network": desktop_network_admin_snapshot(config)}


@app.patch("/api/desktop/network/ddns")
async def desktop_update_ddns(request: Request, admin: str = Depends(admin_auth)):
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="A JSON settings object is required.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="A JSON settings object is required.")
    domain = str(data.get("domain") or "").strip().lower()
    token = str(data.get("token") or "").strip()
    if domain and not re.fullmatch(r"(?i)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.duckdns\.org)?", domain):
        raise HTTPException(status_code=400, detail="Enter a DuckDNS subdomain or full .duckdns.org hostname.")
    config = load_config() or {}
    network = config.setdefault("network", {})
    existing = network.get("ddns") or {}
    network["ddns"] = {
        "provider": "duckdns",
        "domain": domain or existing.get("domain", ""),
        "token": token or existing.get("token", ""),
        "last_result": existing.get("last_result"),
    }
    save_config(config)
    audit_event("network.ddns_updated", request=request, detail={
        "domain": network["ddns"]["domain"],
        "token_updated": bool(token),
    })
    return {"ok": True, "network": desktop_network_admin_snapshot(config)}


@app.post("/api/desktop/network/mapping")
async def desktop_create_router_mapping(request: Request, admin: str = Depends(admin_auth)):
    global ROUTER_DISCOVERY
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="A JSON mapping request is required.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="A JSON mapping request is required.")
    if data.get("confirm") != "CREATE" or data.get("approve") is not True:
        raise HTTPException(status_code=400, detail="Explicit router-forwarding approval is required.")
    method = str(data.get("method") or "upnp-igd").lower()
    if method not in {"upnp-igd", "nat-pmp", "pcp"}:
        raise HTTPException(status_code=400, detail="Unsupported router mapping method.")
    gateway = (ROUTER_DISCOVERY or {}).get("router_address") or MAPPING_PROTOCOLS.get("gateway")
    if method == "upnp-igd" and not (ROUTER_DISCOVERY and ROUTER_DISCOVERY.get("available")):
        raise HTTPException(status_code=409, detail="UPnP IGD was not discovered.")
    if method == "nat-pmp" and not MAPPING_PROTOCOLS.get("nat_pmp"):
        raise HTTPException(status_code=409, detail="NAT-PMP was not detected on the default gateway.")
    if method == "pcp" and not MAPPING_PROTOCOLS.get("pcp"):
        raise HTTPException(status_code=409, detail="PCP was not detected on the default gateway.")
    if not gateway:
        raise HTTPException(status_code=409, detail="No compatible router gateway was detected.")
    try:
        raw_internal = data.get("internal_port") or 0
        raw_external = data.get("external_port") or 0
        if isinstance(raw_internal, bool) or isinstance(raw_external, bool):
            raise ValueError("boolean is not a port")
        internal_port = int(raw_internal)
        external_port = int(raw_external)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Ports must be integers.") from exc
    if not 1 <= internal_port <= 65535 or not 1 <= external_port <= 65535:
        raise HTTPException(status_code=400, detail="Ports must be between 1 and 65535.")
    config = load_config() or {}
    network = config.setdefault("network", {})
    current_mapping = network.get("upnp_mapping")
    if current_mapping and not router_mapping_expired(current_mapping):
        raise HTTPException(status_code=409, detail="A router mapping is already recorded. Remove it before creating another.")
    configured_https_port = int(network.get("port", 443))
    if internal_port != configured_https_port:
        raise HTTPException(status_code=400, detail="Only the configured HTTPS reverse-proxy port can be forwarded.")
    local_ip = network_connectivity.default_route_ip()
    if not local_ip:
        raise HTTPException(status_code=503, detail="Could not determine the local LAN address.")
    if not await asyncio.to_thread(network_connectivity.probe_https_endpoint, local_ip, internal_port, timeout=2.0):
        raise HTTPException(status_code=409, detail="The selected LAN port did not complete an HTTPS handshake. Configure the TLS reverse proxy first; Sf2AiS itself listens on localhost:8000.")
    try:
        if method == "upnp-igd":
            result = await asyncio.to_thread(
                network_connectivity.apply_mapping, ROUTER_DISCOVERY, internal_port, external_port,
                protocol="TCP", description="Sf2AiS HTTPS gateway", lease_seconds=86400,
            )
        elif method == "nat-pmp":
            result = await asyncio.to_thread(network_connectivity.nat_pmp_map, gateway, internal_port, external_port, 86400, "TCP")
        else:
            result = await asyncio.to_thread(network_connectivity.pcp_map, gateway, internal_port, external_port, 86400, "TCP")
    except network_connectivity.NetworkSetupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    network["upnp_mapping"] = {
        **result, "method": method, "router_address": gateway, "created_at": now_iso(),
        "expires_at": datetime.fromtimestamp(time.time() + result["lease_seconds"], timezone.utc).isoformat(),
    }
    save_config(config)
    audit_event("router_mapping_created", request=request, detail={
        "router_address": gateway, "internal_port": internal_port,
        "external_port": external_port, "protocol": "TCP",
    })
    return {"ok": True, "mapping": network["upnp_mapping"], "network": desktop_network_admin_snapshot(config)}


@app.delete("/api/desktop/network/mapping")
def desktop_remove_router_mapping(request: Request, admin: str = Depends(admin_auth)):
    global ROUTER_DISCOVERY
    config = load_config() or {}
    network = config.get("network", {})
    mapping = network.get("upnp_mapping")
    if not mapping:
        return {"ok": True, "removed": False, "network": desktop_network_admin_snapshot(config)}
    router = None
    try:
        method = mapping.get("method", "upnp-igd")
        gateway = mapping.get("router_address")
        if method == "upnp-igd":
            router = network_connectivity.discover_router(timeout=1.5)
            if not router.get("available") or router.get("router_address") != gateway:
                raise HTTPException(status_code=409, detail="The original router was not found. The temporary lease will expire automatically; reconnect to that LAN to remove it.")
            network_connectivity.remove_mapping(router, int(mapping["external_port"]), mapping.get("protocol", "TCP"))
        elif method == "nat-pmp":
            network_connectivity.nat_pmp_remove(
                gateway, int(mapping["external_port"]), mapping.get("protocol", "TCP"),
                int(mapping.get("internal_port", mapping["external_port"])),
            )
        elif method == "pcp":
            network_connectivity.pcp_remove(
                gateway, int(mapping["internal_port"]), int(mapping["external_port"]),
                mapping.get("protocol", "TCP"), mapping.get("pcp_nonce"),
            )
        else:
            raise HTTPException(status_code=409, detail="Unknown stored router mapping protocol.")
    except network_connectivity.NetworkSetupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    network.pop("upnp_mapping", None)
    save_config(config)
    if router is not None:
        ROUTER_DISCOVERY = router
    audit_event("router_mapping_removed", request=request, detail={
        "router_address": mapping.get("router_address"),
        "external_port": mapping.get("external_port"),
        "protocol": mapping.get("protocol", "TCP"),
    })
    return {"ok": True, "removed": True, "network": desktop_network_admin_snapshot(config)}


@app.post("/api/desktop/network/verification")
def desktop_create_external_verification(request: Request, admin: str = Depends(admin_auth)):
    config = load_config() or {}
    network = config.get("network", {})
    public_host = resolve_public_host(config)
    if not public_host:
        raise HTTPException(status_code=409, detail="Configure a public domain or public IP before creating an external test link.")
    try:
        parsed_host = urlsplit("//" + str(public_host))
        host_value = parsed_host.hostname or ""
        try:
            ipaddress.ip_address(host_value)
        except ValueError:
            if not re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*", host_value):
                raise ValueError("invalid hostname")
        if parsed_host.port:
            raise ValueError("port must be configured separately")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="The configured public host is invalid.") from exc
    mapping = network.get("upnp_mapping") or {}
    port = int(mapping.get("external_port") or network.get("port", 443))
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail="The configured public port is invalid.")
    token = secrets.token_urlsafe(32)
    network["external_probe"] = {
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "expires_at": datetime.fromtimestamp(time.time() + 600, timezone.utc).isoformat(),
        "status": "pending",
    }
    save_config(config)
    audit_event("external_reachability_challenge_created", request=request, detail={
        "host": host_value, "port": port, "expires_in_seconds": 600,
    })
    authority = host_value
    if ":" in authority and not authority.startswith("["):
        authority = "[" + authority + "]"
    public_url = "https://" + authority + ((":" + str(port)) if port != 443 else "")
    verification_url = public_url + "/network/verify#" + token
    return {"ok": True, "url": verification_url, "expires_in_seconds": 600}


@app.get("/api/desktop/network/relay")
def desktop_network_relay_status(admin: str = Depends(admin_auth)):
    return desktop_network_admin_snapshot(load_config()).get("relay", {})


@app.post("/api/desktop/shares", status_code=201)
async def desktop_create_share(request: Request, admin: str = Depends(admin_auth)):
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON object required.")
    folder = str(data.get("folder", "")).strip()
    if not folder:
        raise HTTPException(status_code=400, detail="Project folder path is required.")
    config = load_config() or {}
    try:
        share_path = Path(folder).expanduser()
        share_path.mkdir(parents=True, exist_ok=True)
        share_path = share_path.resolve(strict=True)
        if not share_path.is_dir():
            raise ValueError("Path is not a directory.")
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Cannot use that folder: " + str(exc))
    share_id = str(uuid.uuid4())
    project_name = slugify(share_path.name)[:36] or "project"
    # New desktop-created projects use per-AI bearer tokens, not shared Basic-auth credentials.
    share = {
        "id": share_id,
        "username": project_name,
        "legacy_auth_disabled": True,
        "folder": str(share_path),
        "last_seen": None,
        "cli_enabled": bool(data.get("cli_enabled", False)),
        "tunnel_enabled": bool(data.get("tunnel_enabled", False)),
        "workspace_write_enabled": bool(data.get("workspace_write_enabled", False)),
        "ide_enabled": bool(data.get("ide_enabled", False)),
        "computer_use_enabled": False,
        "computer_use_observe_enabled": False,
        "computer_use_control_enabled": False,
        "clients": [],
    }
    config.setdefault("shares", []).append(share)
    save_config(config)
    audit_event("share.create", share, request, detail={"folder": str(share_path)})
    return JSONResponse({"share": {"id": share["id"], "username": share["username"], "folder": str(share_path)}}, status_code=201)


@app.patch("/api/desktop/shares/{share_id}")
async def desktop_update_share(share_id: str, request: Request, admin: str = Depends(admin_auth)):
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON object required.")
    allowed = {
        "cli_enabled", "tunnel_enabled", "workspace_write_enabled", "ide_enabled",
        "computer_use_enabled", "computer_use_observe_enabled", "computer_use_control_enabled",
    }
    if not data or set(data) - allowed or any(not isinstance(v, bool) for v in data.values()):
        raise HTTPException(status_code=400, detail="Only explicit boolean capability settings may be changed.")
    config = load_config() or {}
    share = next((item for item in config.get("shares", []) if item.get("id") == share_id), None)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found.")
    if data.get("computer_use_control_enabled") and not data.get("computer_use_enabled", share.get("computer_use_enabled", False)):
        raise HTTPException(status_code=400, detail="Computer-use control requires computer use to be enabled.")
    if data.get("computer_use_observe_enabled") and not data.get("computer_use_enabled", share.get("computer_use_enabled", False)):
        raise HTTPException(status_code=400, detail="Computer-use observation requires computer use to be enabled.")
    share.update(data)
    if not share.get("computer_use_enabled"):
        share["computer_use_observe_enabled"] = False
        share["computer_use_control_enabled"] = False
        CUA_DRIVER.close_share(share_id)
    save_config(config)
    audit_event("share.permissions.updated", share, request, detail=data)
    return JSONResponse({"ok": True, "share_id": share_id, "settings": {key: share.get(key, False) for key in allowed}})


@app.delete("/api/desktop/shares/{share_id}")
def desktop_delete_share(share_id: str, request: Request, admin: str = Depends(admin_auth)):
    config = load_config() or {}
    share = next((item for item in config.get("shares", []) if item.get("id") == share_id), None)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found.")
    config["shares"] = [item for item in config.get("shares", []) if item.get("id") != share_id]
    save_config(config)
    TERMINAL_SESSIONS.close_share(share_id)
    CUA_DRIVER.close_share(share_id)
    audit_event("share.delete", share, request)
    return JSONResponse({"ok": True})


@app.post("/api/desktop/shares/{share_id}/clients", status_code=201)
async def desktop_create_client(share_id: str, request: Request, admin: str = Depends(admin_auth)):
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON object required.")
    name = str(data.get("name", "")).strip()[:80]
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Client name must be at least two characters.")
    allowed = {"read", "write", "cli", "tunnel", "git_stage", "git_commit", "git_push", "ide", "computer_use", "computer_use_observe", "computer_use_control"}
    supplied = data.get("permissions", {})
    if not isinstance(supplied, dict) or set(supplied) - allowed or any(not isinstance(v, bool) for v in supplied.values()):
        raise HTTPException(status_code=400, detail="Invalid client permissions.")
    permissions = {key: bool(supplied.get(key, False)) for key in allowed}
    # A newly issued identity starts with no project-file access. Granular access
    # is granted separately by the project permission manager after issuance.
    permissions["read"] = False
    permissions["write"] = False
    permissions["project_access"] = {"read": False, "write": False, "upload": False, "download": False, "deny": False, "rules": []}
    if permissions["computer_use_control"] or permissions["computer_use_observe"]:
        if not permissions["computer_use"]:
            raise HTTPException(status_code=400, detail="Computer-use scopes require computer_use permission.")
    config = load_config() or {}
    share = next((item for item in config.get("shares", []) if item.get("id") == share_id), None)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found.")
    if permissions["write"] and not share.get("workspace_write_enabled", False):
        raise HTTPException(status_code=400, detail="Enable workspace write on this share before granting client write access.")
    if permissions["cli"] and not share.get("cli_enabled", False):
        raise HTTPException(status_code=400, detail="Enable CLI on this share before granting client CLI access.")
    if permissions["ide"] and not share.get("ide_enabled", False):
        raise HTTPException(status_code=400, detail="Enable IDE on this share before granting client IDE access.")
    if permissions["computer_use"] and not share.get("computer_use_enabled", False):
        raise HTTPException(status_code=400, detail="Enable computer use on this share before granting client access.")
    token = secrets.token_urlsafe(40)
    client = {
        "id": str(uuid.uuid4()),
        "name": name,
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "permissions": permissions,
        "created_at": now_iso(),
        "last_seen": None,
    }
    share.setdefault("clients", []).append(client)
    save_config(config)
    audit_event("ai_client.create", share, request, name, {"permissions": permissions})
    return JSONResponse({"client": {"id": client["id"], "name": name, "permissions": permissions}, "token": token}, status_code=201)


@app.get("/api/desktop/shares/{share_id}/tree")
def desktop_share_tree(share_id: str, path: str = "", admin: str = Depends(admin_auth)):
    config = load_config() or {}
    share = next((item for item in config.get("shares", []) if item.get("id") == share_id), None)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found.")
    try:
        return workspace_module.list_directory(share, path, depth=1)
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.patch("/api/desktop/shares/{share_id}/clients/{client_id}/project-access")
async def desktop_update_client_project_access(share_id: str, client_id: str, request: Request,
                                               admin: str = Depends(admin_auth)):
    data = await request.json()
    if not isinstance(data, dict) or set(data) != {"project_access"}:
        raise HTTPException(status_code=400, detail="Supply only a project_access permission object.")
    try:
        access = project_access_module.validate_access_config(data["project_access"])
        for rule in access["rules"]:
            if workspace_module.is_protected_path(rule["path"]):
                raise ValueError("Protected system paths cannot receive project permissions.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    config = load_config() or {}
    share = next((item for item in config.get("shares", []) if item.get("id") == share_id), None)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found.")
    client = next((item for item in share.get("clients", []) if item.get("id") == client_id), None)
    if not client:
        raise HTTPException(status_code=404, detail="AI client not found.")
    client.setdefault("permissions", {})["project_access"] = access
    # Legacy broad file scopes are disabled once the granular policy is saved.
    client["permissions"]["read"] = bool(access["read"] or any(r.get("read") for r in access["rules"]))
    client["permissions"]["write"] = bool(access["write"] or any(r.get("write") for r in access["rules"]))
    save_config(config)
    audit_event("ai_client.project_access.updated", share, request, client_id,
                {"root": {key: access[key] for key in project_access_module.PERMISSION_KEYS},
                 "path_rule_count": len(access["rules"])})
    return {"ok": True, "client_id": client_id, "project_access": access}


@app.delete("/api/desktop/shares/{share_id}/clients/{client_id}")
def desktop_revoke_client(share_id: str, client_id: str, request: Request, admin: str = Depends(admin_auth)):
    config = load_config() or {}
    share = next((item for item in config.get("shares", []) if item.get("id") == share_id), None)
    if not share:
        raise HTTPException(status_code=404, detail="Share not found.")
    before = len(share.get("clients", []))
    share["clients"] = [client for client in share.get("clients", []) if client.get("id") != client_id]
    if len(share["clients"]) == before:
        raise HTTPException(status_code=404, detail="AI client not found.")
    save_config(config)
    TERMINAL_SESSIONS.close_owner("client:" + client_id)
    CUA_DRIVER.close_owner(share_id + ":" + client_id)
    audit_event("ai_client.revoke", share, request, client_id)
    return JSONResponse({"ok": True})


@app.get("/api/desktop/activity")
def desktop_activity(limit: int = 100, admin: str = Depends(admin_auth)):
    limit = max(1, min(limit, 500))
    try:
        if not AUDIT_PATH.exists():
            return JSONResponse({"events": []})
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return JSONResponse({"events": list(reversed(events))})
    except OSError:
        raise HTTPException(status_code=500, detail="Could not read the audit log.")


# ---------------------------------------------------------------------------
# Probe (public IP updater) endpoint + downloadable script
# ---------------------------------------------------------------------------

@app.post("/api/ip-update")
async def ip_update(request: Request):
    config = load_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Not configured.")
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    token = data.get("token", "")
    ip_value = data.get("ip", "")
    expected = config.get("network", {}).get("probe_token", "")
    if not isinstance(token, str) or not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid probe token.")
    if not isinstance(ip_value, str) or len(ip_value) > 64:
        raise HTTPException(status_code=400, detail="Invalid IP format.")
    try:
        parsed_ip = ipaddress.ip_address(ip_value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid IP format.")
    if not parsed_ip.is_global:
        raise HTTPException(status_code=400, detail="The probe must report a globally routable public IP.")
    ip = str(parsed_ip)
    config["network"]["last_public_ip"] = ip
    config["network"]["last_ip_update"] = now_iso()
    ddns_cfg = config.get("network", {}).get("ddns")
    if ddns_cfg and ddns_cfg.get("token") and ddns_cfg.get("domain"):
        ok, msg = ddns_module.update(
            ddns_cfg.get("provider", "duckdns"), ddns_cfg["domain"], ddns_cfg["token"], ip
        )
        config["network"]["ddns"]["last_result"] = {"ok": ok, "message": msg, "at": now_iso()}
    save_config(config)
    return {"ok": True}

PROBE_SCRIPT = """#!/usr/bin/env python3
# Sf2AiS IP Probe
# Checks your public IP periodically and reports changes back to your gateway
# so your shareable link keeps working even if your IP address changes.
#
# Cross-platform: works on Windows, macOS, and Linux with Python 3 installed.
#
# USAGE:
#   python3 probe.py
#
# Schedule it to run every 5 minutes:
#   Windows  -> Task Scheduler: create a Basic Task, trigger "Repeat every 5 minutes",
#               action: python.exe, argument: full path to this script
#   macOS    -> cron: */5 * * * * /usr/bin/python3 /path/to/probe.py
#   Linux    -> cron: */5 * * * * /usr/bin/python3 /path/to/probe.py

import json
import urllib.request

GATEWAY_URL = "GATEWAY_URL_PLACEHOLDER"
PROBE_TOKEN = "PROBE_TOKEN_PLACEHOLDER"
CACHE_FILE = "sf2ais_probe_last_ip.txt"


def get_public_ip():
    with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
        return r.read().decode().strip()


def read_cached_ip():
    try:
        with open(CACHE_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def write_cached_ip(ip):
    with open(CACHE_FILE, "w") as f:
        f.write(ip)


def report_ip(ip):
    payload = json.dumps({"token": PROBE_TOKEN, "ip": ip}).encode()
    req = urllib.request.Request(
        GATEWAY_URL.rstrip("/") + "/api/ip-update",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def main():
    ip = get_public_ip()
    if ip != read_cached_ip():
        report_ip(ip)
        write_cached_ip(ip)
        print("IP changed -> " + ip + " (reported to gateway)")
    else:
        print("IP unchanged (" + ip + ") - nothing to do.")


if __name__ == "__main__":
    main()
"""

@app.get("/probe/download")
def probe_download(token: str = "", platform: str = "linux"):
    config = load_config() or {}
    gateway_url = build_share_link(config)
    if not gateway_url.startswith("https://"):
        gateway_url = "https://YOUR-GATEWAY-ADDRESS"
    script = PROBE_SCRIPT.replace("GATEWAY_URL_PLACEHOLDER", gateway_url).replace("PROBE_TOKEN_PLACEHOLDER", token)
    return Response(content=script, media_type="text/x-python",
                     headers={"Content-Disposition": "attachment; filename=probe.py"})

@app.get("/probe/setup-guide", response_class=HTMLResponse)
def probe_setup_guide():
    body = brand_header() + """
        <h2>IP Probe setup</h2>
        <p class="sub">1. Install Python 3 if it isn't already (comes preinstalled on most Mac/Linux systems).</p>
        <p class="sub">2. Open the downloaded <code>probe.py</code> and replace <code>GATEWAY_URL</code>
        with your gateway's real address (e.g. https://203.0.113.5 or your domain).</p>
        <p class="sub">3. Schedule it to run every 5 minutes:</p>
        <p class="sub"><strong>Windows</strong> - Task Scheduler &rarr; Create Basic Task &rarr; Trigger: repeat every 5 min &rarr; Action: run python.exe with the script path as argument.</p>
        <p class="sub"><strong>macOS / Linux</strong> - run <code>crontab -e</code> and add:</p>
        <code>*/5 * * * * /usr/bin/python3 /path/to/probe.py</code>
        <a class="btn secondary" style="margin-top:20px;" href="/dashboard">Back to dashboard</a>
    """
    return page("Probe Setup", body)


@app.get("/probe/desktop-app/{platform}")
def probe_desktop_app(
    platform: str,
    request: Request,
    arch: str = "x64",
    admin: str = Depends(admin_auth),
):
    """Serve the native desktop installer matching the requested OS/architecture."""
    requested_platform = platform.lower()
    user_agent = (request.headers.get("user-agent") or "").lower()

    # The ARM button intentionally selects ARM64 and infers the OS from the
    # requesting browser. It never silently falls back to an x64 binary.
    if requested_platform == "arm":
        arch = "arm64"
        if "windows" in user_agent:
            requested_platform = "windows"
        elif "macintosh" in user_agent or "mac os" in user_agent:
            requested_platform = "macos"
        elif "linux" in user_agent or "android" in user_agent:
            requested_platform = "linux"
        else:
            raise HTTPException(
                status_code=400,
                detail="Could not detect your operating system. Use the Windows, Linux, or macOS button instead.",
            )

    if requested_platform not in {"windows", "macos", "linux"}:
        raise HTTPException(status_code=404, detail="Unsupported platform. Use windows, macos, linux, or arm.")
    if arch not in {"x64", "arm64"}:
        raise HTTPException(status_code=400, detail="Unsupported architecture. Use x64 or arm64.")

    dist_dir = Path(__file__).parent / "probe-app" / "dist"
    try:
        desktop_package = json.loads((Path(__file__).parent / "probe-app" / "package.json").read_text(encoding="utf-8"))
        version = desktop_package["version"]
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=503, detail="Desktop package metadata is unavailable.")
    artifact_names = {
        "windows": ["SF2AiS-Desktop-Setup-%s-%s.exe" % (version, arch), "SF2AiS-Desktop-Portable-%s-%s.exe" % (version, arch)],
        "macos": ["SF2AiS-Desktop-%s-%s.dmg" % (version, arch), "SF2AiS-Desktop-%s-%s.zip" % (version, arch)],
        "linux": ["SF2AiS-Desktop-%s-%s.AppImage" % (version, arch), "SF2AiS-Desktop-%s-%s.deb" % (version, arch)],
    }
    download_path = next((dist_dir / name for name in artifact_names[requested_platform] if (dist_dir / name).is_file()), None)
    if download_path is None:
        expected = ", ".join(name for name in artifact_names[requested_platform] if name)
        raise HTTPException(
            status_code=404,
            detail=(
                "The %s %s installer has not been built or published on this server yet. "
                "Expected one of: %s. No other architecture will be substituted."
            ) % (requested_platform, arch, expected),
        )

    media_type = {
        ".exe": "application/vnd.microsoft.portable-executable",
        ".dmg": "application/x-apple-diskimage",
        ".zip": "application/zip",
        ".appimage": "application/octet-stream",
        ".deb": "application/vnd.debian.binary-package",
    }.get(download_path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=str(download_path),
        media_type=media_type,
        filename=download_path.name,
    )


# ---------------------------------------------------------------------------
# Workspace API + browser-native Workbench (no MCP required)
# ---------------------------------------------------------------------------

def workspace_error_response(exc: workspace_module.WorkspaceError):
    raise HTTPException(status_code=exc.status_code, detail=str(exc))


def require_project_permission(share: dict, path: str, action: str):
    """Enforce per-client path permissions on the server for every file operation."""
    token_permissions = share.get("_client_permissions")
    if token_permissions is None:
        # Legacy Basic-auth share access remains bounded by its existing share-wide
        # settings; AI tokens always use the granular project access policy.
        if action == "write" and not share.get("workspace_write_enabled", False):
            raise HTTPException(status_code=403, detail="Workspace editing is disabled for this share.")
        if action == "upload" and not share.get("workspace_write_enabled", False):
            raise HTTPException(status_code=403, detail="Uploads are disabled for this share.")
        return
    if action in ("write", "upload") and not share.get("workspace_write_enabled", False):
        raise HTTPException(status_code=403, detail="The administrator has disabled project write access for this share.")
    if action == "write" and not token_permissions.get("write", False):
        raise HTTPException(status_code=403, detail="This AI identity has no write capability.")
    if not project_access_module.is_allowed(token_permissions, path, action):
        raise HTTPException(status_code=403, detail="This AI identity is not permitted to %s this project path." % action)


def require_workspace_write(share: dict, path: str = "", action: str = "write"):
    require_project_permission(share, path, action)


def require_git_read_access(share: dict):
    permissions = share.get("_client_permissions")
    if permissions is not None and permissions.get("project_access", {}).get("rules"):
        raise HTTPException(status_code=403, detail="Repository-wide Git metadata is unavailable while path-specific project rules exist.")
    require_project_permission(share, "", "read")


def require_git_scope(share: dict, scope: str):
    permissions = share.get("_client_permissions")
    if permissions is None or not permissions.get(scope, False):
        raise HTTPException(status_code=403, detail="This operation requires an AI client token explicitly granted the %s scope." % scope)
    require_git_read_access(share)


@app.get("/api/network/status")
def api_network_status(admin: str = Depends(admin_auth)):
    config = load_config() or {}
    network = config.get("network", {})
    relay = CLOUDFLARE_RELAY.status()
    mapping = network.get("upnp_mapping")
    return {
        "relay": {"state": relay.get("state"), "enabled": relay.get("enabled")},
        "upnp_mapping": mapping,
        "local_address": network_connectivity.default_route_ip(),
        "default_gateway": MAPPING_PROTOCOLS.get("gateway") or network_connectivity.default_gateway(),
        "router_discovery": {
            "available": bool(ROUTER_DISCOVERY and ROUTER_DISCOVERY.get("available")),
            "router_address": (ROUTER_DISCOVERY or {}).get("router_address"),
            "reason": (ROUTER_DISCOVERY or {}).get("reason"),
        },
        "mapping_protocols": MAPPING_PROTOCOLS or network_connectivity.discover_mapping_protocols(ROUTER_DISCOVERY),
        "nat_diagnostics": NAT_DIAGNOSTICS,
        "router_setup_available": relay.get("state") != "connected" and not external_reachability_verified(network.get("external_reachability")) and (not mapping or router_mapping_expired(mapping)),
        "mdns": MDNS_ADVERTISER.status(),
        "external_reachability": "verified" if external_reachability_verified(network.get("external_reachability")) else "unverified",
        "note": "NAT diagnostics identify upstream NAT risks; they do not prove an inbound port is reachable.",
    }


@app.post("/dashboard/router/discover")
def dashboard_router_discover(admin: str = Depends(admin_auth)):
    global ROUTER_DISCOVERY, MAPPING_PROTOCOLS, NAT_DIAGNOSTICS
    try:
        ROUTER_DISCOVERY = network_connectivity.discover_router(timeout=1.5)
    except network_connectivity.NetworkSetupError as exc:
        ROUTER_DISCOVERY = {"available": False, "reason": str(exc)}
    try:
        MAPPING_PROTOCOLS = network_connectivity.discover_mapping_protocols(ROUTER_DISCOVERY)
    except Exception as exc:
        MAPPING_PROTOCOLS = {"gateway": network_connectivity.default_gateway(),
                             "upnp_igd": False, "nat_pmp": False, "pcp": False,
                             "reason": str(exc)[:200]}
    try:
        NAT_DIAGNOSTICS = network_connectivity.diagnose_nat(ROUTER_DISCOVERY)
    except Exception as exc:
        NAT_DIAGNOSTICS = {"external_reachability": "unverified", "reason": str(exc)[:200]}
    audit_event("router_discovery", detail={
        "available": bool(ROUTER_DISCOVERY.get("available")),
        "router_address": ROUTER_DISCOVERY.get("router_address"),
    })
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/dashboard/router/map")
async def dashboard_router_map(request: Request, admin: str = Depends(admin_auth)):
    global ROUTER_DISCOVERY
    form = await request.form()
    if form.get("confirm") != "CREATE" or form.get("approve") != "on":
        raise HTTPException(status_code=400, detail="Explicit forwarding approval is required.")
    method = str(form.get("method") or "upnp-igd").lower()
    if method not in {"upnp-igd", "nat-pmp", "pcp"}:
        raise HTTPException(status_code=400, detail="Unsupported router mapping method.")
    gateway = (ROUTER_DISCOVERY or {}).get("router_address") or MAPPING_PROTOCOLS.get("gateway")
    if method == "upnp-igd" and not (ROUTER_DISCOVERY and ROUTER_DISCOVERY.get("available")):
        raise HTTPException(status_code=409, detail="UPnP IGD was not discovered.")
    if method == "nat-pmp" and not MAPPING_PROTOCOLS.get("nat_pmp"):
        raise HTTPException(status_code=409, detail="NAT-PMP was not detected on the default gateway.")
    if method == "pcp" and not MAPPING_PROTOCOLS.get("pcp"):
        raise HTTPException(status_code=409, detail="PCP was not detected on the default gateway.")
    if not gateway:
        raise HTTPException(status_code=409, detail="No compatible router gateway was detected.")
    try:
        internal_port = int(form.get("internal_port") or 0)
        external_port = int(form.get("external_port") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Ports must be integers.")
    if not 1 <= internal_port <= 65535 or not 1 <= external_port <= 65535:
        raise HTTPException(status_code=400, detail="Ports must be between 1 and 65535.")
    current_network = (load_config() or {}).get("network", {})
    current_mapping = current_network.get("upnp_mapping")
    if current_mapping and not router_mapping_expired(current_mapping):
        raise HTTPException(status_code=409, detail="A router mapping is already recorded. Remove it before creating another.")
    configured_https_port = int(current_network.get("port", 443))
    if internal_port != configured_https_port:
        raise HTTPException(status_code=400, detail="Only the configured HTTPS reverse-proxy port can be forwarded.")
    local_ip = network_connectivity.default_route_ip()
    if not local_ip:
        raise HTTPException(status_code=503, detail="Could not determine the local LAN address.")
    if not network_connectivity.probe_https_endpoint(local_ip, internal_port, timeout=2.0):
        raise HTTPException(status_code=409, detail="The selected LAN port did not complete an HTTPS handshake. Start/configure the TLS reverse proxy first; Sf2AiS itself listens on localhost:8000.")
    try:
        if method == "upnp-igd":
            result = network_connectivity.apply_mapping(
                ROUTER_DISCOVERY, internal_port, external_port, protocol="TCP",
                description="Sf2AiS HTTPS gateway", lease_seconds=86400,
            )
        elif method == "nat-pmp":
            result = network_connectivity.nat_pmp_map(
                gateway, internal_port, external_port, 86400, "TCP"
            )
        else:
            result = network_connectivity.pcp_map(
                gateway, internal_port, external_port, 86400, "TCP"
            )
        router_ip = gateway
        config = load_config()
        config.setdefault("network", {})["upnp_mapping"] = {
            **result, "method": method, "router_address": router_ip, "created_at": now_iso(),
            "expires_at": datetime.fromtimestamp(time.time() + result["lease_seconds"], timezone.utc).isoformat(),
        }
        save_config(config)
        audit_event("router_mapping_created", request=request, detail={
            "router_address": router_ip, "internal_port": internal_port,
            "external_port": external_port, "protocol": "TCP",
        })
    except network_connectivity.NetworkSetupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/dashboard/router/remove")
def dashboard_router_remove(request: Request, admin: str = Depends(admin_auth)):
    global ROUTER_DISCOVERY
    config = load_config()
    network = config.get("network", {})
    mapping = network.get("upnp_mapping")
    if not mapping:
        return RedirectResponse(url="/dashboard", status_code=303)
    router = None
    try:
        method = mapping.get("method", "upnp-igd")
        gateway = mapping.get("router_address")
        if method == "upnp-igd":
            router = network_connectivity.discover_router(timeout=1.5)
            if not router.get("available") or router.get("router_address") != gateway:
                raise HTTPException(status_code=409, detail="The original router was not found. The temporary lease will expire automatically; reconnect to that LAN to remove it.")
            network_connectivity.remove_mapping(router, int(mapping["external_port"]), mapping.get("protocol", "TCP"))
        elif method == "nat-pmp":
            network_connectivity.nat_pmp_remove(
                gateway, int(mapping["external_port"]), mapping.get("protocol", "TCP"),
                int(mapping.get("internal_port", mapping["external_port"]))
            )
        elif method == "pcp":
            network_connectivity.pcp_remove(
                gateway, int(mapping["internal_port"]), int(mapping["external_port"]),
                mapping.get("protocol", "TCP"), mapping.get("pcp_nonce")
            )
        else:
            raise HTTPException(status_code=409, detail="Unknown stored router mapping protocol.")
        network.pop("upnp_mapping", None)
        save_config(config)
        if router is not None:
            ROUTER_DISCOVERY = router
        audit_event("router_mapping_removed", request=request, detail={
            "router_address": mapping.get("router_address"),
            "external_port": mapping.get("external_port"),
            "protocol": mapping.get("protocol", "TCP"),
        })
    except network_connectivity.NetworkSetupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/dashboard/network/verification")
def create_external_verification(request: Request, admin: str = Depends(admin_auth)):
    """Create a short-lived, one-time challenge to be opened from mobile data."""
    config = load_config() or {}
    network = config.get("network", {})
    public_host = resolve_public_host(config)
    if not public_host:
        raise HTTPException(status_code=409, detail="Configure a public domain or public IP before creating an external test link.")
    try:
        parsed_host = urlsplit("//" + str(public_host))
        host_value = parsed_host.hostname or ""
        try:
            ipaddress.ip_address(host_value)
        except ValueError:
            if not re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*", host_value):
                raise ValueError("invalid hostname")
        if parsed_host.port:
            raise ValueError("port must be configured separately")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="The configured public host is invalid.") from exc
    mapping = network.get("upnp_mapping") or {}
    port = int(mapping.get("external_port") or network.get("port", 443))
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail="The configured public port is invalid.")
    token = secrets.token_urlsafe(32)
    network["external_probe"] = {
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "expires_at": datetime.fromtimestamp(time.time() + 600, timezone.utc).isoformat(),
        "status": "pending",
    }
    save_config(config)
    audit_event("external_reachability_challenge_created", request=request, detail={
        "host": host_value, "port": port, "expires_in_seconds": 600,
    })
    authority = host_value
    if ":" in authority and not authority.startswith("["):
        authority = "[" + authority + "]"
    public_url = "https://" + authority + ((":" + str(port)) if port != 443 else "")
    link = public_url + "/network/verify#" + token
    body = """<div class="card"><h2>External connection test</h2><p>Open this link on a phone with Wi-Fi switched off, using mobile data, or from another genuinely external network.</p><p><a href="%s">%s</a></p><p class="sub">The challenge expires in 10 minutes and can be used once. It does not grant workspace access or authenticate a user.</p></div>""" % (html.escape(link, quote=True), html.escape(link))
    return HTMLResponse(page("External connection test", body))


@app.get("/network/verify", response_class=HTMLResponse)
def external_verification_page():
    return HTMLResponse("""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sf2AiS connectivity test</title></head><body><main><h1>Verify external connection</h1><p>Press the button to confirm that this Sf2AiS endpoint can be reached from this network.</p><button id="verify">Verify this connection</button><p id="result" role="status"></p></main><script>
const button=document.getElementById("verify"),result=document.getElementById("result");
button.addEventListener("click",async()=>{button.disabled=true;result.textContent="Checkingâ€¦";try{const token=location.hash.slice(1);const response=await fetch("/network/verify",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token})});const data=await response.json();result.textContent=data.message||"Verification failed.";if(response.ok)history.replaceState(null,"",location.pathname);}catch(e){result.textContent="Could not complete the check. Please try again.";}finally{button.disabled=false;}});
</script></body></html>""")


@app.post("/network/verify")
async def confirm_external_verification(request: Request):
    try:
        body = await request.json()
        token = str(body.get("token", ""))
    except Exception:
        raise HTTPException(status_code=400, detail="A valid verification token is required.")
    if not 32 <= len(token) <= 128:
        raise HTTPException(status_code=400, detail="A valid verification token is required.")
    config = load_config() or {}
    network = config.get("network", {})
    challenge = network.get("external_probe") or {}
    expected = challenge.get("token_hash", "")
    supplied = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not expected or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="This verification link is invalid or has already been used.")
    try:
        expiry = datetime.fromisoformat(challenge.get("expires_at", ""))
    except (TypeError, ValueError):
        expiry = datetime.min.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        network.pop("external_probe", None)
        save_config(config)
        raise HTTPException(status_code=410, detail="This verification link has expired. Generate a new one from the dashboard.")
    client_ip = request.client.host if request.client else ""
    try:
        remote_address = ipaddress.ip_address(client_ip)
    except ValueError:
        raise HTTPException(status_code=403, detail="The remote network address could not be verified.")
    if not remote_address.is_global:
        raise HTTPException(status_code=403, detail="This request appears to come from a private or local network. Switch off Wi-Fi and retry using mobile data.")
    network["external_reachability"] = {
        "status": "verified", "verified_at": now_iso(),
        "remote_ip": client_ip, "method": "one-time external HTTPS challenge",
    }
    network.pop("external_probe", None)
    save_config(config)
    global NAT_DIAGNOSTICS
    NAT_DIAGNOSTICS = {
        **NAT_DIAGNOSTICS, "external_reachability": "verified",
        "verified_at": network["external_reachability"]["verified_at"],
        "verification_method": "one-time external HTTPS challenge",
    }
    audit_event("external_reachability_verified", request=request, detail={
        "remote_ip": client_ip, "method": "one-time external HTTPS challenge",
    })
    return {"ok": True, "message": "External HTTPS reachability verified successfully."}


@app.get("/api/relay/status")
def api_relay_status(admin: str = Depends(admin_auth)):
    return CLOUDFLARE_RELAY.status()


@app.get("/api/audit")
def api_audit(limit: int = 100, admin: str = Depends(admin_auth)):
    limit = max(1, min(limit, 500))
    if not AUDIT_PATH.exists():
        return {"events": []}
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return {"events": events}
    except OSError:
        raise HTTPException(status_code=500, detail="Audit log could not be read.")


def require_ide_enabled(share: dict):
    if not share.get("ide_enabled", False):
        raise HTTPException(status_code=403, detail="IDE integration is disabled for this share.")
    permissions = share.get("_client_permissions")
    if permissions is not None and not permissions.get("ide", False):
        raise HTTPException(status_code=403, detail="This AI client token does not have IDE permission.")


def effective_computer_use_permission(share: dict) -> bool:
    if not share.get("computer_use_enabled", False):
        return False
    permissions = share.get("_client_permissions")
    return permissions is None or bool(permissions.get("computer_use", False))


def require_computer_use_scope(share: dict, scope: str) -> None:
    if not effective_computer_use_permission(share):
        raise HTTPException(status_code=403, detail="Computer use is disabled for this share or AI client.")
    if scope == "observe" and not share.get("computer_use_observe_enabled", False):
        raise HTTPException(status_code=403, detail="Screen observation is disabled for this share.")
    if scope == "control" and not share.get("computer_use_control_enabled", False):
        raise HTTPException(status_code=403, detail="Mouse and keyboard control is disabled for this share.")
    permissions = share.get("_client_permissions")
    if permissions is not None:
        if scope == "observe" and not permissions.get("computer_use_observe", permissions.get("computer_use", False)):
            raise HTTPException(status_code=403, detail="This AI client token does not have screen observation permission.")
        if scope == "control" and not permissions.get("computer_use_control", False):
            raise HTTPException(status_code=403, detail="This AI client token does not have mouse and keyboard permission.")


def computer_use_owner(share: dict) -> str:
    return str(share.get("id", "")) + ":" + str(share.get("_client_id") or "basic")


@app.get("/api/computer-use/status")
def computer_use_status(share: dict = Depends(share_auth)):
    provider = CUA_DRIVER.status()
    permissions = share.get("_client_permissions") or {}
    enabled = effective_computer_use_permission(share)
    observe_allowed = enabled and bool(share.get("computer_use_observe_enabled", False)) and (
        share.get("_client_permissions") is None
        or bool(permissions.get("computer_use_observe", permissions.get("computer_use", False)))
    )
    control_allowed = enabled and bool(share.get("computer_use_control_enabled", False)) and (
        share.get("_client_permissions") is None or bool(permissions.get("computer_use_control", False))
    )
    exposed_tools = (OBSERVATION_TOOLS if observe_allowed else set()) | (ACTION_TOOLS if control_allowed else set())
    return {
        "provider": provider,
        "enabled": enabled,
        "observe_allowed": observe_allowed,
        "control_allowed": control_allowed,
        "session_start_requires_confirmation": True,
        "exposed_tools": sorted(exposed_tools),
    }


@app.post("/api/computer-use/sessions")
async def computer_use_start_session(request: Request, share: dict = Depends(share_auth)):
    require_computer_use_scope(share, "observe")
    try:
        data = await request.json()
    except Exception:
        data = {}
    if data.get("confirm") != "START":
        raise HTTPException(status_code=400, detail="Explicit session confirmation is required.")
    allow_control = bool(data.get("allow_control", False))
    if allow_control:
        require_computer_use_scope(share, "control")
    owner = computer_use_owner(share)
    try:
        session_id = CUA_DRIVER.create_session(owner, allow_control=allow_control)
    except CuaDriverError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    audit_event("computer_use.session.started", share, request, session_id, {
        "control_allowed": allow_control
    })
    return {
        "session_id": session_id,
        "state": "active",
        "expires_in_seconds": 1800,
        "control_allowed": allow_control,
    }


@app.post("/api/computer-use/sessions/{session_id}/observe")
async def computer_use_observe(session_id: str, request: Request, share: dict = Depends(share_auth)):
    require_computer_use_scope(share, "observe")
    data = await request.json()
    tool = data.get("tool", "get_desktop_state")
    if tool not in OBSERVATION_TOOLS:
        raise HTTPException(status_code=400, detail="Only observation tools are accepted on this endpoint.")
    arguments = data.get("arguments", {})
    if not isinstance(arguments, dict):
        raise HTTPException(status_code=400, detail="Tool arguments must be an object.")
    try:
        result = CUA_DRIVER.call(session_id, computer_use_owner(share), tool, arguments)
    except CuaDriverError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    audit_event("computer_use.observe", share, request, session_id, {"tool": tool})
    return result


@app.post("/api/computer-use/sessions/{session_id}/action")
async def computer_use_action(session_id: str, request: Request, share: dict = Depends(share_auth)):
    require_computer_use_scope(share, "control")
    data = await request.json()
    tool = data.get("tool")
    if tool not in ACTION_TOOLS:
        raise HTTPException(status_code=400, detail="This action is not exposed through Sf2AiS.")
    arguments = data.get("arguments", {})
    if not isinstance(arguments, dict):
        raise HTTPException(status_code=400, detail="Tool arguments must be an object.")
    if tool == "type_text" and len(str(arguments.get("text", ""))) > 1000:
        raise HTTPException(status_code=413, detail="Text input is limited to 1000 characters per action.")
    try:
        result = CUA_DRIVER.call(session_id, computer_use_owner(share), tool, arguments)
    except CuaDriverError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    audit_event("computer_use.action", share, request, session_id, {"tool": tool})
    return result


@app.delete("/api/computer-use/sessions/{session_id}")
def computer_use_end_session(session_id: str, request: Request, share: dict = Depends(share_auth)):
    if not CUA_DRIVER.end_session(session_id, computer_use_owner(share)):
        raise HTTPException(status_code=404, detail="Computer-use session not found for this client.")
    audit_event("computer_use.session.ended", share, request, session_id)
    return {"session_id": session_id, "state": "ended"}


@app.get("/api/ide/status")
def ide_status(share: dict = Depends(share_auth)):
    require_ide_enabled(share)
    return {
        "enabled": True,
        "mode": "scoped-remote-filesystem",
        "read": project_access_module.is_allowed(share.get("_client_permissions"), "", "read"),
        "write": bool(share.get("workspace_write_enabled", False)) and (
            share.get("_client_permissions") is None or (bool(share["_client_permissions"].get("write", False)) and project_access_module.is_allowed(share["_client_permissions"], "", "write"))
        ),
        "host_terminal": False,
        "workspace_root": "share",
        "computer_use_available": CUA_DRIVER.status()["available"],
        "note": "IDE access is limited to the share filesystem. Host terminal, tasks, and arbitrary host process execution are not exposed.",
    }


@app.get("/api/ide/tree")
def ide_workspace_tree(path: str = "", depth: int = 2, share: dict = Depends(share_auth)):
    require_ide_enabled(share)
    require_project_permission(share, path, "read")
    try:
        result = workspace_module.list_directory(share, path, depth=max(1, min(depth, 4)))
        if share.get("_client_permissions") is not None:
            result["entries"] = [entry for entry in result["entries"] if project_access_module.is_allowed(share["_client_permissions"], entry["path"], "read")]
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.get("/api/ide/file")
def ide_workspace_read_file(path: str, request: Request, share: dict = Depends(share_auth)):
    require_ide_enabled(share)
    require_project_permission(share, path, "read")
    try:
        result = workspace_module.read_text_file(share, path)
        audit_event("ide.read", share, request, path)
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.put("/api/ide/file")
async def ide_workspace_write_file(request: Request, share: dict = Depends(share_auth)):
    require_ide_enabled(share)
    try:
        data = await request.json()
        require_workspace_write(share, data.get("path", ""), "write")
        result = workspace_module.write_text_file(share, data.get("path", ""), data.get("content"))
        audit_event("ide.write", share, request, result["path"], {"bytes": result["size"]})
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.post("/api/ide/directory")
async def ide_workspace_create_directory(request: Request, share: dict = Depends(share_auth)):
    require_ide_enabled(share)
    try:
        data = await request.json()
        require_workspace_write(share, data.get("path", ""), "write")
        result = workspace_module.create_directory(share, data.get("path", ""))
        audit_event("ide.mkdir", share, request, result["path"])
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.post("/api/ide/move")
async def ide_workspace_move(request: Request, share: dict = Depends(share_auth)):
    require_ide_enabled(share)
    try:
        data = await request.json()
        require_workspace_write(share, data.get("source", ""), "write")
        require_workspace_write(share, data.get("destination", ""), "write")
        result = workspace_module.move_path(share, data.get("source", ""), data.get("destination", ""))
        audit_event("ide.move", share, request, result["source"], {"destination": result["destination"]})
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.delete("/api/ide/path")
def ide_workspace_delete(path: str, request: Request, share: dict = Depends(share_auth)):
    require_ide_enabled(share)
    require_workspace_write(share, path, "write")
    try:
        result = workspace_module.delete_path(share, path)
        audit_event("ide.delete", share, request, result["path"])
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.get("/api/workspace/status")
def workspace_status(share: dict = Depends(share_auth)):
    relay_status = CLOUDFLARE_RELAY.status()
    return {
        "name": APP_NAME,
        "workspace": True,
        "read_enabled": project_access_module.is_allowed(share.get("_client_permissions"), "", "read"),
        "write_enabled": bool(share.get("workspace_write_enabled", False)) and (share.get("_client_permissions") is None or (bool(share["_client_permissions"].get("write", False)) and project_access_module.is_allowed(share["_client_permissions"], "", "write"))),
        "ide_enabled": bool(share.get("ide_enabled", False)) and (share.get("_client_permissions") is None or bool(share["_client_permissions"].get("ide", False))),
        "computer_use_enabled": effective_computer_use_permission(share),
        "computer_use_available": CUA_DRIVER.status()["available"],
        "computer_use_provider": CUA_DRIVER.status(),
        "computer_use_observe_enabled": bool(share.get("computer_use_observe_enabled", False)) and effective_computer_use_permission(share),
        "computer_use_control_enabled": bool(share.get("computer_use_control_enabled", False)) and effective_computer_use_permission(share),
        "cli_enabled": bool(share.get("cli_enabled", False)) and (share.get("_client_permissions") is None or bool(share["_client_permissions"].get("cli", False))),
        "tunnel_enabled": bool(share.get("tunnel_enabled", False)) and (share.get("_client_permissions") is None or bool(share["_client_permissions"].get("tunnel", False))),
        "git_permissions": {scope: bool((share.get("_client_permissions") or {}).get(scope, False)) for scope in ("git_stage", "git_commit", "git_push")},
        "sandbox": sandbox_runner.sandbox_status(),
        "outbound_relay": {key: relay_status[key] for key in ("provider", "enabled", "available", "state") if key in relay_status},
    }


@app.get("/api/workspace/tree")
def workspace_tree(path: str = "", depth: int = 2, share: dict = Depends(share_auth)):
    require_project_permission(share, path, "read")
    try:
        result = workspace_module.list_directory(share, path, depth=depth)
        if share.get("_client_permissions") is not None:
            result["entries"] = [entry for entry in result["entries"]
                                 if project_access_module.is_allowed(share["_client_permissions"], entry["path"], "read")]
        audit_event("workspace.list", share, path=path)
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.get("/api/workspace/file")
def workspace_read_file(path: str, request: Request, share: dict = Depends(share_auth)):
    require_project_permission(share, path, "read")
    try:
        result = workspace_module.read_text_file(share, path)
        audit_event("workspace.read", share, request, path)
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.put("/api/workspace/file")
async def workspace_write_file(request: Request, share: dict = Depends(share_auth)):
    try:
        data = await request.json()
        require_workspace_write(share, data.get("path", ""), "write")
        result = workspace_module.write_text_file(share, data.get("path", ""), data.get("content"))
        audit_event("workspace.write", share, request, result["path"], {"bytes": result["size"]})
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.post("/api/workspace/directory")
async def workspace_create_directory(request: Request, share: dict = Depends(share_auth)):
    try:
        data = await request.json()
        require_workspace_write(share, data.get("path", ""), "write")
        result = workspace_module.create_directory(share, data.get("path", ""))
        audit_event("workspace.mkdir", share, request, result["path"])
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.post("/api/workspace/move")
async def workspace_move(request: Request, share: dict = Depends(share_auth)):
    try:
        data = await request.json()
        require_workspace_write(share, data.get("source", ""), "write")
        require_workspace_write(share, data.get("destination", ""), "write")
        result = workspace_module.move_path(share, data.get("source", ""), data.get("destination", ""))
        audit_event("workspace.move", share, request, result["source"], {"destination": result["destination"]})
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.delete("/api/workspace/path")
def workspace_delete(path: str, request: Request, share: dict = Depends(share_auth)):
    require_workspace_write(share, path, "write")
    try:
        result = workspace_module.delete_path(share, path)
        audit_event("workspace.delete", share, request, result["path"])
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)



@app.get("/api/workspace/download")
def workspace_download(path: str, request: Request, share: dict = Depends(share_auth)):
    require_project_permission(share, path, "download")
    try:
        target = workspace_module.resolve_path(share, path, allow_root=False)
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="File not found.")
        audit_event("workspace.download", share, request, path)
        media_type, _ = guess_type(str(target))
        return FileResponse(path=str(target), media_type=media_type or "application/octet-stream",
                            filename=target.name)
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.post("/api/workspace/upload")
async def workspace_upload(request: Request, path: str = Form(...), file: UploadFile = File(...),
                           share: dict = Depends(share_auth)):
    require_workspace_write(share, path, "upload")
    try:
        data = await file.read(workspace_module.MAX_UPLOAD_BYTES + 1)
        result = workspace_module.write_binary_file(share, path, data)
        audit_event("workspace.upload", share, request, path, {"bytes": result["size"]})
        return result
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)
    finally:
        await file.close()


@app.get("/api/workspace/git/status")
def workspace_git_status(request: Request, share: dict = Depends(share_auth)):
    require_git_read_access(share)
    root = Path(share["folder"]).resolve()
    if not (root / ".git").exists():
        raise HTTPException(status_code=404, detail="This share is not a Git working tree.")
    git = shutil.which("git")
    if not git:
        raise HTTPException(status_code=503, detail="Git is not installed on the server.")
    excludes = [
        ":(exclude,glob)**/.env*", ":(exclude,glob)**/*.pem",
        ":(exclude,glob)**/*.key", ":(exclude,glob)**/id_rsa",
        ":(exclude,glob)**/id_ed25519", ":(exclude,glob)**/data/config.json",
    ]
    try:
        result = subprocess.run([git, "-C", str(root), "status", "--short", "--branch", "--", ".", *excludes],
                                capture_output=True, text=True, timeout=10,
                                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat"})
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Git status timed out.")
    if result.returncode:
        raise HTTPException(status_code=500, detail=(result.stderr or "Git status failed.")[:1000])
    audit_event("git.status", share, request)
    return {"status": result.stdout[:20000]}


@app.post("/api/workspace/git/stage")
async def workspace_git_stage(request: Request, share: dict = Depends(share_auth)):
    require_git_scope(share, "git_stage")
    require_workspace_write(share, "", "write")
    try:
        data = await request.json()
        if data.get("confirm") != "STAGE":
            raise HTTPException(status_code=400, detail='Explicit confirmation required: confirm="STAGE".')
        result = git_workflow_module.stage_files(share, data.get("paths"))
        audit_event("git.stage", share, request, details={"paths": result["staged"]})
        return result
    except git_workflow_module.GitWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.post("/api/workspace/git/commit")
async def workspace_git_commit(request: Request, share: dict = Depends(share_auth)):
    require_git_scope(share, "git_commit")
    require_workspace_write(share, "", "write")
    try:
        data = await request.json()
        if data.get("confirm") != "COMMIT":
            raise HTTPException(status_code=400, detail='Explicit confirmation required: confirm="COMMIT".')
        result = git_workflow_module.commit_staged(share, data.get("message"))
        audit_event("git.commit", share, request, details={"commit": result["commit"]})
        return result
    except git_workflow_module.GitWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.post("/api/workspace/git/push")
async def workspace_git_push(request: Request, share: dict = Depends(share_auth)):
    require_git_scope(share, "git_push")
    require_workspace_write(share, "", "write")
    try:
        data = await request.json()
        if data.get("confirm") != "PUSH":
            raise HTTPException(status_code=400, detail='Explicit confirmation required: confirm="PUSH".')
        result = git_workflow_module.push_branch(share, data.get("remote", "origin"), data.get("branch"))
        audit_event("git.push", share, request, details={"remote": result["remote"], "branch": result["branch"]})
        return result
    except git_workflow_module.GitWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get("/api/workspace/git/staged")
def workspace_git_staged(request: Request, share: dict = Depends(share_auth)):
    require_git_read_access(share)
    try:
        result = git_workflow_module.staged_changes(share)
        audit_event("git.staged", share, request, details={"file_count": result["file_count"]})
        return result
    except git_workflow_module.GitWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get("/api/workspace/git/branches")
def workspace_git_branches(request: Request, share: dict = Depends(share_auth)):
    require_git_read_access(share)
    try:
        result = git_workflow_module.list_branches(share)
        audit_event("git.branches", share, request)
        return result
    except git_workflow_module.GitWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get("/api/workspace/git/log")
def workspace_git_log(request: Request, limit: int = 20, share: dict = Depends(share_auth)):
    require_git_read_access(share)
    try:
        result = git_workflow_module.recent_commits(share, limit)
        audit_event("git.log", share, request, details={"limit": limit})
        return result
    except git_workflow_module.GitWorkflowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get("/api/workspace/git/diff")
def workspace_git_diff(path: str = "", request: Request = None, share: dict = Depends(share_auth)):
    if path:
        require_project_permission(share, path, "read")
    else:
        require_git_read_access(share)
    root = Path(share["folder"]).resolve()
    if not (root / ".git").exists():
        raise HTTPException(status_code=404, detail="This share is not a Git working tree.")
    git = shutil.which("git")
    if not git:
        raise HTTPException(status_code=503, detail="Git is not installed on the server.")
    args = [git, "-C", str(root), "diff", "--no-ext-diff", "--no-color", "--"]
    if path:
        try:
            workspace_module.resolve_path(share, path, allow_root=False)
        except workspace_module.WorkspaceError as exc:
            workspace_error_response(exc)
        args.append(path.replace("\\\\", "/"))
    else:
        args.append(".")
    args.extend([
        ":(exclude,glob)**/.env*", ":(exclude,glob)**/*.pem",
        ":(exclude,glob)**/*.key", ":(exclude,glob)**/id_rsa",
        ":(exclude,glob)**/id_ed25519", ":(exclude,glob)**/data/config.json",
    ])
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10,
                                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat"})
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Git diff timed out.")
    if result.returncode:
        raise HTTPException(status_code=500, detail=(result.stderr or "Git diff failed.")[:1000])
    audit_event("git.diff", share, request, path)
    return {"diff": result.stdout[:100000], "truncated": len(result.stdout) > 100000}



# ---------------------------------------------------------------------------
# No-JavaScript browser workflow for browsing-only AI agents
# ---------------------------------------------------------------------------

@app.get("/browse", response_class=HTMLResponse)
def browse_nojs(path: str = "", share: dict = Depends(share_auth)):
    require_project_permission(share, path, "read")
    try:
        listing = workspace_module.list_directory(share, path, depth=3)
        if share.get("_client_permissions") is not None:
            listing["entries"] = [item for item in listing["entries"] if project_access_module.is_allowed(share["_client_permissions"], item["path"], "read")]
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)
    rows = []
    if path:
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        rows.append('<li><a href="/browse?path=%s">.. (parent)</a></li>' % quote(parent, safe=""))
    for item in listing["entries"]:
        encoded = quote(item["path"], safe="")
        name = html.escape(item["name"])
        if item["type"] == "directory":
            rows.append('<li>ðŸ“ <a href="/browse?path=%s">%s/</a></li>' % (encoded, name))
        else:
            size = item["size"] or 0
            rows.append('<li>ðŸ“„ <a href="/browse/file?path=%s">%s</a> <small>(%s bytes)</small></li>' %
                        (encoded, name, size))
    write_controls = ""
    if share.get("workspace_write_enabled", False) and (
        share.get("_client_permissions") is None or share["_client_permissions"].get("write", False)
    ):
        write_controls = """
        <h3>Create directory</h3>
        <form method="post" action="/browse/mkdir">
          <input type="hidden" name="parent" value="%s">
          <input name="name" required placeholder="New folder name">
          <button type="submit">Create folder</button>
        </form>
        <h3>Upload file</h3>
        <form method="post" action="/browse/upload" enctype="multipart/form-data">
          <input type="hidden" name="parent" value="%s">
          <input type="file" name="file" required>
          <button type="submit">Upload</button>
        </form>
        """ % (html.escape(path), html.escape(path))
    token_permissions = share.get("_client_permissions")
    cli_allowed = bool(share.get("cli_enabled", False)) and (
        token_permissions is None or bool(token_permissions.get("cli", False))
    )
    if cli_allowed:
        sandbox_info = sandbox_runner.sandbox_status()
        if sandbox_info.get("available"):
            terminal_controls = """
            <h3>Run isolated CLI command</h3>
            <form method="post" action="/browse/command">
              <label>Working directory (relative to share)</label>
              <input name="cwd" value="%s" placeholder="src">
              <label>Command (sh/bash inside isolated container)</label>
              <textarea name="command" rows="4" required placeholder="npm test"></textarea>
              <button type="submit">Run command</button>
            </form>
            <p><a href="/browse/terminal?cwd=%s">Open persistent terminal (no JavaScript)</a></p>
            """ % (html.escape(path), quote(path, safe=""))
        else:
            terminal_controls = '<p class="sub">CLI is enabled but unavailable: %s</p>' % html.escape(sandbox_info.get("reason", "Runner unavailable"))
    else:
        terminal_controls = '<p class="sub">CLI is disabled for this share or AI client.</p>'
    body = brand_header() + """
      <h2>Simple browser workspace</h2>
      <p class="sub">No JavaScript required. This page uses ordinary links and HTML forms.</p>
      <p><strong>Current folder:</strong> /%s</p>
      <ul style="line-height:1.9">%s</ul>
      %s
      %s
      <p><a href="/workbench">Open interactive Workbench</a></p>
    """ % (html.escape(path), "".join(rows) or "<li>Empty folder</li>", write_controls, terminal_controls)
    return page("Simple Workspace", body, wide=True)


@app.get("/browse/file", response_class=HTMLResponse)
def browse_nojs_file(path: str, share: dict = Depends(share_auth)):
    require_project_permission(share, path, "read")
    try:
        item = workspace_module.read_text_file(share, path)
        can_write = bool(share.get("workspace_write_enabled", False)) and (
            share.get("_client_permissions") is None or share["_client_permissions"].get("write", False)
        )
        editor = """
        <form method="post" action="/browse/save">
          <input type="hidden" name="path" value="%s">
          <textarea name="content" rows="32" style="width:100%%;font-family:monospace">%s</textarea>
          <button type="submit" %s>Save file</button>
        </form>
        """ % (html.escape(item["path"]), html.escape(item["content"]), "" if can_write else "disabled")
        if not can_write:
            editor = '<pre style="white-space:pre-wrap">%s</pre><p class="sub">Read-only token/share.</p>' % html.escape(item["content"])
        body = brand_header() + """
          <h2>%s</h2>
          <p><a href="/browse?path=%s">Back to folder</a> Â· <a href="/api/workspace/download?path=%s">Download file</a></p>
          %s
        """ % (html.escape(item["path"]), quote(item["path"].rsplit("/", 1)[0] if "/" in item["path"] else "", safe=""),
               quote(item["path"], safe=""), editor)
    except workspace_module.WorkspaceError as exc:
        body = brand_header() + '<h2>Cannot open file</h2><div class="error">%s</div><p><a href="/browse">Back</a></p>' % html.escape(str(exc))
    return page("File Editor", body, wide=True)


@app.post("/browse/save")
def browse_nojs_save(request: Request, path: str = Form(...), content: str = Form(...),
                     share: dict = Depends(share_auth)):
    require_workspace_write(share, path, "write")
    try:
        result = workspace_module.write_text_file(share, path, content)
        audit_event("workspace.write", share, request, result["path"], {"bytes": result["size"]})
        return RedirectResponse(url="/browse/file?path=" + quote(result["path"], safe=""), status_code=303)
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.post("/browse/mkdir")
def browse_nojs_mkdir(request: Request, parent: str = Form(""), name: str = Form(...),
                      share: dict = Depends(share_auth)):
    relative = (parent.strip("/") + "/" + name.strip("/")).strip("/")
    require_workspace_write(share, relative, "write")
    try:
        result = workspace_module.create_directory(share, relative)
        audit_event("workspace.mkdir", share, request, result["path"])
        return RedirectResponse(url="/browse?path=" + quote(parent, safe=""), status_code=303)
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)


@app.post("/browse/upload")
async def browse_nojs_upload(request: Request, parent: str = Form(""), file: UploadFile = File(...),
                             share: dict = Depends(share_auth)):
    try:
        relative = (parent.strip("/") + "/" + Path(file.filename or "upload.bin").name).strip("/")
        require_workspace_write(share, relative, "upload")
        data = await file.read(workspace_module.MAX_UPLOAD_BYTES + 1)
        result = workspace_module.write_binary_file(share, relative, data)
        audit_event("workspace.upload", share, request, relative, {"bytes": result["size"]})
        return RedirectResponse(url="/browse?path=" + quote(parent, safe=""), status_code=303)
    except workspace_module.WorkspaceError as exc:
        workspace_error_response(exc)
    finally:
        await file.close()



@app.post("/browse/command", response_class=HTMLResponse)
async def browse_nojs_command(request: Request, command: str = Form(...), cwd: str = Form(""),
                              share: dict = Depends(share_auth)):
    require_cli_enabled(share, require_runner=True)
    command = command.strip()
    if not command or len(command) > 20000:
        raise HTTPException(status_code=400, detail="Command must be 1-20000 characters.")
    working_dir = resolve_cli_cwd(share, cwd)
    job_id = str(uuid.uuid4())
    with CLI_JOBS_LOCK:
        active = [job for job in CLI_JOBS.values()
                  if job.get("share_id") == share["id"] and job.get("status") == "running"]
        active_global = [job for job in CLI_JOBS.values() if job.get("status") == "running"]
        if len(active) >= 2:
            raise HTTPException(status_code=429, detail="This share already has two running CLI jobs.")
        if len(active_global) >= CLI_MAX_GLOBAL_JOBS:
            raise HTTPException(status_code=429, detail="The server has reached its global CLI job limit.")
        CLI_JOBS[job_id] = {
            "id": job_id, "share_id": share["id"], "command": command,
            "shell": "bash", "cwd": str(working_dir), "status": "running",
            "stdout": "", "stderr": "", "exit_code": None,
            "writeback_enabled": workspace_writeback_allowed(share),
            "started_at": now_iso(), "finished_at": None,
        }
    audit_event("cli.start", share, request, str(working_dir), {"job_id": job_id, "shell": "bash"})
    thread = threading.Thread(target=_run_cli_job, args=(job_id, "bash", command, working_dir), daemon=True)
    thread.start()
    started = time_mod.monotonic()
    while time_mod.monotonic() - started < CLI_MAX_RUNTIME_SECONDS + 15:
        await asyncio.sleep(0.5)
        job = CLI_JOBS.get(job_id, {})
        if job.get("status") != "running":
            break
    job = CLI_JOBS.get(job_id, {})
    body = brand_header() + """
      <h2>Command result</h2>
      <p><strong>Command:</strong> <code>%s</code></p>
      <p><strong>Status:</strong> %s Â· <strong>Exit:</strong> %s</p>
      <h3>Standard output</h3><pre style="white-space:pre-wrap;overflow:auto">%s</pre>
      <h3>Standard error</h3><pre style="white-space:pre-wrap;overflow:auto">%s</pre>
      <p><a href="/browse?path=%s">Return to workspace</a> Â· <a href="/browse">Workspace root</a></p>
    """ % (html.escape(command), html.escape(job.get("status", "unknown")),
           html.escape(str(job.get("exit_code"))), html.escape(job.get("stdout", "")),
           html.escape(job.get("stderr", "")), quote(cwd, safe=""))
    return page("Command Result", body, wide=True)


@app.get("/browse/terminal", response_class=HTMLResponse)
def browse_terminal(session_id: str = "", cwd: str = "",
                    share: dict = Depends(share_auth)):
    require_cli_enabled(share)
    sandbox_info = sandbox_runner.sandbox_status()
    if not sandbox_info.get("available"):
        body = brand_header() + '<h2>Persistent terminal unavailable</h2><p class="sub">%s</p><p><a href="/browse">Back to workspace</a></p>' % html.escape(sandbox_info.get("reason", "Docker unavailable"))
        return page("Persistent terminal", body, wide=True)
    if session_id:
        session = terminal_session_or_404(session_id, share)
        result = TERMINAL_SESSIONS.read(session, 0)
        output_text = "".join(event["data"] for event in result["events"][-50:])
        output_note = '<p class="sub">Older output was trimmed.</p>' if result["truncated"] else ""
        terminal_body = """
        <p><strong>Status:</strong> %s Â· <a href="/browse/terminal?session_id=%s">Refresh output</a></p>
        %s
        <pre style="white-space:pre-wrap;overflow:auto;max-height:55vh;background:#101820;color:#e7edf2;padding:14px;border-radius:8px;">%s</pre>
        <form method="post" action="/browse/terminal/input">
          <input type="hidden" name="session_id" value="%s">
          <label>Shell input (append a newline to run a command)</label>
          <textarea name="data" rows="4" required placeholder="pwd"></textarea>
          <button type="submit">Send input</button>
        </form>
        <form method="post" action="/browse/terminal/close">
          <input type="hidden" name="session_id" value="%s">
          <button type="submit" class="secondary">Close terminal and sync workspace</button>
        </form>
        """ % (html.escape(session.status), quote(session.id, safe=""), output_note,
               html.escape(output_text), html.escape(session.id), html.escape(session.id))
    else:
        safe_cwd = html.escape(cwd)
        terminal_body = """
        <p class="sub">Start a persistent isolated shell. This page works with ordinary browser links and HTML forms; JavaScript is not required.</p>
        <form method="post" action="/browse/terminal/start">
          <label>Working directory (relative to the share)</label>
          <input name="cwd" value="%s" placeholder="src">
          <button type="submit">Start terminal</button>
        </form>
        """ % safe_cwd
    body = brand_header() + "<h2>Persistent isolated terminal</h2>" + terminal_body + '<p><a href="/browse">Back to workspace</a></p>'
    return page("Persistent terminal", body, wide=True)


@app.post("/browse/terminal/start")
def browse_terminal_start(request: Request, cwd: str = Form(""),
                          share: dict = Depends(share_auth)):
    require_cli_enabled(share, require_runner=True)
    working_dir = resolve_cli_cwd(share, cwd)
    try:
        session = TERMINAL_SESSIONS.start(share, working_dir, terminal_owner_id(share))
    except TerminalSessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    audit_event("terminal.open", share, request, str(working_dir), {"session_id": session.id, "source": "nojs"})
    return RedirectResponse(url="/browse/terminal?session_id=" + quote(session.id, safe=""), status_code=303)


@app.post("/browse/terminal/input")
def browse_terminal_input(request: Request, session_id: str = Form(...), data: str = Form(...),
                          share: dict = Depends(share_auth)):
    require_cli_enabled(share)
    session = terminal_session_or_404(session_id, share)
    if not data.endswith("\n"):
        data += "\n"
    try:
        TERMINAL_SESSIONS.write(session, data)
    except TerminalSessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    audit_event("terminal.input", share, request, session_id, {"bytes": len(data.encode("utf-8")), "source": "nojs"})
    return RedirectResponse(url="/browse/terminal?session_id=" + quote(session.id, safe=""), status_code=303)


@app.post("/browse/terminal/close")
def browse_terminal_close(request: Request, session_id: str = Form(...),
                          share: dict = Depends(share_auth)):
    require_cli_enabled(share)
    session = terminal_session_or_404(session_id, share)
    TERMINAL_SESSIONS.close(session, reason="closed by no-JavaScript browser")
    audit_event("terminal.close", share, request, session_id, {"source": "nojs"})
    return RedirectResponse(url="/browse/terminal", status_code=303)


@app.get("/workbench", response_class=HTMLResponse)
def workbench(share: dict = Depends(share_auth)):
    body = brand_header() + r"""
    <style>
      .wb{display:grid;grid-template-columns:minmax(220px,30%) 1fr;gap:14px;margin-top:18px}
      .wb-panel{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:14px;min-width:0}
      .wb-tree{max-height:58vh;overflow:auto;font:13px ui-monospace,monospace}
      .wb-entry{display:block;width:100%;text-align:left;background:transparent;border:0;color:inherit;padding:6px;border-radius:6px;cursor:pointer}
      .wb-entry:hover{background:rgba(255,255,255,.1)}
      .wb-editor{width:100%;min-height:48vh;font:13px ui-monospace,monospace;white-space:pre;tab-size:2}
      .wb-output{white-space:pre-wrap;overflow:auto;max-height:220px;background:#10141d;padding:12px;border-radius:8px;font:12px ui-monospace,monospace}
      .wb-actions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
      .wb-muted{opacity:.7;font-size:12px}
      @media(max-width:760px){.wb{grid-template-columns:1fr}.wb-tree{max-height:30vh}.wb-editor{min-height:36vh}}
    </style>
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap">
      <div><h2 style="margin:8px 0">Remote Workbench</h2><p class="sub">Authenticated browser workspace Â· no MCP required</p></div>
      <span id="wb-status" class="badge offline">Connectingâ€¦</span>
    </div>
    <div class="wb">
      <section class="wb-panel">
        <strong>Project files</strong>
        <div class="wb-actions">
          <button class="secondary small" id="refresh">Refresh</button>
          <button class="secondary small" id="new-file">New file</button>
          <button class="secondary small" id="new-folder">New folder</button>
          <input id="upload-file" type="file" style="max-width:150px;font-size:11px">
          <button class="secondary small" id="upload">Upload</button>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0">
          <input id="tree-search" type="search" placeholder="Filter visible files and foldersâ€¦" aria-label="Filter visible files and folders" style="flex:1;min-width:150px">
          <span id="tree-count" class="wb-muted" aria-live="polite">Loadingâ€¦</span>
        </div>
        <div id="tree-location" class="wb-muted" style="margin:4px 0 8px">Workspace root</div>
        <div id="tree" class="wb-tree">Loading workspaceâ€¦</div>
      </section>
      <section class="wb-panel">
        <div style="display:flex;justify-content:space-between;gap:10px;align-items:center">
          <strong id="file-name">Select a file</strong>
          <button id="download" class="secondary small" disabled>Download</button>
          <button id="save" class="small" disabled>Save changes</button>
        </div>
        <textarea id="editor" class="wb-editor" spellcheck="false" placeholder="Choose a text file from the project treeâ€¦" disabled></textarea>
        <p id="editor-note" class="wb-muted">Files are saved atomically. Credentials and key files are intentionally hidden.</p>
        <div class="wb-actions"><button id="move" class="secondary small" disabled>Move / rename selected</button><button id="delete" class="danger small" disabled>Delete selected</button></div>
        <hr style="opacity:.15;margin:18px 0">
        <strong>Terminal</strong>
        <p id="terminal-note" class="wb-muted">Checking isolated command runnerâ€¦</p>
        <form id="terminal-form">
          <input id="terminal-cwd" placeholder="Working directory (relative to workspace)" value="">
          <textarea id="terminal-command" rows="3" placeholder="Enter a shell command or stdin inputâ€¦" disabled></textarea>
          <div class="wb-actions">
            <button id="terminal-start" type="button" class="secondary small" disabled>Start terminal</button>
            <button id="terminal-run" type="submit" class="small" disabled>Send input</button>
            <button id="terminal-close" type="button" class="danger small" disabled>Close terminal</button>
          </div>
        </form>
        <p class="wb-muted">Persistent line-oriented shell. Full-screen TUI applications are not supported in this terminal mode.</p>
        <div class="wb-actions"><button id="git-status" class="secondary small">Git status</button><button id="git-diff" class="secondary small">Git diff</button><button id="git-branches" class="secondary small">Branches</button><button id="git-log" class="secondary small">Commit history</button></div>
        <hr style="opacity:.15;margin:16px 0">
        <strong>Git change control</strong>
        <p class="wb-muted">Stage only the selected file. Review the staged patch before committing. Push is a separate, explicitly authorised action.</p>
        <div class="wb-actions"><button id="git-stage" class="secondary small" disabled>Stage open file</button><button id="git-stage-selected" class="secondary small" disabled>Stage checked files</button><button id="git-staged" class="secondary small">Review staged changes</button></div>
        <div class="wb-actions"><input id="git-message" maxlength="200" placeholder="Commit message (max 200 characters)"><button id="git-commit" class="small" disabled>Commit staged</button></div>
        <div class="wb-actions"><input id="git-remote" maxlength="64" value="origin" aria-label="Git remote" placeholder="Remote"><input id="git-branch" maxlength="128" placeholder="Push branch (e.g. main)"><button id="git-push" class="danger small" disabled>Push branch</button></div>
        <pre id="terminal-output" class="wb-output">No command has been run.</pre>
      </section>
    </div>
    <script>
    (() => {
      const $ = id => document.getElementById(id);
      let currentDir = "", selectedPath = "", original = "", canWrite = false;
      let visibleEntryCount = 0;
      let gitPermissions = {git_stage:false,git_commit:false,git_push:false};
      const gitSelection = new Set();
      let terminalSessionId = null, terminalCursor = 0, terminalPollActive = false;
      const call = async (url, options={}) => {
        const response = await fetch(url, {credentials:"same-origin", ...options,
          headers:{"Content-Type":"application/json", ...(options.headers||{})}});
        const data = await response.json().catch(()=>({detail:response.statusText}));
        if (!response.ok) throw new Error(data.detail || ("HTTP "+response.status));
        return data;
      };
      const showError = e => { $("wb-status").textContent = e.message; $("wb-status").className="badge offline"; };
      async function status(){
        const s = await call("/api/workspace/status");
        canWrite = !!s.write_enabled;
        gitPermissions = s.git_permissions || gitPermissions;
        $("git-stage").disabled = !gitPermissions.git_stage || !selectedPath;
        $("git-commit").disabled = !gitPermissions.git_commit;
        $("git-push").disabled = !gitPermissions.git_push;
        $("wb-status").textContent = s.write_enabled ? "Workspace connected Â· read/write" : "Workspace connected Â· read only";
        $("wb-status").className="badge online";
        $("editor-note").textContent = s.write_enabled ? "Changes are saved directly to the shared workspace." : "Read-only access. Ask the administrator to enable workspace editing.";
        $("save").disabled = !s.write_enabled;
        $("new-file").disabled = !s.write_enabled; $("new-folder").disabled = !s.write_enabled;
        $("delete").disabled = !s.write_enabled;
        const sandbox = s.sandbox || {};
        $("terminal-note").textContent = sandbox.available && s.cli_enabled
          ? "Isolated Docker runner ready Â· network disabled Â· workspace-only mount."
          : (s.cli_enabled ? sandbox.reason : "CLI access is disabled for this share.") + " Host-shell fallback is never used.";
        $("terminal-command").disabled = !(sandbox.available && s.cli_enabled);
        $("terminal-start").disabled = !(sandbox.available && s.cli_enabled) || !!terminalSessionId;
        $("terminal-run").disabled = !(sandbox.available && s.cli_enabled) || !terminalSessionId;
        $("terminal-close").disabled = !terminalSessionId;
      }
      function applyTreeFilter(){
        const query=$("tree-search").value.trim().toLocaleLowerCase();
        let visible=0;
        for(const row of $("tree").querySelectorAll("[data-search]")){
          const match=!query || row.dataset.search.includes(query);
          row.hidden=!match;
          if(match)visible++;
        }
        $("tree-count").textContent=visible+" / "+visibleEntryCount+" entries";
      }
      async function tree(path=currentDir){
        currentDir = path;
        const data = await call("/api/workspace/tree?path="+encodeURIComponent(path)+"&depth=3");
        const host = $("tree"); host.replaceChildren();
        visibleEntryCount=data.entries.length;
        $("tree-location").textContent=path ? "Workspace / "+path : "Workspace root";
        const up = document.createElement("button"); up.className="wb-entry"; up.textContent="â†°  "+(path ? "Parent folder" : "Workspace root");
        up.onclick=()=>tree(path.includes("/")?path.slice(0,path.lastIndexOf("/")):""); host.append(up);
        for(const item of data.entries){
          const row=document.createElement("div"); row.className="wb-entry"; row.style.display="flex"; row.style.alignItems="center"; row.style.gap="7px";
          row.dataset.search=item.path.toLocaleLowerCase();
          const level=item.path.split("/").length-1; row.style.paddingLeft=(8+level*12)+"px";
          if(item.type==="file" && gitPermissions.git_stage){
            const pick=document.createElement("input"); pick.type="checkbox"; pick.checked=gitSelection.has(item.path); pick.title="Select "+item.path; pick.setAttribute("aria-label","Select "+item.path);
            pick.onchange=()=>{if(pick.checked)gitSelection.add(item.path);else gitSelection.delete(item.path);$("git-stage-selected").disabled=!gitSelection.size;}; row.append(pick);
          }
          const b=document.createElement("button"); b.type="button"; b.className="wb-entry"; b.style.flex="1"; b.style.textAlign="left"; b.style.border="0"; b.style.background="transparent";
          b.textContent=(item.type==="directory"?"ðŸ“ ":"ðŸ“„ ")+item.name; b.title=item.path;
          b.onclick=()=>item.type==="directory"?tree(item.path):openFile(item.path); row.append(b); host.append(row);
        }
        if(data.truncated){const note=document.createElement("div");note.className="wb-muted";note.textContent="Listing truncated at 500 entries.";host.append(note);}
        applyTreeFilter();
      }
      $("tree-search").addEventListener("input",applyTreeFilter);
      async function openFile(path){
        try{
          const d=await call("/api/workspace/file?path="+encodeURIComponent(path));
          selectedPath=d.path; original=d.content; $("editor").value=d.content; $("editor").disabled=false;
          $("file-name").textContent=d.path; $("delete").disabled=!canWrite; $("move").disabled=!canWrite; $("download").disabled=false;
          $("save").disabled=true; $("git-stage").disabled=!gitPermissions.git_stage;
        }catch(e){
          selectedPath=path; $("file-name").textContent=path; $("download").disabled=false;
          $("editor").value=""; $("editor").disabled=true; $("save").disabled=true; $("move").disabled=true; $("delete").disabled=true;
          showError(e);
        }
      }
      $("editor").addEventListener("input",()=>{$("save").disabled=(!canWrite || $("editor").value===original);});
      $("save").onclick=async()=>{
        try{await call("/api/workspace/file",{method:"PUT",body:JSON.stringify({path:selectedPath,content:$("editor").value})});original=$("editor").value;$("save").disabled=true;$("wb-status").textContent="Saved "+selectedPath;}
        catch(e){showError(e);}
      };
      $("download").onclick=()=>{if(selectedPath)window.location.href="/api/workspace/download?path="+encodeURIComponent(selectedPath);};
      $("refresh").onclick=()=>tree(currentDir);
      $("new-file").onclick=async()=>{const name=prompt("New file path (relative to workspace):",currentDir?currentDir+"/":"");if(!name)return;try{await call("/api/workspace/file",{method:"PUT",body:JSON.stringify({path:name,content:""})});await tree(currentDir);await openFile(name);}catch(e){showError(e);}};
      $("new-folder").onclick=async()=>{const name=prompt("New folder path (relative to workspace):",currentDir?currentDir+"/":"");if(!name)return;try{await call("/api/workspace/directory",{method:"POST",body:JSON.stringify({path:name})});await tree(currentDir);}catch(e){showError(e);}};
      $("upload").onclick=async()=>{const file=$("upload-file").files[0];if(!file){alert("Choose a file first.");return;}const form=new FormData();form.append("path",(currentDir?currentDir+"/":"")+file.name);form.append("file",file);try{const response=await fetch("/api/workspace/upload",{method:"POST",credentials:"same-origin",body:form});const data=await response.json();if(!response.ok)throw new Error(data.detail||"Upload failed");$("wb-status").textContent="Uploaded "+data.path;await tree(currentDir);}catch(e){showError(e);}};
      $("git-status").onclick=async()=>{try{const d=await call("/api/workspace/git/status");$("terminal-output").textContent=d.status||"Working tree clean";}catch(e){$("terminal-output").textContent=e.message;}};
      $("git-diff").onclick=async()=>{try{const url="/api/workspace/git/diff"+(selectedPath?"?path="+encodeURIComponent(selectedPath):"");const d=await call(url);$("terminal-output").textContent=d.diff||"No tracked changes.";if(d.truncated)$("terminal-output").textContent+="\n[diff truncated]";}catch(e){$("terminal-output").textContent=e.message;}};
      $("git-branches").onclick=async()=>{try{const d=await call("/api/workspace/git/branches");$("terminal-output").textContent="Current branch: "+(d.current||"(detached HEAD)")+"\n\n"+(d.branches||[]).map(b=>(b.current?"* ":"  ")+b.name+"  "+b.commit+"  "+b.subject).join("\n");if(!d.branches.length)$("terminal-output").textContent+="\nNo branches found.";}catch(e){$("terminal-output").textContent=e.message;}};
      $("git-log").onclick=async()=>{try{const d=await call("/api/workspace/git/log?limit=20");$("terminal-output").textContent=(d.commits||[]).map(c=>c.short_hash+"  "+c.date+"  "+c.author+"\n    "+c.subject).join("\n\n")||"No commits found.";}catch(e){$("terminal-output").textContent=e.message;}};
      async function stagePaths(paths){if(!paths.length||!gitPermissions.git_stage)return;if(!confirm("Stage "+paths.length+" explicitly selected file(s)?\\n\\n"+paths.join("\\n")))return;try{const d=await call("/api/workspace/git/stage",{method:"POST",body:JSON.stringify({paths,confirm:"STAGE"})});for(const path of d.staged||[])gitSelection.delete(path);$("git-stage-selected").disabled=!gitSelection.size;$("terminal-output").textContent="Staged: "+d.staged.join(", ");await showStaged();}catch(e){$("terminal-output").textContent=e.message;}}
      $("git-stage").onclick=()=>stagePaths(selectedPath?[selectedPath]:[]);
      $("git-stage-selected").onclick=()=>stagePaths(Array.from(gitSelection).slice(0,100));
      async function showStaged(){const d=await call("/api/workspace/git/staged");$("terminal-output").textContent="Staged files ("+d.file_count+"):\n"+(d.files||[]).join("\n")+(d.hidden_protected_count?"\n[protected paths omitted: "+d.hidden_protected_count+"]":"")+"\n\n"+(d.diff||"No staged patch.");if(d.truncated)$("terminal-output").textContent+="\n[staged diff truncated at 20 KB]";}
      $("git-staged").onclick=async()=>{try{await showStaged();}catch(e){$("terminal-output").textContent=e.message;}};
      $("git-commit").onclick=async()=>{const message=$("git-message").value.trim();if(!message){alert("Enter a commit message.");return;}if(!gitPermissions.git_commit)return;try{const staged=await call("/api/workspace/git/staged");if(!staged.file_count){$("terminal-output").textContent="No visible staged files to commit.";return;}if(!confirm("Commit "+staged.file_count+" staged file(s) with message:\n\n"+message+"?\nReview the staged patch first."))return;const d=await call("/api/workspace/git/commit",{method:"POST",body:JSON.stringify({message,confirm:"COMMIT"})});$("terminal-output").textContent="Committed "+d.commit+"\n"+d.output;$("git-message").value="";}catch(e){$("terminal-output").textContent=e.message;}};
      $("git-push").onclick=async()=>{const remote=$("git-remote").value.trim(),branch=$("git-branch").value.trim();if(!remote||!branch){alert("Enter both a remote and branch.");return;}if(!gitPermissions.git_push)return;if(!confirm("Push local HEAD to "+remote+" / "+branch+"? This sends commits to the remote repository."))return;try{const d=await call("/api/workspace/git/push",{method:"POST",body:JSON.stringify({remote,branch,confirm:"PUSH"})});$("terminal-output").textContent="Pushed to "+d.remote+"/"+d.branch+"\n"+d.output;}catch(e){$("terminal-output").textContent=e.message;}};
      $("move").onclick=async()=>{
        if(!selectedPath||!canWrite)return;
        if($("editor").value!==original&&!confirm("This file has unsaved editor changes. Move the saved file without those changes?"))return;
        const destination=prompt("New workspace-relative path:",selectedPath);
        if(!destination||destination===selectedPath)return;
        try{
          const d=await call("/api/workspace/move",{method:"POST",body:JSON.stringify({source:selectedPath,destination})});
          selectedPath=d.destination;await tree(currentDir);await openFile(selectedPath);
          $("wb-status").textContent="Moved to "+selectedPath;
        }catch(e){showError(e);}
      };
      $("delete").onclick=async()=>{if(!selectedPath||!confirm("Delete "+selectedPath+"?"))return;try{await call("/api/workspace/path?path="+encodeURIComponent(selectedPath),{method:"DELETE"});selectedPath="";$("editor").value="";$("file-name").textContent="Select a file";$("delete").disabled=true;$("move").disabled=true;await tree(currentDir);}catch(e){showError(e);}};
      async function pollTerminal(sessionId){
        if(terminalPollActive)return;
        terminalPollActive=true;
        try{
          while(terminalSessionId===sessionId){
            const d=await call("/cli/sessions/"+sessionId+"/output?after="+terminalCursor+"&wait=10");
            if(d.truncated)$("terminal-output").textContent+="\n[older output was trimmed]\n";
            for(const event of d.events||[]){$("terminal-output").textContent+=event.data;terminalCursor=event.seq;}
            terminalCursor=Math.max(terminalCursor,d.next||0);
            $("terminal-output").scrollTop=$("terminal-output").scrollHeight;
            if(d.status!=="running"){
              $("terminal-output").textContent+="\n[terminal "+d.status+(d.exit_code===null?"":", exit "+d.exit_code)+"]";
              terminalSessionId=null;status().catch(showError);break;
            }
          }
        }catch(e){
          $("terminal-output").textContent+="\n[terminal connection: "+e.message+"]";
        }finally{terminalPollActive=false;}
      }
      async function startTerminal(){
        if(terminalSessionId)return terminalSessionId;
        const created=await call("/cli/sessions",{method:"POST",body:JSON.stringify({cwd:$("terminal-cwd").value.trim()})});
        terminalSessionId=created.session_id;terminalCursor=0;
        $("terminal-output").textContent="[terminal session "+terminalSessionId+"]\n";
        $("terminal-start").disabled=true;$("terminal-run").disabled=false;$("terminal-close").disabled=false;
        pollTerminal(terminalSessionId);
        return terminalSessionId;
      }
      $("terminal-start").onclick=async()=>{try{await startTerminal();}catch(e){$("terminal-output").textContent=e.message;}};
      $("terminal-form").onsubmit=async e=>{
        e.preventDefault();const input=$("terminal-command").value;if(!input)return;
        try{
          const sessionId=await startTerminal();
          await call("/cli/sessions/"+sessionId+"/input",{method:"POST",body:JSON.stringify({data:input.endsWith("\n")?input:input+"\n"})});
          $("terminal-command").value="";
        }catch(e){$("terminal-output").textContent=e.message;}
      };
      $("terminal-close").onclick=async()=>{
        if(!terminalSessionId)return;
        const sessionId=terminalSessionId;
        try{await call("/cli/sessions/"+sessionId,{method:"DELETE"});}
        catch(e){$("terminal-output").textContent+="\n[close: "+e.message+"]";}
        terminalSessionId=null;terminalPollActive=false;status().catch(showError);
      };
      $("editor").disabled=true;
      Promise.all([status(),tree("")]).catch(showError);
    })();
    </script>
    <p class="wb-muted" style="margin-top:14px">This browser interface is a web client for Sf2AiS. Access is limited to the authenticated share and its configured permissions.</p>
    """
    return page("Remote Workbench", body, wide=True)


# ---------------------------------------------------------------------------
# CLI execution (opt-in, per-share) - lets an AI assistant run shell / PowerShell
# commands for debugging and testing, alongside the read-only file endpoints.
# Off by default; a share must have cli_enabled=True to use these routes.
# ---------------------------------------------------------------------------
import threading

CLI_JOBS = {}
CLI_JOBS_LOCK = threading.Lock()
CLI_MAX_RUNTIME_SECONDS = 600     # hard kill after 10 minutes
CLI_MAX_OUTPUT_CHARS = 200_000    # truncate huge output
CLI_MAX_GLOBAL_JOBS = 4
TERMINAL_SESSIONS = TerminalSessionManager()


def resolve_cli_cwd(share: dict, requested: str) -> Path:
    try:
        candidate = workspace_module.resolve_path(share, requested or "")
    except workspace_module.WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=400, detail="cwd does not exist or is not a directory.")
    return candidate


def workspace_writeback_allowed(share: dict) -> bool:
    if not share.get("workspace_write_enabled", False):
        return False
    permissions = share.get("_client_permissions")
    if permissions is None:
        return True
    access = permissions.get("project_access")
    # Preserve the historical broad-write interpretation for legacy identities
    # that have not yet been migrated to a granular project_access object.
    if not isinstance(access, dict):
        return bool(permissions.get("write", False))
    # The sandbox can write across its mounted workspace; do not expose that
    # broad capability when the identity has any narrower path rules.
    return bool(permissions.get("write", False)) and bool(access.get("write", False)) and not access.get("deny", False) and not access.get("rules")


def require_cli_enabled(share: dict, require_runner: bool = False):
    if not share.get("cli_enabled"):
        raise HTTPException(status_code=403, detail="CLI access is disabled for this share.")
    token_permissions = share.get("_client_permissions")
    if token_permissions is not None and not token_permissions.get("cli", False):
        raise HTTPException(status_code=403, detail="This AI client token does not have CLI permission.")
    if token_permissions is not None:
        access = token_permissions.get("project_access", {})
        if access.get("rules") or access.get("deny") or not all(access.get(key, False) for key in ("read", "write", "upload", "download")):
            raise HTTPException(status_code=403, detail="CLI requires unrestricted read, write, upload and download access to the entire project. Path-specific restrictions cannot be safely applied to shell commands.")
        require_project_permission(share, "", "write")
    if require_runner:
        status_info = sandbox_runner.sandbox_status()
        if not status_info.get("available"):
            raise HTTPException(status_code=503, detail=status_info.get("reason", "A secure command runner is unavailable."))


def _run_cli_job(job_id: str, shell: str, command: str, cwd: Path):
    job = CLI_JOBS[job_id]
    share = next((item for item in (load_config() or {}).get("shares", [])
                  if item.get("id") == job.get("share_id")), None)
    if not share:
        job["status"] = "failed"
        job["stderr"] = "Share no longer exists."
        job["finished_at"] = now_iso()
        return
    if shell not in ("auto", "bash", "sh"):
        job["status"] = "failed"
        job["stderr"] = "The isolated Docker runner currently supports sh/bash only."
        job["finished_at"] = now_iso()
        return
    try:
        result = sandbox_runner.run_sandboxed(
            share, command, cwd, CLI_MAX_RUNTIME_SECONDS,
            shell="bash" if shell == "bash" else "sh",
            sync_changes=bool(job.get("writeback_enabled", False)),
        )
        job.update(result)
    except Exception as exc:
        job["status"] = "failed"
        job["stderr"] = str(exc)
        job["exit_code"] = None
    job["stdout"] = (job.get("stdout") or "")[:CLI_MAX_OUTPUT_CHARS]
    job["stderr"] = (job.get("stderr") or "")[:CLI_MAX_OUTPUT_CHARS]
    job["finished_at"] = now_iso()
    audit_event("cli.finish", share, path=job.get("cwd", ""), detail={
        "job_id": job_id, "status": job["status"], "exit_code": job.get("exit_code"),
        "workspace_sync": job.get("workspace_sync", "not-run"),
        "writeback_enabled": job.get("writeback_enabled", False),
    })


@app.post("/cli/jobs")
async def cli_create_job(request: Request, share: dict = Depends(share_auth)):
    require_cli_enabled(share, require_runner=True)
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    command_value = data.get("command")
    if not isinstance(command_value, str):
        raise HTTPException(status_code=400, detail="'command' must be a string.")
    command = command_value.strip()
    if not command:
        raise HTTPException(status_code=400, detail="'command' is required.")
    if len(command) > 20000:
        raise HTTPException(status_code=413, detail="Command exceeds the 20,000 character limit.")
    shell = data.get("shell") or share.get("cli_shell") or "auto"
    if not isinstance(shell, str) or shell not in ("auto", "bash", "sh"):
        raise HTTPException(status_code=400, detail="Only the isolated sh/bash runner is supported.")
    requested_cwd = data.get("cwd") or ""
    if not isinstance(requested_cwd, str) or len(requested_cwd) > 500:
        raise HTTPException(status_code=400, detail="cwd must be a relative path of at most 500 characters.")
    cwd = resolve_cli_cwd(share, requested_cwd)

    job_id = str(uuid.uuid4())
    with CLI_JOBS_LOCK:
        cutoff = datetime.now(timezone.utc).timestamp() - 86400
        for old_id, old_job in list(CLI_JOBS.items()):
            finished = old_job.get("finished_at")
            if finished:
                try:
                    if datetime.fromisoformat(finished).timestamp() < cutoff:
                        CLI_JOBS.pop(old_id, None)
                except ValueError:
                    pass
        active = [j for j in CLI_JOBS.values() if j["share_id"] == share["id"] and j["status"] == "running"]
        active_global = [j for j in CLI_JOBS.values() if j["status"] == "running"]
        if len(active) >= 2:
            raise HTTPException(status_code=429, detail="This share already has two running CLI jobs.")
        if len(active_global) >= CLI_MAX_GLOBAL_JOBS:
            raise HTTPException(status_code=429, detail="The server has reached its global CLI job limit.")
        CLI_JOBS[job_id] = {
            "id": job_id, "share_id": share["id"], "command": command,
            "shell": shell, "cwd": str(cwd), "status": "running",
            "stdout": "", "stderr": "", "exit_code": None,
            "writeback_enabled": workspace_writeback_allowed(share),
            "started_at": now_iso(), "finished_at": None,
        }
    thread = threading.Thread(target=_run_cli_job, args=(job_id, shell, command, cwd), daemon=True)
    thread.start()
    audit_event("cli.start", share, request, str(cwd), {
        "job_id": job_id, "shell": shell,
        "writeback_enabled": CLI_JOBS[job_id]["writeback_enabled"],
    })
    return JSONResponse({"job_id": job_id, "status": "running"})


@app.get("/cli/jobs/{job_id}")
def cli_get_job(job_id: str, share: dict = Depends(share_auth)):
    require_cli_enabled(share)
    job = CLI_JOBS.get(job_id)
    if not job or job["share_id"] != share["id"]:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JSONResponse(job)


@app.get("/cli/jobs")
def cli_list_jobs(share: dict = Depends(share_auth)):
    require_cli_enabled(share)
    jobs = [j for j in CLI_JOBS.values() if j["share_id"] == share["id"]]
    jobs.sort(key=lambda j: j["started_at"], reverse=True)
    return JSONResponse({"jobs": jobs[:50]})


def terminal_owner_id(share: dict) -> str:
    client_id = share.get("_client_id")
    return "client:" + str(client_id) if client_id else "basic:" + str(share["id"])


def terminal_session_or_404(session_id: str, share: dict):
    try:
        return TERMINAL_SESSIONS.get(session_id, share["id"], terminal_owner_id(share))
    except TerminalSessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.post("/cli/sessions", status_code=201)
async def cli_create_session(request: Request, share: dict = Depends(share_auth)):
    require_cli_enabled(share, require_runner=True)
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    requested_cwd = data.get("cwd") or ""
    if not isinstance(requested_cwd, str) or len(requested_cwd) > 500:
        raise HTTPException(status_code=400, detail="cwd must be a relative path of at most 500 characters.")
    cwd = resolve_cli_cwd(share, requested_cwd)
    try:
        session = TERMINAL_SESSIONS.start(share, cwd, terminal_owner_id(share))
    except TerminalSessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    audit_event("terminal.open", share, request, str(cwd), {"session_id": session.id})
    return JSONResponse({"session_id": session.id, "status": session.status,
                         "shell": "sh", "mode": "line-oriented"}, status_code=201)


@app.post("/cli/sessions/{session_id}/input")
async def cli_session_input(session_id: str, request: Request, share: dict = Depends(share_auth)):
    require_cli_enabled(share)
    session = terminal_session_or_404(session_id, share)
    data = await request.json()
    if not isinstance(data, dict) or not isinstance(data.get("data"), str):
        raise HTTPException(status_code=400, detail="Request body must contain a string 'data' field.")
    try:
        TERMINAL_SESSIONS.write(session, data["data"])
    except TerminalSessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    audit_event("terminal.input", share, request, session_id,
                {"bytes": len(data["data"].encode("utf-8"))})
    return {"accepted": True}


@app.get("/cli/sessions/{session_id}/output")
async def cli_session_output(session_id: str, after: int = 0, wait: float = 0,
                             share: dict = Depends(share_auth)):
    require_cli_enabled(share)
    session = terminal_session_or_404(session_id, share)
    wait_seconds = max(0.0, min(float(wait), 15.0))
    deadline = time_mod.monotonic() + wait_seconds
    while True:
        try:
            result = TERMINAL_SESSIONS.read(session, after)
        except TerminalSessionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        if result["events"] or result["status"] != "running" or time_mod.monotonic() >= deadline:
            return JSONResponse(result)
        await asyncio.sleep(0.25)


@app.delete("/cli/sessions/{session_id}")
def cli_close_session(session_id: str, request: Request, share: dict = Depends(share_auth)):
    require_cli_enabled(share)
    session = terminal_session_or_404(session_id, share)
    TERMINAL_SESSIONS.close(session, reason="closed by client")
    audit_event("terminal.close", share, request, session_id)
    return {"status": session.status, "exit_code": session.exit_code}


# ---------------------------------------------------------------------------
# Temporary debug tunnels (UPnP IGD port forwarding) - opt-in, per-share.
# Lets an AI expose a local dev server (e.g. localhost:5173) to the public
# internet for a short, bounded window to visually check work in progress.
# Requires the router to support UPnP IGD; fails clearly if it doesn't
# (common on CGNAT connections, where there's no public IP to forward on
# the router in the first place).
# ---------------------------------------------------------------------------
import time as time_mod
import xml.etree.ElementTree as ET
import http.client
import urllib.request as _urllib_request
from urllib.parse import urlparse

TUNNELS = {}
TUNNELS_LOCK = threading.Lock()
TUNNEL_MAX_TTL_SECONDS = 7200      # hard cap: 2 hours
TUNNEL_DEFAULT_TTL_SECONDS = 1800  # default: 30 min
TUNNEL_MAX_ACTIVE_PER_SHARE = 3
SSDP_TIMEOUT = 3


def upnp_discover():
    """Multicast SSDP search for an Internet Gateway Device. Returns
    (control_url, service_type) or raises RuntimeError with a clear reason."""
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        "MAN: \"ssdp:discover\"\r\n"
        "MX: 2\r\n"
        "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n"
    ).encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(SSDP_TIMEOUT)
    sock.sendto(msg, ("239.255.255.250", 1900))
    location = None
    try:
        while True:
            data, _ = sock.recvfrom(65507)
            text = data.decode(errors="ignore")
            for line in text.split("\r\n"):
                if line.lower().startswith("location:"):
                    location = line.split(":", 1)[1].strip()
                    break
            if location:
                break
    except socket.timeout:
        pass
    finally:
        sock.close()

    if not location:
        raise RuntimeError("No UPnP gateway responded. Your router may not support UPnP, "
                            "may have it disabled, or you may be behind CGNAT with no public IP.")

    parsed = urlparse(location)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=SSDP_TIMEOUT)
    conn.request("GET", parsed.path or "/")
    resp = conn.getresponse()
    desc_xml = resp.read()
    conn.close()

    root = ET.fromstring(desc_xml)
    control_url = None
    service_type = None
    for service in root.iter():
        tag = service.tag.rsplit("}", 1)[-1]
        if tag != "service":
            continue
        st, cu = "", ""
        for child in service:
            ctag = child.tag.rsplit("}", 1)[-1]
            if ctag == "serviceType":
                st = child.text or ""
            elif ctag == "controlURL":
                cu = child.text or ""
        if "WANIPConnection" in st or "WANPPPConnection" in st:
            control_url, service_type = cu, st
            break

    if not control_url:
        raise RuntimeError("Router responded but exposed no WANIPConnection/WANPPPConnection service.")

    base = "%s://%s:%s" % (parsed.scheme, parsed.hostname, parsed.port or 80)
    if not control_url.startswith("http"):
        control_url = base + ("" if control_url.startswith("/") else "/") + control_url
    return control_url, service_type


def upnp_soap_call(control_url: str, service_type: str, action: str, args: dict) -> str:
    parsed = urlparse(control_url)
    args_xml = "".join("<%s>%s</%s>" % (k, v, k) for k, v in args.items())
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body><u:%s xmlns:u="%s">%s</u:%s></s:Body></s:Envelope>'
    ) % (action, service_type, args_xml, action)

    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=SSDP_TIMEOUT)
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": '"%s#%s"' % (service_type, action),
    }
    conn.request("POST", parsed.path, body=body, headers=headers)
    resp = conn.getresponse()
    result = resp.read().decode(errors="ignore")
    conn.close()
    if resp.status >= 300:
        raise RuntimeError("Router rejected %s: HTTP %d - %s" % (action, resp.status, result[:300]))
    return result


def local_outbound_ip() -> str:
    try:
        probe_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe_sock.connect(("8.8.8.8", 80))
        ip = probe_sock.getsockname()[0]
        probe_sock.close()
        return ip
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def upnp_add_port_mapping(external_port: int, internal_port: int, protocol: str, description: str,
                           ttl_seconds: int, override_internal_ip: str = None):
    control_url, service_type = upnp_discover()
    local_ip = override_internal_ip or local_outbound_ip()
    upnp_soap_call(control_url, service_type, "AddPortMapping", {
        "NewRemoteHost": "",
        "NewExternalPort": external_port,
        "NewProtocol": protocol,
        "NewInternalPort": internal_port,
        "NewInternalClient": local_ip,
        "NewEnabled": "1",
        "NewPortMappingDescription": description,
        "NewLeaseDuration": ttl_seconds,
    })
    return control_url, service_type, local_ip


def upnp_delete_port_mapping(control_url: str, service_type: str, external_port: int, protocol: str):
    upnp_soap_call(control_url, service_type, "DeletePortMapping", {
        "NewRemoteHost": "",
        "NewExternalPort": external_port,
        "NewProtocol": protocol,
    })


def get_public_ip_quick() -> str:
    try:
        with _urllib_request.urlopen("https://api.ipify.org", timeout=5) as r:
            return r.read().decode().strip()
    except Exception:
        return ""


def resolve_public_host(config) -> str:
    """Reuse whatever public-address source is already configured for the
    gateway itself (domain/static value, or the IP probe's last report),
    instead of making a fresh external lookup."""
    network = config.get("network", {})
    method = network.get("method")
    if method in ("domain", "ddns", "static"):
        return network.get("value") or ""
    if method == "probe":
        return network.get("last_public_ip") or ""
    return ""


def verify_tunnel_reachable(host: str, port: int, protocol: str, timeout: float = 4.0):
    """Best-effort connect-back test. Only meaningful for TCP, and only as a
    positive signal - a failure here doesn't always mean the port is actually
    unreachable from the real internet, since many routers don't support NAT
    hairpinning (connecting to your own public IP from inside the LAN)."""
    if protocol != "TCP":
        return None, "Reachability verification only supports TCP."
    if not host:
        return False, "No public IP available to verify against yet (probe hasn't checked in, or network method isn't configured)."
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "Connected successfully to %s:%s." % (host, port)
    except Exception as e:
        return False, ("Could not connect to %s:%s (%s). Note: some routers block NAT hairpinning, "
                       "so this can fail even when the port is reachable from outside your network - "
                       "if unsure, confirm with an external port checker.") % (host, port, str(e))


def _close_tunnel(tunnel_id: str, reason: str):
    with TUNNELS_LOCK:
        t = TUNNELS.get(tunnel_id)
        if not t or t["status"] != "open":
            return
        t["status"] = "closed"
        t["closed_reason"] = reason
    try:
        upnp_delete_port_mapping(t["control_url"], t["service_type"], t["external_port"], t["protocol"])
    except Exception as e:
        t["close_error"] = str(e)
    if t.get("isolate"):
        stop_event = t.get("relay_stop_event")
        if stop_event is not None:
            try:
                stop_event.set()
            except Exception as e:
                t["relay_cleanup_error"] = str(e)
        try:
            micro_firewall.remove_firewall_rules(t["fw_prefix"])
        except Exception as e:
            t["fw_cleanup_error"] = str(e)
        try:
            micro_firewall.remove_alias_ip(t["nte_context"])
        except Exception as e:
            t["ip_cleanup_error"] = str(e)


def _public_tunnel_view(t: dict) -> dict:
    return {k: v for k, v in t.items() if k not in ("relay_stop_event", "nte_context")}


def _tunnel_expiry_watcher(tunnel_id: str, ttl_seconds: int):
    time_mod.sleep(ttl_seconds)
    with TUNNELS_LOCK:
        t = TUNNELS.get(tunnel_id)
    if t and t["status"] == "open":
        _close_tunnel(tunnel_id, reason="expired")


def require_tunnel_enabled(share: dict):
    if not share.get("tunnel_enabled"):
        raise HTTPException(status_code=403, detail="Temporary tunnels are disabled for this share.")
    token_permissions = share.get("_client_permissions")
    if token_permissions is not None and not token_permissions.get("tunnel", False):
        raise HTTPException(status_code=403, detail="This AI client token does not have tunnel permission.")


@app.get("/tunnel/interfaces")
def tunnel_interfaces(share: dict = Depends(share_auth)):
    require_tunnel_enabled(share)
    if not MICRO_FIREWALL_AVAILABLE:
        return JSONResponse({
            "supported": False, "interfaces": [],
            "reason": "Isolation mode requires Windows with pywin32 installed.",
        })
    try:
        return JSONResponse({"supported": True, "interfaces": micro_firewall.list_interfaces()})
    except Exception as e:
        return JSONResponse({"supported": False, "interfaces": [], "reason": str(e)})


@app.post("/tunnel/open")
async def tunnel_open(request: Request, share: dict = Depends(share_auth)):
    require_tunnel_enabled(share)
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
    try:
        local_port = int(data.get("local_port", 0))
        external_port = int(data.get("external_port") or local_port)
        ttl_seconds = max(60, min(int(data.get("ttl_seconds") or TUNNEL_DEFAULT_TTL_SECONDS), TUNNEL_MAX_TTL_SECONDS))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Ports and TTL must be integers.")
    if not (1 <= local_port <= 65535):
        raise HTTPException(status_code=400, detail="local_port must be 1-65535.")
    if not (1 <= external_port <= 65535):
        raise HTTPException(status_code=400, detail="external_port must be 1-65535.")
    protocol_value = data.get("protocol") or "TCP"
    if not isinstance(protocol_value, str) or protocol_value.upper() != "TCP":
        raise HTTPException(status_code=400, detail="Only TCP tunnels are supported in isolated mode.")
    protocol = "TCP"
    isolate = data.get("isolate", False)
    if isolate is not True:
        raise HTTPException(status_code=403, detail="Direct UPnP forwarding is disabled. Use isolated mode (isolate=true) with an explicit trusted remote allowlist.")
    remote_values = data.get("trusted_remotes")
    if not isinstance(remote_values, list) or not remote_values or not all(isinstance(item, str) for item in remote_values):
        raise HTTPException(status_code=400, detail="trusted_remotes must be a non-empty list of IP addresses/CIDRs.")
    trusted_remotes = []
    for remote_value in remote_values:
        try:
            remote_network = ipaddress.ip_network(remote_value.strip(), strict=False)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid trusted remote IP/CIDR.")
        if remote_network.version != 4:
            raise HTTPException(status_code=400, detail="The current isolated tunnel relay supports IPv4 allowlists only.")
        if remote_network.prefixlen == 0 or remote_network.is_multicast or remote_network.is_unspecified:
            raise HTTPException(status_code=400, detail="Trusted remote ranges must not be wildcard, multicast or unspecified.")
        trusted_remotes.append(str(remote_network))
    if len(set(trusted_remotes)) > 32:
        raise HTTPException(status_code=400, detail="At most 32 trusted remote ranges may be configured.")

    with TUNNELS_LOCK:
        active_for_share = [item for item in TUNNELS.values()
                            if item.get("share_id") == share["id"] and item.get("status") == "open"]
        if len(active_for_share) >= TUNNEL_MAX_ACTIVE_PER_SHARE:
            raise HTTPException(status_code=429, detail="This share already has the maximum number of active tunnels.")

    tunnel_id = str(uuid.uuid4())
    alias_ip = None
    nte_context = None
    fw_prefix = None
    relay_stop_event = None
    forward_target_ip = None
    mapped_port = local_port

    if isolate:
        if not MICRO_FIREWALL_AVAILABLE:
            raise HTTPException(status_code=400,
                                 detail="Isolation mode requires Windows with pywin32 installed.")
        if protocol != "TCP":
            raise HTTPException(status_code=400, detail="Isolation mode currently only supports TCP.")
        alias_value = data.get("alias_ip")
        try:
            alias_ip = str(ipaddress.IPv4Address(alias_value))
            if_index = int(data.get("interface_index"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="alias_ip must be IPv4 and interface_index must be an integer.")
        alias_address = ipaddress.IPv4Address(alias_ip)
        if not alias_address.is_private or alias_address.is_loopback or alias_address.is_multicast or alias_address.is_unspecified or alias_address.is_reserved:
            raise HTTPException(status_code=400, detail="alias_ip must be a usable private unicast IPv4 address.")
        if not 1 <= if_index <= 65535:
            raise HTTPException(status_code=400, detail="interface_index is out of range.")
        fw_prefix = "Sf2AiS_%s" % tunnel_id[:8]
        try:
            nte_context = micro_firewall.add_alias_ip(alias_ip, int(if_index))
            micro_firewall.add_firewall_rules(fw_prefix, alias_ip, external_port, trusted_remotes)
        except Exception as e:
            try:
                micro_firewall.remove_firewall_rules(fw_prefix)
            except Exception:
                pass
            if nte_context is not None:
                try:
                    micro_firewall.remove_alias_ip(nte_context)
                except Exception:
                    pass
            raise HTTPException(status_code=500, detail="Isolation setup failed: %s" % str(e))

        relay_stop_event = threading.Event()
        relay_thread = threading.Thread(
            target=micro_firewall.start_relay,
            args=(alias_ip, external_port, local_port, trusted_remotes, relay_stop_event),
            daemon=True,
        )
        relay_thread.start()
        forward_target_ip = alias_ip
        mapped_port = external_port

    try:
        control_url, service_type, local_ip = upnp_add_port_mapping(
            external_port, mapped_port, protocol,
            "Sf2AiS debug tunnel (%s)" % share["username"], ttl_seconds,
            override_internal_ip=forward_target_ip,
        )
    except Exception as e:
        if isolate:
            relay_stop_event.set()
            try:
                micro_firewall.remove_firewall_rules(fw_prefix)
            except Exception:
                pass
            try:
                micro_firewall.remove_alias_ip(nte_context)
            except Exception:
                pass
        raise HTTPException(status_code=502, detail="Couldn't open tunnel via UPnP: %s" % str(e))

    config = load_config()
    public_host = resolve_public_host(config) or get_public_ip_quick()
    public_url = "http://%s:%s" % (public_host, external_port) if public_host else None

    verify_result = None
    if data.get("verify"):
        ok, msg = verify_tunnel_reachable(public_host, external_port, protocol)
        verify_result = {"reachable": ok, "message": msg}

    with TUNNELS_LOCK:
        TUNNELS[tunnel_id] = {
            "id": tunnel_id, "share_id": share["id"], "local_port": local_port,
            "external_port": external_port, "protocol": protocol,
            "control_url": control_url, "service_type": service_type,
            "status": "open", "opened_at": now_iso(), "public_url": public_url,
            "verify_result": verify_result,
            "isolate": isolate, "alias_ip": alias_ip, "trusted_remotes": trusted_remotes,
            "nte_context": nte_context, "fw_prefix": fw_prefix,
            "relay_stop_event": relay_stop_event,
        }

    watcher = threading.Thread(target=_tunnel_expiry_watcher, args=(tunnel_id, ttl_seconds), daemon=True)
    watcher.start()

    audit_event("tunnel.open", share, request, str(local_port), {
        "tunnel_id": tunnel_id, "external_port": external_port,
        "ttl_seconds": ttl_seconds, "trusted_remotes": trusted_remotes,
    })
    return JSONResponse({
        "tunnel_id": tunnel_id,
        "public_url": public_url,
        "external_port": external_port,
        "expires_in_seconds": ttl_seconds,
        "verify_result": verify_result,
        "isolated": isolate,
    })


@app.post("/tunnel/{tunnel_id}/close")
def tunnel_close(tunnel_id: str, request: Request, share: dict = Depends(share_auth)):
    require_tunnel_enabled(share)
    t = TUNNELS.get(tunnel_id)
    if not t or t["share_id"] != share["id"]:
        raise HTTPException(status_code=404, detail="Tunnel not found.")
    _close_tunnel(tunnel_id, reason="closed by request")
    audit_event("tunnel.close", share, request, str(t.get("external_port", "")), {"tunnel_id": tunnel_id})
    return JSONResponse({"status": "closed"})


@app.get("/tunnel")
def tunnel_list(share: dict = Depends(share_auth)):
    require_tunnel_enabled(share)
    tunnels = [_public_tunnel_view(t) for t in TUNNELS.values() if t["share_id"] == share["id"]]
    return JSONResponse({"tunnels": tunnels})


# ---------------------------------------------------------------------------
# Secure File serving (per-share) - Patched v1.0
# ---------------------------------------------------------------------------
@app.get("/files", response_class=HTMLResponse)
def list_files(share: dict = Depends(share_auth)):
    require_project_permission(share, "", "read")
    # Safely cast and isolate root directory tracking elements using pathlib
    folder_path = Path(share["folder"]).resolve()
    
    try:
        # Enforce strict path iteration rather than raw os.listdir sequences
        files = sorted([f for f in folder_path.iterdir() if f.is_file()])
    except Exception as e:
        # Escape exception details to prevent error-based XSS injection vulnerabilities
        safe_error = html.escape(str(e))
        return HTMLResponse(content=f"<html><body><h3>Error reading directory: {safe_error}</h3></body></html>", status_code=500)
    
    links = ""
    for file in files:
        # Prevent listing hidden system configuration files or paths the identity cannot read.
        if file.name.startswith('.'):
            continue
        if share.get("_client_permissions") is not None and not project_access_module.is_allowed(share["_client_permissions"], file.name, "read"):
            continue
            
        # Escape parameters before injection into the HTML template string
        safe_name = html.escape(file.name)
        links += f'<li><a href="/files/download/{safe_name}">{safe_name}</a></li>\n'
        
    if not links:
        links = "<li><em>No assets available in this directory stream.</em></li>"
        
    safe_user = html.escape(share['username'])
    body = brand_header() + f"""
    <h2>Secure AI Extraction Terminal</h2>
    <p class="sub">Authenticated Profile: <strong>{safe_user}</strong></p>
    <ul style="line-height: 1.8;">{links}</ul>
    """
    return page("File Index", body)

@app.get("/files/download/{filename}")
def download_file(filename: str, share: dict = Depends(share_auth)):
    require_project_permission(share, filename, "download")
    base_dir = Path(share["folder"]).resolve()
    
    # Security Rule 1: Strip out directory separators to isolate the absolute base string
    clean_filename = Path(filename).name
    if clean_filename.startswith(".") or workspace_module.is_protected_path(clean_filename):
        raise HTTPException(status_code=403, detail="This file is protected from share downloads.")
    
    # Security Rule 2: Force resolution under a combined absolute anchor check
    target_path = (base_dir / clean_filename).resolve()
    
    # Security Rule 3: Validate boundaries to block path traversal manipulation attacks
    if not target_path.is_relative_to(base_dir):
        raise HTTPException(status_code=403, detail="Security violation: Out of boundary file request.")
        
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="The requested document file does not exist.")
        
    media_type, _ = guess_type(str(target_path))
    return FileResponse(
        path=target_path, 
        media_type=media_type or "application/octet-stream", 
        filename=target_path.name
    )

# ============================================================================
# Universal gateway — connection authorization, initialization protocol,
# capability registry, file locking, and live multi-session monitoring.
# Extends main:app; never replaces existing functionality.
# ============================================================================

# ---------------------------------------------------------------------------
# Defaults and state helpers (merged into data/config.json)
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "connection_mode": "both",
    "max_connections": 10,
    "max_ai_connections": 5,
    "max_human_connections": 3,
    "max_sessions_per_identity": 3,
    "max_sessions_per_workspace": 5,
    "connection_queue_enabled": True,
    "session_timeout_seconds": 3600,
    "idle_timeout_seconds": 900,
    "authentication_policy": "biometric",
    "blacklist_enabled": True,
    "recent_edit_warning_seconds": 120,
    "file_lock_ttl_seconds": 300,
    "emergency_locked": False,
}

_COMPONENT_VERSIONS = {"sf2ais_law": "1.0.0", "connection_protocol": "1.0.0"}


def _ensure_state(config):
    if not isinstance(config, dict):
        config = {}
    settings = config.setdefault("settings", {})
    if not isinstance(settings, dict):
        settings = config["settings"] = {}
    for k, v in DEFAULT_SETTINGS.items():
        settings.setdefault(k, v)
    defaults = {
        "connections": [], "sessions": {}, "file_locks": {}, "blacklist": [],
        "skill_registry": [], "tool_registry": [],
        "component_versions": _COMPONENT_VERSIONS,
    }
    for k, v in defaults.items():
        if k not in config:
            config[k] = v
    return config


def _load_state():
    return _ensure_state(load_config() or {})


def _save_state(config):
    save_config(config)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _make_id():
    return secrets.token_urlsafe(12)


# ---------------------------------------------------------------------------
# Universal gateway — connection authorization lifecycle
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _connection_request_schema():
    return {
        "client_type": "ai",                      # ai | human
        "client_app": "ChatGPT",
        "client_version": "4.0.0",
        "identity": "ChatGPT US East",
        "identity_verified": False,
        "client_credential": None,
        "capabilities": [],
        "workspace": None,
        "purpose": "",
        "duration_seconds": 3600,
    }


def _create_connection_request(data, requester):
    config = _load_state()
    req = dict(data or {})
    for k, v in _connection_request_schema().items():
        req.setdefault(k, v)
    if isinstance(req.get("capabilities"), list):
        req["capabilities"] = [str(c) for c in req["capabilities"]]
    else:
        req["capabilities"] = []
    if isinstance(req.get("workspace"), dict):
        req["workspace"] = req["workspace"]
    else:
        req["workspace"] = {}
    req["id"] = _make_id()
    req["requester"] = requester or "unknown"
    req["status"] = "pending"
    req["verified"] = bool(req.get("identity_verified"))
    req["created_at"] = _now_iso()
    if req.get("duration_seconds") and req["duration_seconds"] > 0:
        # conns explicitly request a lifetime in seconds; store the absolute expiry.
        duration = max(1, int(req["duration_seconds"]))
        req["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=duration)).isoformat()
    else:
        # No duration (or zero) => session does not expire by duration.
        req["expires_at"] = None
    config["connections"].append(req)
    _save_state(config)
    return req


def _cleanup_expired_connections(config, now):
    kept = []
    for c in config.get("connections", []):
        try:
            exp = datetime.fromisoformat(c.get("expires_at", "1970-01-01T00:00:00+00:00"))
        except (ValueError, TypeError):
            exp = datetime.min.replace(tzinfo=timezone.utc)
        if exp >= now:
            kept.append(c)
        else:
            audit_event("connection.expired", None, None, path="/api/connections", detail={"connection_id": c.get("id")})
    config["connections"] = kept


def _is_blacklisted(config, client_id):
    for b in config.get("blacklist", []):
        if b.get("client_id") == client_id:
            return True
    return False


@app.post("/api/connections", status_code=201)
async def create_connection_request(request: Request, admin: str = Depends(admin_auth)):
    data = await request.json()
    req = _create_connection_request(data, requester="admin")
    audit_event("connection.requested", None, request, path="/api/connections", detail=req)
    return JSONResponse({"connection": req}, status_code=201)


@app.get("/api/connections")
async def list_connections(admin: str = Depends(admin_auth), status_filter: str | None = None):
    config = _load_state()
    _cleanup_expired_connections(config, datetime.now(timezone.utc))
    conns = config.get("connections", [])
    if status_filter:
        conns = [c for c in conns if c.get("status") == status_filter]
    return JSONResponse({"connections": conns})


@app.get("/api/realtime/access")
async def realtime_access_overview(admin: str = Depends(admin_auth)):
    """Return all realtime AI access overview: active sessions, approved connections, pending requests."""
    config = _load_state()
    _cleanup_expired_connections(config, datetime.now(timezone.utc))

    sessions = config.get("sessions", {})

    active_sessions = []
    for sid, sess in sessions.items():
        if sess.get("status") == "running":
            active_sessions.append({
                "session_id": sid,
                "share_id": sess.get("share_id"),
                "share_name": sess.get("share_name", ""),
                "owner": sess.get("owner", ""),
                "started_at": sess.get("started_at"),
                "last_activity": sess.get("last_activity"),
                "mode": sess.get("mode", "line-oriented"),
            })

    approved = [c for c in config.get("connections", []) if c.get("status") == "approved"]
    pending = [c for c in config.get("connections", []) if c.get("status") == "pending"]
    denied = [c for c in config.get("connections", []) if c.get("status") == "denied"]

    # AI/client registry from shares
    ai_clients = []
    for share in config.get("shares", []):
        for client in share.get("clients", []):
            ai_clients.append({
                "client_id": client.get("id"),
                "client_name": client.get("name", "Unknown AI"),
                "share_id": share.get("id"),
                "share_name": share.get("username", ""),
                "permissions": client.get("permissions", {}),
                "created_at": client.get("created_at"),
                "last_seen": client.get("last_seen"),
            })

    return JSONResponse({
        "active_sessions": active_sessions,
        "approved_connections": approved,
        "pending_requests": pending,
        "denied_requests": denied,
        "ai_clients": ai_clients,
        "total_connections": len(approved) + len(pending) + len(denied),
        "active_sessions_count": len(active_sessions),
        "active_clients": len(ai_clients),
    })


# ---------------------------------------------------------------------------
# Universal gateway — safe connection discovery (machine-readable manifest)
# NOTE: This route MUST be registered before /api/connections/{connection_id}
# so that "discover" is not captured as a connection_id path parameter.
# ---------------------------------------------------------------------------

@app.get("/api/connections/discover", response_class=HTMLResponse)
async def connection_discovery(request: Request, admin: str = Depends(admin_auth)):
    config = _load_state()
    manifest = {
        "protocol": "sf2ais.connection-discover/1.0.0",
        "service": "SF2AiS Universal Gateway",
        "version": "1.0.0",
        "connection_mode": config.get("settings", {}).get("connection_mode", "both"),
        "authentication_policy": config.get("settings", {}).get("authentication_policy", "biometric"),
        "max_connections": config.get("settings", {}).get("max_connections"),
        "machine": {
            "name": socket.gethostname(),
            "os": platform.platform(),
            "arch": platform.machine(),
        },
        "endpoints": {
            "connections": "/api/connections",
            "connection_detail": "/api/connections/{id}",
            "sessions": "/api/sessions",
            "session_ack": "/api/sessions/{session_id}/ack",
            "capabilities": "/api/capabilities",
            "capabilities_tools": "/api/capabilities/tools",
            "capabilities_skills": "/api/capabilities/skills",
            "capabilities_workspaces": "/api/capabilities/workspaces",
            "capabilities_access_types": "/api/capabilities/access-types",
            "capabilities_system": "/api/capabilities/system",
            "monitor_sessions": "/api/monitor/sessions",
            "monitor_events": "/api/monitor/events",
            "files_locks": "/api/files/locks",
        },
        "policy": {
            "authenticated_requests_require_https": True,
            "no_public_unrestricted_access": True,
            "every_client_independent_identity": True,
            "no_automatic_approval": True,
        },
    }
    body = "<pre>" + html.escape(json.dumps(manifest, indent=2)) + "</pre>"
    return page("SF2AiS Connection Discovery", body, wide=True)


@app.get("/api/connections/{connection_id}")
async def get_connection(connection_id: str, admin: str = Depends(admin_auth)):
    config = _load_state()
    conn = next((c for c in config.get("connections", []) if c.get("id") == connection_id), None)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection request not found.")
    return JSONResponse({"connection": conn})


@app.post("/api/connections/{connection_id}/approve", status_code=200)
async def approve_connection(connection_id: str, request: Request, admin: str = Depends(admin_auth)):
    config = _load_state()
    conn = next((c for c in config.get("connections", []) if c.get("id") == connection_id), None)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection request not found.")
    if conn.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Connection request is not pending.")
    conn["status"] = "approved"
    conn["approved_at"] = _now_iso()
    conn["session_id"] = _make_id()
    conn["client_id"] = _make_id()
    _save_state(config)
    audit_event("connection.approved", None, request, path=f"/api/connections/{connection_id}/approve", detail=conn)
    return JSONResponse({"connection": conn})


@app.post("/api/connections/{connection_id}/deny", status_code=200)
async def deny_connection(connection_id: str, request: Request, admin: str = Depends(admin_auth)):
    config = _load_state()
    conn = next((c for c in config.get("connections", []) if c.get("id") == connection_id), None)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection request not found.")
    if conn.get("status") not in ("pending", "approved"):
        raise HTTPException(status_code=409, detail="Connection request already final.")
    action = request.query_params.get("action", "deny")
    conn["status"] = "denied"
    conn["denied_at"] = _now_iso()
    if action == "blacklist":
        config.setdefault("blacklist", []).append({"client_id": conn.get("client_id"), "client_name": conn.get("identity"), "added_at": _now_iso(), "expires_at": None})
    _save_state(config)
    audit_event("connection.denied", None, request, path=f"/api/connections/{connection_id}/deny", detail=conn)
    return JSONResponse({"connection": conn})


@app.post("/api/connections/{connection_id}/status", status_code=200)
async def update_connection_status(connection_id: str, request: Request, admin: str = Depends(admin_auth)):
    data = await request.json()
    config = _load_state()
    conn = next((c for c in config.get("connections", []) if c.get("id") == connection_id), None)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection request not found.")
    new_status = data.get("status") if isinstance(data, dict) else None
    if new_status not in ("pending", "approved", "denied", "expired"):
        raise HTTPException(status_code=400, detail="Invalid status.")
    if new_status == "expired":
        conn["status"] = "expired"
        conn["expires_at"] = _now_iso()
    else:
        conn["status"] = new_status
    _save_state(config)
    audit_event("connection.status.changed", None, request, path=f"/api/connections/{connection_id}/status", detail=conn)
    return JSONResponse({"connection": conn})
# ============================================================================
# Universal gateway — session initialization protocol (SF2AiSLaw)
# Appended to main.py via chunk C.
# ============================================================================

SF2AIS_LAW = """# SF2AiSLaw v1.0.0 — mandatory operational & security rules

Every connecting AI client must receive this law and acknowledge it before
operational access is granted. The backend remains authoritative.

1. **Authorized role.** You are a scoped workspace assistant. Read, write
   (only where permitted), CLI sandbox execution, and approved tool use are
   allowed only inside the assigned share and capability scopes.
2. **Available permissions.** Granted via the connection's permissions manifest.
   You may not act outside them.
3. **Prohibited operations.** Host-shell execution, arbitrary filesystem access,
   credential/secret exfiltration, and commands that escape the sandbox are
   prohibited and will be logged.
4. **Filesystem boundaries.** All file operations stay inside the approved share
   root. Path traversal and symlink escape are rejected.
5. **CLI restrictions.** CLI runs only in the isolated Docker sandbox. Host
   PowerShell/CMD is never invoked. Commands are recorded; exit codes are
   reported.
6. **Credential and secret handling.** Never log, return, or expose passwords,
   tokens, or secrets. Secrets never enter logs or the audit trail.
7. **Data privacy.** Do not read or transmit data outside the approved share
   without explicit owner permission.
8. **Audit.** Every operation is audited server-side. You may read the audit
   timeline but must not attempt to exfiltrate it.
9. **Human authorization.** Human-facing requests require the configured
   authentication policy (biometric/passkey/device/none). None requires the
   exact word ACCEPT and warns of risk.
10. **File conflict rules.** Shared files use locks; a two-minute recent-edit
    warning applies. Coordinate with other editors before writing.
11. **Session expiration and revocation.** Sessions expire after the
    configured idle/timeout; owners may revoke any session immediately.
12. **Emergency termination.** The owner may lock the system, suspending new
    connections and revoking active sessions.

Law is instructional; backend authorization remains authoritative.
"""

SF2AIS_LAW_VERSIONS = {"1.0.0": SF2AIS_LAW}

ACCESS_TYPES = [
    {"id": "filesystem", "name": "Filesystem", "level": "disabled"},
    {"id": "cli", "name": "CLI sandbox", "level": "disabled"},
    {"id": "ide", "name": "IDE", "level": "disabled"},
    {"id": "git", "name": "Git", "level": "disabled"},
    {"id": "browser", "name": "Browser", "level": "disabled"},
    {"id": "desktop", "name": "Desktop", "level": "disabled"},
    {"id": "ssh", "name": "SSH", "level": "disabled"},
    {"id": "services", "name": "Services", "level": "disabled"},
    {"id": "database", "name": "Database", "level": "disabled"},
    {"id": "applications", "name": "Applications", "level": "disabled"},
]

TOOL_REGISTRY = [
    {"id": "fs_read", "name": "Read file", "category": "filesystem", "level": "read"},
    {"id": "fs_write", "name": "Write file", "category": "filesystem", "level": "write"},
    {"id": "fs_metadata", "name": "File metadata", "category": "filesystem", "level": "read"},
    {"id": "fs_move", "name": "Move file", "category": "filesystem", "level": "write"},
    {"id": "fs_delete", "name": "Delete file", "category": "filesystem", "level": "write"},
    {"id": "cli_execute", "name": "Execute command", "category": "cli", "level": "execute"},
    {"id": "cli_list_jobs", "name": "List CLI jobs", "category": "cli", "level": "read"},
    {"id": "ide_tree", "name": "Project tree", "category": "ide", "level": "read"},
    {"id": "ide_file", "name": "Read file", "category": "ide", "level": "read"},
    {"id": "git_status", "name": "Git status", "category": "git", "level": "read"},
    {"id": "git_diff", "name": "Git diff", "category": "git", "level": "read"},
    {"id": "git_stage", "name": "Git stage", "category": "git", "level": "write"},
    {"id": "browser_status", "name": "Browser status", "category": "browser", "level": "read"},
    {"id": "desktop_status", "name": "Desktop status", "category": "desktop", "level": "read"},
    {"id": "service_status", "name": "Service status", "category": "services", "level": "read"},
]

SKILL_REGISTRY = [
    {"id": "creodevo-dev", "name": "CreoDevo Development", "version": "1.0.0",
     "capabilities": ["filesystem", "git", "ide"], "instructions": "Use for CreoDevo project work."},
    {"id": "windows-dev", "name": "Windows Development", "version": "1.0.0",
     "capabilities": ["filesystem", "cli"], "instructions": "Use for Windows development."},
    {"id": "git-workflow", "name": "Git Workflow", "version": "1.0.0",
     "capabilities": ["git"], "instructions": "Use for version control tasks."},
    {"id": "security-audit", "name": "Security Audit", "version": "1.0.0",
     "capabilities": ["filesystem", "ide"], "instructions": "Use for security review."},
    {"id": "software-testing", "name": "Software Testing", "version": "1.0.0",
     "capabilities": ["filesystem", "ide"], "instructions": "Use for testing tasks."},
]

SKILL_VERSIONS = {"1.0.0": {}}


def _init_package(session):
    conn = session.get("connection", {})
    capabilities = session.get("capabilities", [])
    session_id = session.get("id")
    return {
        "protocol": "sf2ais.connection-init/1.0.0",
        "version": "1.0.0",
        "session_id": session_id,
        "state": session.get("state"),
        "sf2ais_law": SF2AIS_LAW,
        "connection_manifest": {
            "connection_id": conn.get("id"), "client_id": conn.get("client_id"),
            "client_type": conn.get("client_type"), "client_app": conn.get("client_app"),
            "client_version": conn.get("client_version"), "identity": conn.get("identity"),
            "created_at": conn.get("created_at"), "approved_at": conn.get("approved_at"),
            "session_id": session_id, "owner_id": conn.get("requester"),
        },
        "permissions_manifest": {
            "session_id": session_id, "capabilities": capabilities,
            "write": "filesystem" in capabilities,
            "cli": "cli" in capabilities,
            "ide": "ide" in capabilities,
            "git": "git" in capabilities,
            "browser": "browser" in capabilities,
            "desktop": "desktop" in capabilities,
            "ssh": "ssh" in capabilities,
            "services": "services" in capabilities,
            "database": "database" in capabilities,
            "applications": "applications" in capabilities,
        },
        "access_types": ACCESS_TYPES,
        "tool_discovery": {"instructions_url": "/api/capabilities/tools", "name": "sf2ais tool discover"},
        "skill_discovery": {"instructions_url": "/api/capabilities/skills", "name": "sf2ais skill discover"},
        "workspace_manifest": session.get("workspace_manifest", {"paths": []}),
        "system_capabilities": session.get("system_capabilities", {"storage": "local"}),
        "session_instructions": "Acknowledge the law above before using any tool.",
        "session_expiry": session.get("expires_at"),
        "revocation": "session may be revoked by owner at any time via /api/monitor/sessions",
    }


def _authz_ok(session):
    if session.get("state") != "authorized":
        return False
    return True


@app.post("/api/sessions", status_code=201)
async def create_session(request: Request, admin: str = Depends(admin_auth)):
    data = await request.json()
    config = _load_state()
    connection_id = data.get("connection_id") if isinstance(data, dict) else None
    conn = next((c for c in config.get("connections", []) if c.get("id") == connection_id), None)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection request not found.")
    if conn.get("status") != "approved":
        raise HTTPException(status_code=409, detail="Connection must be approved first.")
    share = conn.get("workspace") or {}
    if not isinstance(share, dict):
        share = {}
    session_id = _make_id()
    session = {
        "id": session_id,
        "connection_id": conn.get("id"),
        "client_id": conn.get("client_id"),
        "client_type": conn.get("client_type"),
        "identity": conn.get("identity"),
        "share_id": share.get("id"),
        "share_path": share.get("path"),
        "workspace_manifest": {"paths": [share.get("path")] if share.get("path") else []},
        "capabilities": conn.get("capabilities", []),
        "state": "authorized",
        "expires_at": _now_iso(),
        "idle_timeout_seconds": config.get("settings", {}).get("idle_timeout_seconds", 900),
        "created_at": _now_iso(),
        "last_seen": _now_iso(),
        "activity": [],
        "files_read": [],
        "files_written": [],
        "commands": [],
        "resource_usage": {},
    }
    config["sessions"][session_id] = session
    _save_state(config)
    audit_event("session.created", None, request, path="/api/sessions", detail=session)
    return JSONResponse({"session": _init_package(session)}, status_code=201)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, admin: str = Depends(admin_auth)):
    config = _load_state()
    session = config.get("sessions", {}).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return JSONResponse({"session": _init_package(session)})


@app.post("/api/sessions/{session_id}/ack")
async def ack_init(session_id: str, request: Request, admin: str = Depends(admin_auth)):
    config = _load_state()
    session = config.get("sessions", {}).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.get("state") != "authorized":
        raise HTTPException(status_code=409, detail="Session already initialized.")
    data = await request.json()
    ack = data if isinstance(data, dict) else {}
    law_version = ack.get("sf2ais_law_version", "1.0.0")
    if law_version not in SF2AIS_LAW_VERSIONS:
        raise HTTPException(status_code=400, detail="Unrecognised law version.")
    session["state"] = "initialized"
    session["ack"] = {
        "law_version": law_version,
        "init_received": True,
        "tools_discovered": ack.get("tools_discovered", []),
        "skills_discovered": ack.get("skills_discovered", []),
        "permissions_understood": ack.get("permissions_understood", True),
        "unsupported_capabilities": ack.get("unsupported_capabilities", []),
        "operational_ready": ack.get("operational_ready", False),
        "acknowledged_at": _now_iso(),
    }
    session["last_seen"] = _now_iso()
    _save_state(config)
    audit_event("session.initialized", None, request, path=f"/api/sessions/{session_id}/ack", detail=session["ack"])
    return JSONResponse({"session": _init_package(session)})


# ---------------------------------------------------------------------------
# Universal gateway — capability registry
# ---------------------------------------------------------------------------

def _tool_schema(tool_id):
    mapping = {
        "fs_read": {"summary": "Read a UTF-8 file inside the share", "input": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        "fs_write": {"summary": "Write a UTF-8 file inside the share", "input": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        "fs_move": {"summary": "Move a file inside the share", "input": {"type": "object", "properties": {"source": {"type": "string"}, "destination": {"type": "string"}}, "required": ["source", "destination"]}},
        "fs_delete": {"summary": "Delete a file or directory inside the share", "input": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        "cli_execute": {"summary": "Run a bounded command in the isolated sandbox", "input": {"type": "object", "properties": {"command": {"type": "string"}, "timeout_seconds": {"type": "integer"}}, "required": ["command"]}},
        "cli_list_jobs": {"summary": "List recent CLI jobs", "input": {"type": "object", "properties": {}}},
        "ide_tree": {"summary": "List an approved project directory tree", "input": {"type": "object", "properties": {"path": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["path"]}},
        "ide_file": {"summary": "Read a UTF-8 file from the approved share", "input": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        "git_status": {"summary": "Git status for the approved workspace", "input": {"type": "object", "properties": {}}},
        "git_diff": {"summary": "Unified diff of the workspace", "input": {"type": "object", "properties": {}}},
        "git_stage": {"summary": "Stage a file for commit", "input": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        "browser_status": {"summary": "Report browser session status", "input": {"type": "object", "properties": {}}},
        "desktop_status": {"summary": "Report desktop status", "input": {"type": "object", "properties": {}}},
        "service_status": {"summary": "Report service status", "input": {"type": "object", "properties": {}}},
    }
    return mapping.get(tool_id, {"summary": "Capabilities tool", "input": {"type": "object", "properties": {}}})


@app.get("/api/capabilities")
async def list_capabilities():
    return JSONResponse({
        "capabilities": {
            "tool_registry": TOOL_REGISTRY,
            "skill_registry": SKILL_REGISTRY,
            "access_types": ACCESS_TYPES,
            "component_versions": _COMPONENT_VERSIONS,
        }
    })


@app.get("/api/capabilities/tools")
async def list_tools():
    return JSONResponse({"tools": TOOL_REGISTRY})


@app.get("/api/capabilities/tools/{tool_id}/schema")
async def tool_schema(tool_id: str):
    return JSONResponse({"schema": _tool_schema(tool_id)})


@app.get("/api/capabilities/skills")
async def list_skills():
    return JSONResponse({"skills": SKILL_REGISTRY})


@app.get("/api/capabilities/workspaces")
async def list_workspaces(admin: str = Depends(admin_auth)):
    config = _load_state()
    workspaces = []
    for share in config.get("shares", []):
        workspaces.append({"id": share.get("id"), "path": share.get("folder"), "name": share.get("username")})
    return JSONResponse({"workspaces": workspaces})


@app.get("/api/capabilities/access-types")
async def list_access_types():
    return JSONResponse({"access_types": ACCESS_TYPES})


@app.get("/api/capabilities/system")
async def system_capabilities():
    return JSONResponse({
        "storage": "local",
        "sandbox": {"available": bool(sandbox_runner.docker_binary())},
        "computer_use_provider": CUA_DRIVER.status(),
        "component_versions": _COMPONENT_VERSIONS,
    })


# ---------------------------------------------------------------------------
# Universal gateway — file locking (per-file edit protection)
# ---------------------------------------------------------------------------

def _lock_key(path):
    return str(path)


def _acquire_lock(config, path, session_id, identity):
    key = _lock_key(path)
    now = _now_iso()
    lock = config.setdefault("file_locks", {}).get(key) or {
        "path": path, "owner_session": None, "owner_identity": None,
        "locked_at": now, "expires_at": "", "version": 1, "hash": "",
    }
    lock["owner_session"] = session_id
    lock["owner_identity"] = identity
    lock["locked_at"] = now
    lock["expires_at"] = _now_iso()
    lock["version"] = lock.get("version", 0) + 1
    config["file_locks"][key] = lock
    _save_state(config)
    return lock


def _release_lock(config, path, session_id):
    key = _lock_key(path)
    lock = config.get("file_locks", {}).get(key)
    if not lock:
        return None
    if lock.get("owner_session") != session_id:
        # only owner may release
        return None
    lock["owner_session"] = None
    lock["expires_at"] = _now_iso()
    config["file_locks"][key] = lock
    _save_state(config)
    return lock


@app.get("/api/files/locks")
async def list_locks(session_id: str = Header(default=""), identity: str = Header(default="")):
    # header style flexible (query or header)
    if not session_id:
        session_id = ""
    config = _load_state()
    user_locks = []
    for key, lock in config.get("file_locks", {}).items():
        if lock.get("owner_session") == session_id:
            user_locks.append(lock)
    return JSONResponse({"locks": user_locks})


@app.post("/api/files/locks", status_code=201)
async def acquire_lock(request: Request):
    data = await request.json()
    path = data.get("path") if isinstance(data, dict) else None
    session_id = data.get("session_id") or request.headers.get("X-Sf2AiS-Session")
    identity = data.get("identity") or request.headers.get("X-Sf2AiS-Identity") or "unknown"
    if not path or not session_id:
        raise HTTPException(status_code=400, detail="path and session_id required.")
    config = _load_state()
    lock = _acquire_lock(config, path, session_id, identity)
    return JSONResponse({"lock": lock}, status_code=201)


@app.delete("/api/files/locks/{file_path:path}")
async def release_lock(file_path: str, request: Request):
    session_id = request.headers.get("X-Sf2AiS-Session") or request.query_params.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required.")
    config = _load_state()
    lock = _release_lock(config, file_path, session_id)
    if lock is None:
        raise HTTPException(status_code=404, detail="Lock not held by this session.")
    return JSONResponse({"lock": lock})


@app.post("/api/files/locks/{file_path:path}/renew")
async def renew_lock(file_path: str, request: Request):
    session_id = request.headers.get("X-Sf2AiS-Session") or request.query_params.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required.")
    config = _load_state()
    lock = config.get("file_locks", {}).get(file_path)
    if not lock or lock.get("owner_session") != session_id:
        raise HTTPException(status_code=404, detail="Lock not held by this session.")
    lock["expires_at"] = _now_iso()
    lock["locked_at"] = _now_iso()
    config["file_locks"][file_path] = lock
    _save_state(config)
    return JSONResponse({"lock": lock})


# ---------------------------------------------------------------------------
# Universal gateway — live multi-session monitoring
# ---------------------------------------------------------------------------

# In-memory SSE channel registry (per session) for push updates.
_sse_channels = {}
_sse_lock = threading.Lock()


def _publish(session_id, event):
    payload = json.dumps(event, ensure_ascii=False)
    with _sse_lock:
        clients = _sse_channels.get(session_id)
        if clients:
            for q in clients:
                try:
                    q.put_nowait(payload)
                except Exception:
                    pass


@app.get("/api/monitor/sessions")
async def list_monitor_sessions(admin: str = Depends(admin_auth)):
    config = _load_state()
    sessions = []
    for sid, sess in config.get("sessions", {}).items():
        sessions.append({
            "session_id": sid,
            "client_id": sess.get("client_id"),
            "client_type": sess.get("client_type"),
            "identity": sess.get("identity"),
            "share_id": sess.get("share_id"),
            "workspace_path": sess.get("share_path"),
            "capabilities": sess.get("capabilities", []),
            "status": sess.get("state"),
            "expires_at": sess.get("expires_at"),
            "last_seen": sess.get("last_seen"),
            "resource_usage": sess.get("resource_usage", {}),
        })
    return JSONResponse({"sessions": sessions})


@app.get("/api/monitor/events")
async def monitor_events(admin: str = Depends(admin_auth), session_id: str | None = None,
                         since: str | None = None, limit: int = 200):
    config = _load_state()
    events = []
    for sid, sess in config.get("sessions", {}).items():
        if session_id and sid != session_id:
            continue
        for ev in sess.get("activity", []):
            try:
                ts = datetime.fromisoformat(ev.get("at", ""))
            except (ValueError, TypeError):
                continue
            if since and ts <= datetime.fromisoformat(since):
                continue
            events.append(ev)
            if len(events) >= limit:
                break
        if len(events) >= limit:
            break
    return JSONResponse({"events": events})


@app.get("/api/monitor/events/stream")
async def monitor_events_stream(session_id: str | None = None):
    # SSE fallback over HTTP; a polling client should use /api/monitor/events.
    async def _stream():
        buf = ""
        while True:
            with _sse_lock:
                channels = _sse_channels.setdefault(session_id, [])
            if session_id and session_id not in config.get("sessions", {}):
                await asyncio.sleep(1)
                continue
            yield "data: " + json.dumps({"type": "ping", "session_id": session_id}) + "\n\n"
            await asyncio.sleep(3)
    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.post("/api/monitor/events", status_code=201)
async def record_monitor_event(request: Request, admin: str = Depends(admin_auth)):
    data = await request.json()
    session_id = data.get("session_id") if isinstance(data, dict) else None
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required.")
    config = _load_state()
    session = config.get("sessions", {}).get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    event = {
        "at": _now_iso(),
        "session_id": session_id,
        "action": data.get("action") or "monitor.event",
        "detail": data.get("detail", {}),
    }
    session.setdefault("activity", []).append(event)
    _publish(session_id, event)
    audit_event("monitor.activity", None, request, path="/api/monitor/events", detail=event)
    return JSONResponse({"event": event}, status_code=201)
