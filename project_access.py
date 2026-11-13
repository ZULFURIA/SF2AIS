"""Per-AI project-folder permission evaluation for SF2AiS.

Rules are relative to a configured share root. Access is deny-by-default for
AI client tokens. A matching explicit deny always wins over inherited grants.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

ACTIONS = ("read", "write", "upload", "download")
PERMISSION_KEYS = (*ACTIONS, "deny")


def normalise_rule_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if raw in ("", "."):
        return ""
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("Permission paths must be relative to the project folder.")
    if any(":" in part or any(ord(ch) < 32 for ch in part) for part in path.parts):
        raise ValueError("Permission path contains an invalid path segment.")
    return path.as_posix()


def validate_access_config(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Project access must be an object.")
    unknown = set(value) - set(PERMISSION_KEYS) - {"rules"}
    if unknown:
        raise ValueError("Unknown project permission: " + ", ".join(sorted(unknown)))
    result = {key: value.get(key, False) for key in PERMISSION_KEYS}
    if any(not isinstance(flag, bool) for flag in result.values()):
        raise ValueError("Project permissions must be boolean values.")
    rules = value.get("rules", [])
    if not isinstance(rules, list) or len(rules) > 500:
        raise ValueError("Project path rules must be a list of at most 500 entries.")
    clean_rules = []
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) - ({"path"} | set(PERMISSION_KEYS)):
            raise ValueError("Each path rule must contain a path and permission flags only.")
        path = normalise_rule_path(rule.get("path", ""))
        if not path:
            raise ValueError("Use the project-level controls for the project root.")
        if path in seen:
            raise ValueError("Duplicate permission rule for: " + path)
        seen.add(path)
        clean = {"path": path}
        for key in PERMISSION_KEYS:
            if key in rule and not isinstance(rule[key], bool):
                raise ValueError("Project permissions must be boolean values.")
            if key in rule:
                clean[key] = rule[key]
        clean_rules.append(clean)
    clean_rules.sort(key=lambda item: (item["path"].count("/"), item["path"].casefold()))
    result["rules"] = clean_rules
    return result


def effective_permissions(client_permissions: dict | None, path: str) -> dict:
    """Return effective per-path rights for an authenticated client token."""
    if not isinstance(client_permissions, dict):
        # Legacy Basic-auth shares are constrained by the share-level master switch.
        return {"read": True, "write": False, "upload": False, "download": True, "deny": False}
    access = client_permissions.get("project_access")
    if not isinstance(access, dict):
        # Existing AI tokens keep their previous broad read/write scopes until
        # an administrator explicitly configures granular access for them.
        return {
            "read": bool(client_permissions.get("read", False)),
            "write": bool(client_permissions.get("write", False)),
            "upload": bool(client_permissions.get("write", False)),
            "download": bool(client_permissions.get("read", False)),
            "deny": False,
        }
    rel = normalise_rule_path(path)
    result = {key: bool(access.get(key, False)) for key in PERMISSION_KEYS}
    if result["deny"]:
        return {key: False for key in PERMISSION_KEYS} | {"deny": True}
    matched = []
    for rule in access.get("rules", []):
        rule_path = normalise_rule_path(rule.get("path", ""))
        if rel == rule_path or rel.startswith(rule_path + "/"):
            matched.append(rule)
    # Any explicit deny on an ancestor or exact path is absolute.
    if any(rule.get("deny") is True for rule in matched):
        return {key: False for key in PERMISSION_KEYS} | {"deny": True}
    for rule in matched:
        for key in ACTIONS:
            if key in rule:
                result[key] = bool(rule[key])
    result["deny"] = False
    return result


def is_allowed(client_permissions: dict | None, path: str, action: str) -> bool:
    if action not in ACTIONS:
        raise ValueError("Unsupported project permission action.")
    rights = effective_permissions(client_permissions, path)
    return not rights["deny"] and rights[action]
