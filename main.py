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

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
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
        rows += """
        <tr>
            <td>%s</td>
            <td>%s</td>
            <td><span class="badge %s"><span class="pulse"></span>%s</span></td>
            <td>%s</td>
            <td>
                <form method="post" action="/dashboard/shares/%s/delete" style="margin:0;">
                    <button type="submit" class="danger small">Remove</button>
                </form>
            </td>
        </tr>
        """ % (s['folder'], s['username'], s_badge, s_text, seen_label, s['id'])

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

        <h2 style="margin-top:30px;">Shares</h2>
        <table>
            <thead><tr><th>Folder</th><th>Username</th><th>Status</th><th>Last seen</th><th></th></tr></thead>
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
    """ % (badge_cls, badge_text, net_msg, link, rows))
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
    })
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
