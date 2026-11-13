import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import main

for route in main.app.routes:
    path = getattr(route, "path", "")
    if any(term in path.lower() for term in ("network", "router", "ddns", "relay", "desktop", "share", "computer-use", "client", "task", "agent", "cli", "workspace", "ide")):
        methods = ",".join(sorted(getattr(route, "methods", []) or []))
        print(methods, getattr(getattr(route.endpoint, '__code__', None), 'co_firstlineno', 0), path)
