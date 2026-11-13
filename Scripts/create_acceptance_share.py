from __future__ import annotations

import json
import os
import secrets
import string
import uuid
from pathlib import Path

from passlib.hash import bcrypt

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "config.json"
SHARE_ROOT = (ROOT / "test-share").resolve()
USERNAME = "sf2ais-acceptance"

if not CONFIG.is_file():
    raise SystemExit(f"Missing configuration: {CONFIG}")
data = json.loads(CONFIG.read_text(encoding="utf-8"))
existing = next((s for s in data.get("shares", []) if s.get("username") == USERNAME), None)
if existing:
    print(f"Acceptance share already exists: {USERNAME}")
    raise SystemExit(0)

SHARE_ROOT.mkdir(parents=True, exist_ok=True)
alphabet = string.ascii_letters + string.digits + "!@#$%_-"
password_chars = [
    secrets.choice(string.ascii_uppercase),
    secrets.choice(string.ascii_lowercase),
    secrets.choice(string.digits),
    secrets.choice("!@#$%_-"),
]
password_chars.extend(secrets.choice(alphabet) for _ in range(28))
secrets.SystemRandom().shuffle(password_chars)
password = "".join(password_chars)

share = {
    "id": str(uuid.uuid4()),
    "username": USERNAME,
    "password_hash": bcrypt.hash(password),
    "folder": str(SHARE_ROOT),
    "last_seen": None,
    "cli_enabled": True,
    "tunnel_enabled": False,
    "workspace_write_enabled": True,
    "ide_enabled": True,
    "computer_use_enabled": False,
    "clients": [],
}
data.setdefault("shares", []).append(share)
temporary = CONFIG.with_suffix(".json.acceptance.tmp")
temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, CONFIG)
print(f"ACCEPTANCE_SHARE_USERNAME={USERNAME}")
print(f"ACCEPTANCE_SHARE_PASSWORD={password}")
print(f"ACCEPTANCE_SHARE_FOLDER={SHARE_ROOT}")
print("CLI=enabled; workspace_write=enabled; IDE=enabled; CUA=disabled; tunnel=disabled")
