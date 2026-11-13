from pathlib import Path

import pytest
from fastapi import HTTPException

from computer_use_manager import ACTION_TOOLS, OBSERVATION_TOOLS, ALLOWED_TOOLS, CuaDriverBridge, CuaDriverError
from main import computer_use_status, require_computer_use_scope, workspace_writeback_allowed


def test_cua_tool_surface_excludes_shell_and_unbounded_script():
    assert "get_desktop_state" in OBSERVATION_TOOLS
    assert "click" in ACTION_TOOLS
    assert "shell_execute" not in ALLOWED_TOOLS
    assert "run_script" not in ALLOWED_TOOLS
    assert "clipboard_read" not in ALLOWED_TOOLS


def test_bridge_reports_unavailable_without_a_driver_binary(tmp_path: Path):
    bridge = CuaDriverBridge(tmp_path, binary_path=str(tmp_path / "missing.exe"))
    status = bridge.status()
    assert status["available"] is False
    assert status["running"] is False
    assert status["network_listener"] is False


def test_bridge_writes_bounded_deny_by_default_policy(tmp_path: Path):
    bridge = CuaDriverBridge(tmp_path, binary_path=str(tmp_path / "missing.exe"))
    manifest, policy = bridge._write_policy()
    assert "version: 3" in manifest.read_text()
    assert "desktop:" in manifest.read_text()
    policy_text = policy.read_text()
    assert "deny:" in policy_text
    assert "shell_execute" in policy_text
    assert "run_script" in policy_text


def test_observation_requires_share_and_token_grants():
    share = {
        "computer_use_enabled": True,
        "computer_use_observe_enabled": True,
        "computer_use_control_enabled": False,
        "_client_permissions": {
            "computer_use": True,
            "computer_use_observe": True,
            "computer_use_control": False,
        },
    }
    require_computer_use_scope(share, "observe")
    with pytest.raises(HTTPException) as exc:
        require_computer_use_scope(share, "control")
    assert exc.value.status_code == 403


def test_observation_is_denied_when_share_scope_is_missing_or_false():
    for share in (
        {"computer_use_enabled": True},
        {"computer_use_enabled": True, "computer_use_observe_enabled": False},
        {"computer_use_enabled": True, "computer_use_observe_enabled": True,
         "_client_permissions": {"computer_use": True, "computer_use_observe": False}},
    ):
        with pytest.raises(HTTPException) as exc:
            require_computer_use_scope(share, "observe")
        assert exc.value.status_code == 403


def test_cua_status_hides_tools_until_each_scope_is_granted():
    disabled = computer_use_status({"computer_use_enabled": True})
    assert disabled["observe_allowed"] is False
    assert disabled["control_allowed"] is False
    assert disabled["exposed_tools"] == []

    observing = computer_use_status({
        "computer_use_enabled": True,
        "computer_use_observe_enabled": True,
        "_client_permissions": {"computer_use": True, "computer_use_observe": True},
    })
    assert observing["observe_allowed"] is True
    assert observing["control_allowed"] is False
    assert set(observing["exposed_tools"]) == OBSERVATION_TOOLS
    assert not (set(observing["exposed_tools"]) & ACTION_TOOLS)


def test_control_requires_explicit_share_and_client_permission():
    share = {
        "computer_use_enabled": True,
        "computer_use_observe_enabled": True,
        "computer_use_control_enabled": True,
        "_client_permissions": {
            "computer_use": True,
            "computer_use_observe": True,
            "computer_use_control": False,
        },
    }
    with pytest.raises(HTTPException) as exc:
        require_computer_use_scope(share, "control")
    assert exc.value.status_code == 403
    share["_client_permissions"]["computer_use_control"] = True
    require_computer_use_scope(share, "control")


def test_disabled_share_blocks_all_computer_use():
    share = {
        "computer_use_enabled": False,
        "computer_use_observe_enabled": True,
        "_client_permissions": {"computer_use": True, "computer_use_observe": True},
    }
    with pytest.raises(HTTPException) as exc:
        require_computer_use_scope(share, "observe")
    assert exc.value.status_code == 403


def test_session_control_grant_is_immutable_for_session(tmp_path: Path):
    bridge = CuaDriverBridge(tmp_path, binary_path=str(tmp_path / "missing.exe"))
    bridge._sessions["session-a"] = {"owner": "share:client", "control_allowed": False}
    bridge.start = lambda: {}
    with pytest.raises(CuaDriverError, match="without mouse and keyboard control consent"):
        bridge.call("session-a", "share:client", "click", {"x": 1, "y": 1})


def test_session_is_bound_to_the_creating_client(tmp_path: Path):
    bridge = CuaDriverBridge(tmp_path, binary_path=str(tmp_path / "missing.exe"))
    bridge._sessions["session-a"] = {"owner": "share:client-a", "control_allowed": True}
    bridge.start = lambda: {}
    with pytest.raises(CuaDriverError, match="not found for this client"):
        bridge.call("session-a", "share:client-b", "get_desktop_state", {})


def test_owner_revocation_clears_owned_sessions(tmp_path: Path):
    bridge = CuaDriverBridge(tmp_path, binary_path=str(tmp_path / "missing.exe"))
    bridge._sessions["session-a"] = {"owner": "share:client-a", "control_allowed": False}
    bridge._sessions["session-b"] = {"owner": "share:client-b", "control_allowed": False}
    assert bridge.close_owner("share:client-a") == 1
    assert "session-a" not in bridge._sessions
    assert "session-b" in bridge._sessions


def test_cli_writeback_requires_both_share_and_client_write_grants():
    assert workspace_writeback_allowed({"workspace_write_enabled": False}) is False
    assert workspace_writeback_allowed({
        "workspace_write_enabled": True,
        "_client_permissions": {"write": False, "cli": True},
    }) is False
    assert workspace_writeback_allowed({
        "workspace_write_enabled": True,
        "_client_permissions": {"write": True, "cli": True},
    }) is True
    assert workspace_writeback_allowed({"workspace_write_enabled": True}) is True
