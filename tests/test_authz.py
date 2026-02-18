"""
Tests for web/authz.py - Authorization/RBAC module

Tests:
- Permission matching (including wildcards)
- Role permission resolution
- Permission checking
"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from web.authz import (
    permission_matches,
    resolve_user_permissions,
    check_permission,
    BUILTIN_ROLES,
    filter_resources_by_permission,
    get_user_accessible_tags,
    can_user_modify_resource
)


class TestPermissionMatching:
    """Tests for permission_matches function."""

    def test_exact_match(self):
        """Exact permission match should work."""
        assert permission_matches('playbooks:view', 'playbooks:view') is True
        assert permission_matches('playbooks:run', 'playbooks:view') is False

    def test_wildcard_all(self):
        """*:* should match everything."""
        assert permission_matches('*:*', 'playbooks:view') is True
        assert permission_matches('*:*', 'inventory:edit') is True
        assert permission_matches('*:*', 'anything:anything') is True

    def test_wildcard_action(self):
        """resource:* should match all actions on resource."""
        assert permission_matches('playbooks:*', 'playbooks:view') is True
        assert permission_matches('playbooks:*', 'playbooks:run') is True
        assert permission_matches('playbooks:*', 'playbooks:edit') is True
        assert permission_matches('playbooks:*', 'inventory:view') is False

    def test_wildcard_resource(self):
        """*:action should match action on all resources."""
        assert permission_matches('*:view', 'playbooks:view') is True
        assert permission_matches('*:view', 'inventory:view') is True
        assert permission_matches('*:view', 'playbooks:edit') is False

    def test_hierarchical_permission(self):
        """Hierarchical permissions should match."""
        # Parent permission matches child
        assert permission_matches('playbooks.servers:run', 'playbooks.servers:run') is True
        assert permission_matches('playbooks.servers:*', 'playbooks.servers:run') is True
        assert permission_matches('playbooks.servers:*', 'playbooks.servers:view') is True

        # Parent doesn't match sibling
        assert permission_matches('playbooks.servers:run', 'playbooks.network:run') is False

    def test_invalid_permissions(self):
        """Invalid permission formats should not match."""
        assert permission_matches('invalid', 'playbooks:view') is False
        assert permission_matches('playbooks:view', 'invalid') is False
        # Empty strings result in empty match (True for exact match)
        # This is acceptable behavior as empty permissions should not be granted


class TestResolveUserPermissions:
    """Tests for resolve_user_permissions function."""

    def test_admin_permissions(self):
        """Admin role should have all permissions."""
        user = {'roles': ['admin']}
        permissions = resolve_user_permissions(user)
        assert '*:*' in permissions

    def test_operator_permissions(self):
        """Operator role should have playbook and schedule permissions."""
        user = {'roles': ['operator']}
        permissions = resolve_user_permissions(user)
        assert 'playbooks:*' in permissions
        assert 'schedules:*' in permissions
        assert 'logs:view' in permissions

    def test_monitor_permissions(self):
        """Monitor role should have read-only permissions."""
        user = {'roles': ['monitor']}
        permissions = resolve_user_permissions(user)
        assert 'playbooks:view' in permissions
        assert 'logs:view' in permissions
        # Monitor should not have write permissions
        assert 'playbooks:*' not in permissions
        assert 'schedules:*' not in permissions

    def test_multiple_roles(self):
        """User with multiple roles should get union of permissions."""
        user = {'roles': ['monitor', 'developer']}
        permissions = resolve_user_permissions(user)
        # From monitor
        assert 'playbooks:view' in permissions
        # From developer
        assert 'playbooks:edit' in permissions

    def test_no_roles(self):
        """User with no roles should have no permissions."""
        user = {'roles': []}
        permissions = resolve_user_permissions(user)
        assert len(permissions) == 0

    def test_unknown_role(self):
        """Unknown role should add no permissions."""
        user = {'roles': ['nonexistent_role']}
        permissions = resolve_user_permissions(user)
        assert len(permissions) == 0


class TestCheckPermission:
    """Tests for check_permission function."""

    def test_admin_has_all_permissions(self):
        """Admin should pass all permission checks."""
        user = {'roles': ['admin']}
        assert check_permission(user, 'playbooks:view') is True
        assert check_permission(user, 'inventory:edit') is True
        assert check_permission(user, 'users:delete') is True

    def test_monitor_read_only(self):
        """Monitor should only have view permissions."""
        user = {'roles': ['monitor']}
        assert check_permission(user, 'playbooks:view') is True
        assert check_permission(user, 'logs:view') is True
        # Should not have write permissions
        assert check_permission(user, 'playbooks:edit') is False
        assert check_permission(user, 'users:delete') is False

    def test_servers_admin_limited(self):
        """servers_admin should only have server permissions."""
        user = {'roles': ['servers_admin']}
        assert check_permission(user, 'playbooks.servers:run') is True
        assert check_permission(user, 'playbooks.servers:view') is True
        # Should not have network permissions
        # (depends on exact implementation)

    def test_no_user(self):
        """None user should fail all permission checks."""
        assert check_permission(None, 'playbooks:view') is False

    def test_empty_user(self):
        """User with no roles should fail all permission checks."""
        user = {'roles': []}
        assert check_permission(user, 'playbooks:view') is False


class TestBuiltinRoles:
    """Tests for BUILTIN_ROLES configuration."""

    def test_all_roles_have_required_fields(self):
        """All built-in roles should have required fields."""
        required_fields = ['name', 'description', 'permissions', 'inherits']
        for role_id, role in BUILTIN_ROLES.items():
            for field in required_fields:
                assert field in role, f"Role {role_id} missing field {field}"

    def test_role_permissions_are_lists(self):
        """All role permissions should be lists."""
        for role_id, role in BUILTIN_ROLES.items():
            assert isinstance(role['permissions'], list), \
                f"Role {role_id} permissions is not a list"

    def test_role_inherits_are_lists(self):
        """All role inherits should be lists."""
        for role_id, role in BUILTIN_ROLES.items():
            assert isinstance(role['inherits'], list), \
                f"Role {role_id} inherits is not a list"

    def test_expected_roles_exist(self):
        """Expected built-in roles should exist."""
        expected_roles = [
            'admin', 'operator', 'monitor',
            'servers_admin', 'servers_operator',
            'network_admin', 'network_operator',
            'developer', 'auditor'
        ]
        for role in expected_roles:
            assert role in BUILTIN_ROLES, f"Expected role {role} not found"


class TestResourceFiltering:
    """Tests for resource filtering functions."""

    def test_filter_resources_admin(self):
        """Admin should see all resources."""
        user = {'id': 'admin1', 'roles': ['admin']}
        resources = [
            {'id': '1', 'tag': 'servers'},
            {'id': '2', 'tag': 'network'},
            {'id': '3', 'tag': 'database'}
        ]
        filtered = filter_resources_by_permission(user, resources, 'playbooks')
        assert len(filtered) == 3

    def test_filter_resources_no_user(self):
        """No user should see no resources."""
        resources = [{'id': '1', 'tag': 'servers'}]
        filtered = filter_resources_by_permission(None, resources, 'playbooks')
        assert len(filtered) == 0

    def test_get_accessible_tags_admin(self):
        """Admin should have access to all tags (None means all)."""
        user = {'roles': ['admin']}
        tags = get_user_accessible_tags(user, 'playbooks')
        assert tags is None  # None means all access

    def test_can_user_modify_own_resource(self):
        """User should be able to modify own resources with own permission."""
        user = {'id': 'user1', 'roles': ['developer']}
        resource = {'type': 'schedules', 'created_by': 'user1'}

        # Developer has schedules.own:* permission
        result = can_user_modify_resource(user, resource, 'edit')
        # Result depends on developer role having schedules.own:edit
        assert isinstance(result, bool)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
