import os, sys, json, base64
sys.path.insert(0, ".")
import main

TEST_DIR = os.path.abspath("./data/security-test")
os.makedirs(TEST_DIR, exist_ok=True)
share_dir = os.path.abspath("./data/security-share")
os.makedirs(share_dir, exist_ok=True)

# Write a harmless test file inside the share.
with open(os.path.join(share_dir, "hello.txt"), "w") as f:
    f.write("hello world")

config = {
    "admin": {"username": "admin", "password_hash": main.bcrypt.hash("admin-pass-123")},
    "settings": main.DEFAULT_SETTINGS,
    "network": {"port": 8000, "tls": False},
    "shares": [
        {"id": "s1", "folder": share_dir, "username": "share1", "password_hash": main.bcrypt.hash("share-pass-1"),
         "client_id": "client-a", "authorized_clients": ["client-a"],
         "capabilities": ["filesystem"], "permission": "read-write"},
        {"id": "s2", "folder": os.path.abspath("./data/secret-share"), "username": "share2", "password_hash": main.bcrypt.hash("share2-pass"),
         "client_id": "client-b", "authorized_clients": ["client-b"],
         "capabilities": ["filesystem"], "permission": "read-only"},
    ],
    "connections": [], "sessions": {}, "file_locks": {}, "blacklist": [],
    "skill_registry": [], "tool_registry": [], "component_versions": main._COMPONENT_VERSIONS,
}
config_path = os.path.join(TEST_DIR, "config.json")
with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

# Point the app at the test config.
os.environ["CONFIG_PATH"] = TEST_DIR
# Reload config path (already read at import; reload modules that used the old path).
main.CONFIG_PATH = Path(os.environ["CONFIG_PATH"])
from pathlib import Path
main.AUDIT_PATH = main.CONFIG_PATH.parent / "audit.jsonl"

print("config written:", config_path)
print("share:", share_dir)
print("token hashes exist:", all(c.get("token_hash") for c in config["shares"][0].get("clients", [])))
