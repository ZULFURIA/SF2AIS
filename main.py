# ==============================================================================
# AI-Gateway-FTP Core Service Terminal
# Copyright (c) 2026 Wayne Thomas Dougall (ZULFURIA). All rights reserved.
# Licensed under the Sf2AiS Noncommercial License v1.0.
# Commercial use requires prior written permission from the copyright holder.
# ==============================================================================
import os
import re
import json
import html
import uuid
import secrets
import string
from pathlib import Path
from datetime import datetime, timezone
from mimetypes import guess_type

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
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

APP_NAME = "Sf2AiS"
APP_TAGLINE = "Secure Files to AI Server"

app = FastAPI(title=APP_NAME, description="Secure file bridge for web-browsing AI assistants.")
security = HTTPBasic()

BASE_DIR = Path(__file__).parent
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

def _resolve_secrets(obj):
    """Replace ${ENV_VAR} placeholders with environment values.

    Credentials (probe token, DDNS token) are stored as ${SF2AIS_*} placeholders
    in data/config.json so no secret is ever committed. They resolve at load time
    from the environment, falling back to the literal value if no env var is set
    (so a plaintext value still works for local dev).
    """
    if isinstance(obj, dict):
        return {k: _resolve_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_secrets(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        name = obj[2:-1]
        return os.environ.get(name, obj)
    return obj

def load_config():
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text())
            return _resolve_secrets(raw)
        except Exception:
            return None
    return None

def save_config(config: dict):
    CONFIG_PATH.write_text(json.dumps(config, indent=2))

def is_configured() -> bool:
    return load_config() is not None

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

def admin_auth(credentials: HTTPBasicCredentials = Depends(security)):
    config = load_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Not configured. Visit / to complete setup.")
    admin = config["admin"]
    ok_user = secrets.compare_digest(credentials.username, admin["username"])
    ok_pass = bcrypt.verify(credentials.password, admin["password_hash"])
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401, detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def share_auth(credentials: HTTPBasicCredentials = Depends(security)):
    config = load_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Not configured.")
    match = None
    for share in config.get("shares", []):
        if secrets.compare_digest(credentials.username, share["username"]):
            match = share
            break
    valid = match is not None and bcrypt.verify(credentials.password, match["password_hash"])
    if not valid:
        raise HTTPException(
            status_code=401, detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    match["last_seen"] = now_iso()
    save_config(config)
    return match

# ---------------------------------------------------------------------------
# Network / link helpers
# ---------------------------------------------------------------------------

def build_share_link(config) -> str:
    network = config.get("network", {})
    method = network.get("method")
    port = network.get("port", 8000)

    if method in ("domain", "ddns"):
        host = network.get("value") or "your-domain-not-set"
        return "https://%s" % host
    if method == "static":
        ip = network.get("value") or "0.0.0.0"
        return "http://%s:%s" % (ip, port)
    if method == "probe":
        ip = network.get("last_public_ip")
        if ip:
            return "http://%s:%s" % (ip, port)
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
    error_html = ('<div class="error">%s</div>' % error) if error else ""
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
            <input type="text" name="port" value="8000">

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
    port = int(form.get("port") or 8000)
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
        """ % (c['folder'], c['username'], c['password'])

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
        <a class="btn" style="margin-top:26px;" href="/dashboard">Go to Dashboard &rarr;</a>
    """ % (creds_html, probe_block))
    return page("Setup Complete", body)

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(admin: str = Depends(admin_auth)):
    config = load_config()
    link = build_share_link(config)
    net_online, net_msg = network_online_status(config)

    ddns_cfg = config.get("network", {}).get("ddns") or {}
    ddns_domain = ddns_cfg.get("domain", "")
    if ddns_cfg.get("domain") and ddns_cfg.get("token"):
        last = ddns_cfg.get("last_result")
        if last:
            ddns_status = "%s (%s)" % (last.get("message", ""), "OK" if last.get("ok") else "failed")
        else:
            ddns_status = "Configured for %s.duckdns.org - waiting for the next IP check." % ddns_domain
    else:
        ddns_status = "Not configured. Get a free token at duckdns.org, add a subdomain there, then enter it below."
    badge_cls = "online" if net_online else "offline"
    badge_text = "Online" if net_online else "Offline"

    rows = ""
    for s in config.get("shares", []):
        last_seen = s.get("last_seen")
        online = False
        seen_label = "Never connected"
        if last_seen:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_seen)).total_seconds()
            online = age <= SHARE_ONLINE_WINDOW_SECONDS
            mins = int(age // 60)
            seen_label = "just now" if mins < 1 else "%d min ago" % mins
        s_badge = "online" if online else "offline"
        s_text = "Connected" if online else "Offline"
        cli_on = s.get("cli_enabled", False)
        cli_badge = "online" if cli_on else "offline"
        cli_text = "Enabled" if cli_on else "Disabled"
        cli_btn_label = "Disable" if cli_on else "Enable"
        tunnel_on = s.get("tunnel_enabled", False)
        tunnel_badge = "online" if tunnel_on else "offline"
        tunnel_text = "Enabled" if tunnel_on else "Disabled"
        tunnel_btn_label = "Disable" if tunnel_on else "Enable"
        rows += """
        <tr>
            <td>%s</td>
            <td>%s</td>
            <td><span class="badge %s"><span class="pulse"></span>%s</span></td>
            <td>%s</td>
            <td>
                <span class="badge %s">%s</span>
                <form method="post" action="/dashboard/shares/%s/toggle-cli" style="display:inline; margin-left:6px;">
                    <button type="submit" class="secondary small">%s</button>
                </form>
            </td>
            <td>
                <span class="badge %s">%s</span>
                <form method="post" action="/dashboard/shares/%s/toggle-tunnel" style="display:inline; margin-left:6px;">
                    <button type="submit" class="secondary small">%s</button>
                </form>
            </td>
            <td>
                <form method="post" action="/dashboard/shares/%s/delete" style="margin:0;">
                    <button type="submit" class="danger small">Remove</button>
                </form>
            </td>
        </tr>
        """ % (s['folder'], s['username'], s_badge, s_text, seen_label,
               cli_badge, cli_text, s['id'], cli_btn_label,
               tunnel_badge, tunnel_text, s['id'], tunnel_btn_label,
               s['id'])

    body = brand_header() + ("""
        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px;">
            <h2 style="margin:0;">Dashboard</h2>
            <span class="badge %s"><span class="pulse"></span>%s</span>
        </div>
        <p class="sub">%s</p>

        <div class="card-sm" style="margin-top:16px;">
            <div class="label">Shareable link</div>
            <div class="copy-row">
                <code id="share-link">%s</code>
                <button type="button" class="small secondary" onclick="copyLink()">Copy</button>
            </div>
        </div>

        <div class="card-sm" style="margin-top:16px;">
            <div class="label">DDNS (DuckDNS)</div>
            <p class="sub" style="margin-top:4px;">%s</p>
            <form method="post" action="/dashboard/ddns" style="display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end;">
                <div>
                    <label style="display:block; font-size:12px;">Subdomain</label>
                    <input type="text" name="domain" placeholder="wayne-debug" value="%s" style="width:160px;">
                </div>
                <div>
                    <label style="display:block; font-size:12px;">Token</label>
                    <input type="password" name="token" placeholder="duckdns token" style="width:220px;">
                </div>
                <button type="submit" class="secondary small">Save</button>
            </form>
        </div>

        <h2 style="margin-top:30px;">Desktop Probe App</h2>
        <div class="card-sm" style="margin-top:12px;">
            <div class="label">Electron Probe</div>
            <p class="sub" style="margin-top:4px;">Download and run the desktop app for automatic IP monitoring,
            system tray control, and scheduled background checks.</p>
            <div class="grid-2" style="margin-top:14px;">
                <a class="btn secondary" href="/probe/desktop-app/windows">Download for Windows (.zip)</a>
                <a class="btn secondary" href="/probe/desktop-app/macos">Download for macOS (.zip)</a>
            </div>
            <div class="grid-2" style="margin-top:10px;">
                <a class="btn secondary" href="/probe/desktop-app/linux">Download for Linux (.zip)</a>
                <a class="btn secondary" href="/probe/setup-guide">Setup instructions</a>
            </div>
        </div>

        <h2 style="margin-top:30px;">Shares</h2>
        <table>
            <thead><tr><th>Folder</th><th>Username</th><th>Status</th><th>Last seen</th><th>CLI</th><th>Tunnel</th><th></th></tr></thead>
            <tbody>%s</tbody>
        </table>

        <button type="button" class="secondary" style="margin-top:20px;" onclick="document.getElementById('add-modal').classList.add('open')">+ Add Share</button>

        <div class="modal-overlay" id="add-modal">
            <div class="modal glass">
                <h2>Add a new share</h2>
                <p class="sub">Give a new folder its own username and password.</p>
                <form method="post" action="/dashboard/shares/add">
                    <label>Folder path</label>
                    <input type="text" name="folder" required placeholder="/home/you/Documents/New-Share">
                    <label>Username</label>
                    <input type="text" name="username" required>
                    <label>Password</label>
                    <input type="password" name="password" id="new-password" required oninput="checkStrength()">
                    <ul class="reqs" id="reqs">
                        <li id="r-len">At least 12 characters</li>
                        <li id="r-lower">One lowercase letter</li>
                        <li id="r-upper">One uppercase letter</li>
                        <li id="r-digit">One number</li>
                        <li id="r-special">One special character</li>
                    </ul>
                    <label style="display:flex; align-items:flex-start; gap:8px; margin-top:10px;">
                        <input type="checkbox" name="cli_enabled" style="width:auto; margin-top:3px;">
                        <span>Allow command execution (CLI) for this share.</span>
                    </label>
                    <label style="display:flex; align-items:flex-start; gap:8px; margin-top:8px;">
                        <input type="checkbox" name="tunnel_enabled" style="width:auto; margin-top:3px;">
                        <span>Allow temporary debug tunnels for this share.</span>
                    </label>
                    <div style="display:flex; gap:10px;">
                        <button type="button" class="secondary" onclick="document.getElementById('add-modal').classList.remove('open')">Cancel</button>
                        <button type="submit">Create Share</button>
                    </div>
                </form>
            </div>
        </div>

        <script>
        function copyLink() {
            var text = document.getElementById('share-link').innerText;
            navigator.clipboard.writeText(text);
        }
        function checkStrength() {
            var pw = document.getElementById('new-password').value;
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
        setInterval(function(){ location.reload(); }, 15000);
        </script>
    """ % (badge_cls, badge_text, net_msg, link, ddns_status, ddns_domain, rows))
    return page("Dashboard", body, wide=True)

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
    })
    save_config(config)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/dashboard/shares/{share_id}/toggle-cli")
def toggle_cli(share_id: str, admin: str = Depends(admin_auth)):
    config = load_config()
    for s in config.get("shares", []):
        if s["id"] == share_id:
            s["cli_enabled"] = not s.get("cli_enabled", False)
    save_config(config)
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
# Probe (public IP updater) endpoint + downloadable script
# ---------------------------------------------------------------------------

@app.post("/api/ip-update")
async def ip_update(request: Request):
    config = load_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Not configured.")
    data = await request.json()
    token = data.get("token", "")
    ip = data.get("ip", "")
    expected = config.get("network", {}).get("probe_token", "")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid probe token.")
    if not re.match(r"^[0-9a-fA-F.:]+$", ip or ""):
        raise HTTPException(status_code=400, detail="Invalid IP format.")
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
    gateway_url = "http://YOUR-GATEWAY-ADDRESS:8000"
    script = PROBE_SCRIPT.replace("GATEWAY_URL_PLACEHOLDER", gateway_url).replace("PROBE_TOKEN_PLACEHOLDER", token)
    return Response(content=script, media_type="text/x-python",
                     headers={"Content-Disposition": "attachment; filename=probe.py"})

@app.get("/probe/setup-guide", response_class=HTMLResponse)
def probe_setup_guide():
    body = brand_header() + """
        <h2>IP Probe setup</h2>
        <p class="sub">1. Install Python 3 if it isn't already (comes preinstalled on most Mac/Linux systems).</p>
        <p class="sub">2. Open the downloaded <code>probe.py</code> and replace <code>GATEWAY_URL</code>
        with your gateway's real address (e.g. http://203.0.113.5:8000 or your domain).</p>
        <p class="sub">3. Schedule it to run every 5 minutes:</p>
        <p class="sub"><strong>Windows</strong> - Task Scheduler &rarr; Create Basic Task &rarr; Trigger: repeat every 5 min &rarr; Action: run python.exe with the script path as argument.</p>
        <p class="sub"><strong>macOS / Linux</strong> - run <code>crontab -e</code> and add:</p>
        <code>*/5 * * * * /usr/bin/python3 /path/to/probe.py</code>
        <a class="btn secondary" style="margin-top:20px;" href="/dashboard">Back to dashboard</a>
    """
    return page("Probe Setup", body)


@app.get("/probe/desktop-app/{platform}")
def probe_desktop_app(platform: str, token: str = "", admin: str = Depends(admin_auth)):
    """Download the packaged desktop Electron probe app for the given platform.

    The app is shipped as a ZIP of the whole `probe-app/dist/` folder so the
    executable and all of its sibling dependencies (DLLs, locales, swiftshader,
    etc.) stay co-located. Sending the lone .exe loses those deps and the app
    fails to launch. If dist/ is empty we point the user at the Python script.
    """
    probe_dir = Path(__file__).parent / "probe-app"
    dist_dir = probe_dir / "dist"

    platform_map = {
        "windows": "sf2ais-probe-windows.zip",
        "macos": "sf2ais-probe-macos.zip",
        "linux": "sf2ais-probe-linux.zip",
    }
    archive_name = platform_map.get(platform.lower())
    if not archive_name:
        raise HTTPException(status_code=404, detail="Unsupported platform. Use 'windows', 'macos', or 'linux'.")

    if not dist_dir.exists() or not any(dist_dir.iterdir()):
        raise HTTPException(
            status_code=404,
            detail="Desktop app is not yet built on the server. Run `npm run build` in probe-app. "
                   "You can still use the Python script: /probe/download?token=%s&platform=%s" % (token, platform),
        )

    import io as _io
    import zipfile as _zipfile
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(dist_dir.rglob("*")):
            if entry.is_file():
                zf.write(entry, entry.relative_to(dist_dir))
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=%s" % archive_name},
    )


# ---------------------------------------------------------------------------
# CLI execution (opt-in, per-share) - lets an AI assistant run shell / PowerShell
# commands for debugging and testing, alongside the read-only file endpoints.
# Off by default; a share must have cli_enabled=True to use these routes.
# ---------------------------------------------------------------------------
import subprocess
import threading
import platform

CLI_JOBS = {}
CLI_JOBS_LOCK = threading.Lock()
CLI_MAX_RUNTIME_SECONDS = 600     # hard kill after 10 minutes
CLI_MAX_OUTPUT_CHARS = 200_000    # truncate huge output


def default_shell() -> str:
    return "powershell" if platform.system() == "Windows" else "bash"


def build_shell_command(shell: str, command: str):
    shell = (shell or "auto").lower()
    if shell == "auto":
        shell = default_shell()
    if shell == "powershell":
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    if shell == "cmd":
        return ["cmd", "/c", command]
    if shell == "bash":
        return ["bash", "-lc", command]
    raise ValueError("Unsupported shell: %s" % shell)


def resolve_cli_cwd(share: dict, requested: str) -> Path:
    base_dir = Path(share["folder"]).resolve()
    if not requested:
        return base_dir
    candidate = (base_dir / requested).resolve()
    if not candidate.is_relative_to(base_dir):
        raise HTTPException(status_code=403, detail="cwd must stay inside the share folder.")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=400, detail="cwd does not exist.")
    return candidate


def require_cli_enabled(share: dict):
    if not share.get("cli_enabled"):
        raise HTTPException(status_code=403, detail="CLI access is disabled for this share.")


def _run_cli_job(job_id: str, shell: str, command: str, cwd: Path):
    job = CLI_JOBS[job_id]
    try:
        argv = build_shell_command(shell, command)
    except ValueError as e:
        job["status"] = "failed"
        job["stderr"] = str(e)
        job["finished_at"] = now_iso()
        return

    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        job["status"] = "failed"
        job["stderr"] = "Shell '%s' is not available on this host." % shell
        job["finished_at"] = now_iso()
        return

    job["pid"] = proc.pid
    try:
        stdout, stderr = proc.communicate(timeout=CLI_MAX_RUNTIME_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        job["status"] = "timeout"
        job["stdout"] = (stdout or "")[:CLI_MAX_OUTPUT_CHARS]
        job["stderr"] = ((stderr or "") + "\n[killed: exceeded %ds runtime limit]" % CLI_MAX_RUNTIME_SECONDS)[:CLI_MAX_OUTPUT_CHARS]
        job["exit_code"] = None
        job["finished_at"] = now_iso()
        return

    job["status"] = "completed"
    job["stdout"] = (stdout or "")[:CLI_MAX_OUTPUT_CHARS]
    job["stderr"] = (stderr or "")[:CLI_MAX_OUTPUT_CHARS]
    job["exit_code"] = proc.returncode
    job["finished_at"] = now_iso()


@app.post("/cli/jobs")
async def cli_create_job(request: Request, share: dict = Depends(share_auth)):
    require_cli_enabled(share)
    data = await request.json()
    command = (data.get("command") or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="'command' is required.")
    shell = data.get("shell") or share.get("cli_shell") or "auto"
    cwd = resolve_cli_cwd(share, data.get("cwd") or "")

    job_id = str(uuid.uuid4())
    with CLI_JOBS_LOCK:
        CLI_JOBS[job_id] = {
            "id": job_id, "share_id": share["id"], "command": command,
            "shell": shell, "cwd": str(cwd), "status": "running",
            "stdout": "", "stderr": "", "exit_code": None,
            "started_at": now_iso(), "finished_at": None,
        }
    thread = threading.Thread(target=_run_cli_job, args=(job_id, shell, command, cwd), daemon=True)
    thread.start()
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
    local_port = int(data.get("local_port", 0))
    if not (1 <= local_port <= 65535):
        raise HTTPException(status_code=400, detail="local_port must be 1-65535.")
    protocol = (data.get("protocol") or "TCP").upper()
    if protocol not in ("TCP", "UDP"):
        raise HTTPException(status_code=400, detail="protocol must be TCP or UDP.")
    ttl_seconds = min(int(data.get("ttl_seconds") or TUNNEL_DEFAULT_TTL_SECONDS), TUNNEL_MAX_TTL_SECONDS)
    external_port = int(data.get("external_port") or local_port)
    isolate = bool(data.get("isolate", False))
    trusted_remotes = [r.strip() for r in (data.get("trusted_remotes") or []) if r.strip()]

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
        alias_ip = data.get("alias_ip")
        if_index = data.get("interface_index")
        if not alias_ip or if_index is None:
            raise HTTPException(
                status_code=400,
                detail="isolate=true requires both alias_ip and interface_index (see GET /tunnel/interfaces).",
            )
        fw_prefix = "Sf2AiS_%s" % tunnel_id[:8]
        try:
            nte_context = micro_firewall.add_alias_ip(alias_ip, int(if_index))
            micro_firewall.add_firewall_rules(fw_prefix, alias_ip, external_port, trusted_remotes)
        except Exception as e:
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

    return JSONResponse({
        "tunnel_id": tunnel_id,
        "public_url": public_url,
        "external_port": external_port,
        "expires_in_seconds": ttl_seconds,
        "verify_result": verify_result,
        "isolated": isolate,
    })


@app.post("/tunnel/{tunnel_id}/close")
def tunnel_close(tunnel_id: str, share: dict = Depends(share_auth)):
    require_tunnel_enabled(share)
    t = TUNNELS.get(tunnel_id)
    if not t or t["share_id"] != share["id"]:
        raise HTTPException(status_code=404, detail="Tunnel not found.")
    _close_tunnel(tunnel_id, reason="closed by request")
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
        # Prevent listing hidden system configuration files
        if file.name.startswith('.'):
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
    base_dir = Path(share["folder"]).resolve()
    
    # Security Rule 1: Strip out directory separators to isolate the absolute base string
    clean_filename = Path(filename).name
    
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
