"""RBAC catalogue invariants.

The matrix is the contract between the API guards and the UI. These tests fail
as soon as a role silently gains or loses a privilege during a refactor.
"""

from __future__ import annotations

import pytest

from app.models.enums import RoleName
from app.rbac.permissions import (
    ADMIN,
    AUDITOR,
    OPERATOR,
    READ_ONLY,
    ROLE_MATRIX,
    SUPER_ADMIN,
    TENANT_ADMIN,
    P,
    permissions_for,
    role_descriptions,
)


def test_every_role_has_a_matrix_entry() -> None:
    assert set(ROLE_MATRIX) == set(RoleName)


def test_super_admin_owns_every_permission() -> None:
    assert frozenset(P) == SUPER_ADMIN
    assert permissions_for(RoleName.SUPER_ADMIN) == sorted(permission.value for permission in P)


def test_role_hierarchy_is_monotonic() -> None:
    assert READ_ONLY < AUDITOR
    assert READ_ONLY <= OPERATOR
    assert READ_ONLY < OPERATOR
    assert OPERATOR < ADMIN
    assert ADMIN < TENANT_ADMIN
    assert TENANT_ADMIN < SUPER_ADMIN


def test_read_only_cannot_mutate() -> None:
    write_suffixes = (":write", ":delete", ":exec", ":deploy", ":approve", ":restore", ":run", ":ack")
    assert not [permission for permission in READ_ONLY if permission.value.endswith(write_suffixes)]


def test_auditor_reads_audit_but_not_devices_state_changes() -> None:
    assert P.AUDIT_READ in AUDITOR
    assert P.DEVICE_WRITE not in AUDITOR
    assert P.USER_WRITE not in AUDITOR


def test_operator_can_execute_but_not_delete_devices() -> None:
    assert P.DEVICE_EXEC in OPERATOR
    assert P.DEVICE_WRITE in OPERATOR
    assert P.DEVICE_DELETE not in OPERATOR


def test_admin_can_manage_policies_but_not_tenants() -> None:
    assert P.POLICY_DEPLOY in ADMIN
    assert P.POLICY_APPROVE in ADMIN
    assert P.TENANT_WRITE not in ADMIN


def test_tenant_admin_can_manage_users_but_not_platform() -> None:
    assert P.TENANT_WRITE in TENANT_ADMIN
    assert P.USER_DELETE in TENANT_ADMIN
    assert P.PLATFORM_SETTINGS not in TENANT_ADMIN
    assert P.LICENSE_MANAGE not in TENANT_ADMIN


def test_only_super_admin_has_platform_privileges() -> None:
    for role, permissions in ROLE_MATRIX.items():
        if role is RoleName.SUPER_ADMIN:
            continue
        assert P.PLATFORM_SETTINGS not in permissions
        assert P.LICENSE_MANAGE not in permissions


@pytest.mark.parametrize("role", list(RoleName))
def test_permissions_for_is_sorted_and_unique(role: RoleName) -> None:
    values = permissions_for(role)
    assert values == sorted(set(values))
    assert all(isinstance(value, str) for value in values)


def test_role_descriptions_cover_every_role() -> None:
    descriptions = role_descriptions()
    assert set(descriptions) == set(RoleName)
    assert all(text.strip() for text in descriptions.values())
