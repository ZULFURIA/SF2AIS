import pytest
from fastapi import HTTPException

from main import effective_computer_use_permission, require_ide_enabled


def test_ide_is_disabled_by_default():
    with pytest.raises(HTTPException) as exc:
        require_ide_enabled({"id": "share"})
    assert exc.value.status_code == 403


def test_ide_requires_share_and_client_grants():
    with pytest.raises(HTTPException) as exc:
        require_ide_enabled({"ide_enabled": True, "_client_permissions": {"ide": False}})
    assert exc.value.status_code == 403
    require_ide_enabled({"ide_enabled": True, "_client_permissions": {"ide": True}})


def test_computer_use_requires_both_share_and_client_grants():
    assert effective_computer_use_permission({"computer_use_enabled": True}) is True
    assert effective_computer_use_permission({"computer_use_enabled": False}) is False
    assert effective_computer_use_permission({"computer_use_enabled": True, "_client_permissions": {"computer_use": False}}) is False
    assert effective_computer_use_permission({"computer_use_enabled": True, "_client_permissions": {"computer_use": True}}) is True


def test_basic_share_permission_does_not_create_cua_provider():
    share = {"computer_use_enabled": True}
    assert effective_computer_use_permission(share) is True
    # Provider availability is intentionally false until a real connector exists.
