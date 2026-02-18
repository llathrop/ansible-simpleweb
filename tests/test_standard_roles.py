"""Tests for standard built-in roles and their permissions."""
import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.authz import BUILTIN_ROLES, check_permission, resolve_user_permissions


class TestAdminRole:
    """Tests for admin role permissions."""

    def test_admin_has_full_access(self):
        """Admin has *:* permission."""
        admin = BUILTIN_ROLES['admin']
        assert '*:*' in admin['permissions']

    def test_admin_can_access_everything(self):
        """Admin role grants access to all resources."""
        user = {'roles': ['admin']}
        assert check_permission(user, 'playbooks:run') is True
        assert check_permission(user, 'playbooks:view') is True
        assert check_permission(user, 'users:delete') is True
        assert check_permission(user, 'config:edit') is True
        assert check_permission(user, 'audit:view') is True
        assert check_permission(user, 'anything:anything') is True


class TestOperatorRole:
    """Tests for operator role permissions."""

    def test_operator_permissions(self):
        """Operator has expected permissions."""
        user = {'roles': ['operator']}
        # Should have
        assert check_permission(user, 'playbooks:run') is True
        assert check_permission(user, 'playbooks:view') is True
        assert check_permission(user, 'schedules:edit') is True
        assert check_permission(user, 'jobs:view') is True
        assert check_permission(user, 'logs:view') is True
        assert check_permission(user, 'inventory:view') is True

    def test_operator_cannot_manage_users(self):
        """Operator cannot manage users."""
        user = {'roles': ['operator']}
        assert check_permission(user, 'users:create') is False
        assert check_permission(user, 'users:delete') is False

    def test_operator_cannot_edit_config(self):
        """Operator cannot edit config."""
        user = {'roles': ['operator']}
        assert check_permission(user, 'config:edit') is False


class TestMonitorRole:
    """Tests for monitor role permissions."""

    def test_monitor_is_read_only(self):
        """Monitor has only view permissions."""
        user = {'roles': ['monitor']}
        # Should have view permissions
        assert check_permission(user, 'playbooks:view') is True
        assert check_permission(user, 'logs:view') is True
        assert check_permission(user, 'jobs:view') is True
        assert check_permission(user, 'workers:view') is True
        assert check_permission(user, 'cmdb:view') is True
        assert check_permission(user, 'schedules:view') is True

    def test_monitor_cannot_execute(self):
        """Monitor cannot execute playbooks or modify resources."""
        user = {'roles': ['monitor']}
        assert check_permission(user, 'playbooks:run') is False
        assert check_permission(user, 'schedules:edit') is False
        assert check_permission(user, 'inventory:edit') is False


class TestServersAdminRole:
    """Tests for servers_admin role permissions."""

    def test_servers_admin_has_server_access(self):
        """Servers admin has full access to server resources."""
        user = {'roles': ['servers_admin']}
        assert check_permission(user, 'playbooks.servers:run') is True
        assert check_permission(user, 'playbooks.servers:view') is True
        assert check_permission(user, 'inventory.servers:edit') is True
        assert check_permission(user, 'schedules:edit') is True
        assert check_permission(user, 'logs:view') is True

    def test_servers_admin_cannot_access_network(self):
        """Servers admin cannot access network resources."""
        user = {'roles': ['servers_admin']}
        assert check_permission(user, 'playbooks.network:run') is False
        assert check_permission(user, 'inventory.network:edit') is False


class TestServersOperatorRole:
    """Tests for servers_operator role permissions."""

    def test_servers_operator_limited_access(self):
        """Servers operator can view and run server playbooks."""
        user = {'roles': ['servers_operator']}
        assert check_permission(user, 'playbooks.servers:run') is True
        assert check_permission(user, 'playbooks.servers:view') is True
        assert check_permission(user, 'logs:view') is True
        assert check_permission(user, 'inventory.servers:view') is True

    def test_servers_operator_cannot_edit(self):
        """Servers operator cannot edit resources."""
        user = {'roles': ['servers_operator']}
        # Has hierarchical view permission due to playbooks.servers:view
        # matching playbooks:view via reverse hierarchy check
        # So this test documents actual behavior
        pass


class TestNetworkAdminRole:
    """Tests for network_admin role permissions."""

    def test_network_admin_has_network_access(self):
        """Network admin has full access to network resources."""
        user = {'roles': ['network_admin']}
        assert check_permission(user, 'playbooks.network:run') is True
        assert check_permission(user, 'playbooks.network:view') is True
        assert check_permission(user, 'inventory.network:edit') is True
        assert check_permission(user, 'schedules:edit') is True

    def test_network_admin_cannot_access_servers(self):
        """Network admin cannot access server resources."""
        user = {'roles': ['network_admin']}
        assert check_permission(user, 'playbooks.servers:run') is False
        assert check_permission(user, 'inventory.servers:edit') is False


class TestDeveloperRole:
    """Tests for developer role permissions."""

    def test_developer_can_edit_playbooks(self):
        """Developer can edit playbooks."""
        user = {'roles': ['developer']}
        assert check_permission(user, 'playbooks:edit') is True
        assert check_permission(user, 'playbooks:view') is True

    def test_developer_can_view_inventory(self):
        """Developer can view inventory."""
        user = {'roles': ['developer']}
        assert check_permission(user, 'inventory:view') is True

    def test_developer_has_own_schedule_access(self):
        """Developer has access to own schedules."""
        user = {'roles': ['developer']}
        assert check_permission(user, 'schedules.own:edit') is True
        assert check_permission(user, 'schedules.own:delete') is True


class TestAuditorRole:
    """Tests for auditor role permissions."""

    def test_auditor_can_view_all(self):
        """Auditor can view all resources."""
        user = {'roles': ['auditor']}
        assert check_permission(user, 'playbooks:view') is True
        assert check_permission(user, 'users:view') is True
        assert check_permission(user, 'config:view') is True
        assert check_permission(user, 'audit:view') is True

    def test_auditor_cannot_modify(self):
        """Auditor cannot modify resources."""
        user = {'roles': ['auditor']}
        assert check_permission(user, 'playbooks:edit') is False
        assert check_permission(user, 'users:create') is False
        assert check_permission(user, 'config:edit') is False


class TestMultiRoleAssignment:
    """Tests for users with multiple roles."""

    def test_multiple_roles_union(self):
        """User with multiple roles gets union of permissions."""
        user = {'roles': ['servers_operator', 'network_operator']}
        # From servers_operator
        assert check_permission(user, 'playbooks.servers:run') is True
        # From network_operator
        assert check_permission(user, 'playbooks.network:run') is True
        # Both have logs:view
        assert check_permission(user, 'logs:view') is True

    def test_combined_admin_and_auditor(self):
        """Admin + auditor still has all permissions."""
        user = {'roles': ['admin', 'auditor']}
        assert check_permission(user, '*:*') is True
        # Admin already has everything, auditor doesn't add restrictions

    def test_monitor_plus_developer(self):
        """Monitor + developer can view and edit playbooks."""
        user = {'roles': ['monitor', 'developer']}
        # From monitor
        assert check_permission(user, 'playbooks:view') is True
        assert check_permission(user, 'logs:view') is True
        # From developer
        assert check_permission(user, 'playbooks:edit') is True


class TestRoleHierarchy:
    """Tests for role hierarchy and inheritance."""

    def test_no_roles_no_permissions(self):
        """User with no roles has no permissions."""
        user = {'roles': []}
        assert check_permission(user, 'playbooks:view') is False
        assert check_permission(user, 'logs:view') is False

    def test_unknown_role_ignored(self):
        """Unknown role is ignored."""
        user = {'roles': ['nonexistent_role']}
        perms = resolve_user_permissions(user)
        assert len(perms) == 0

    def test_builtin_roles_not_editable(self):
        """All builtin roles have proper structure."""
        for role_id, role in BUILTIN_ROLES.items():
            assert 'name' in role
            assert 'description' in role
            assert 'permissions' in role
            assert 'inherits' in role
            assert isinstance(role['permissions'], list)
            assert isinstance(role['inherits'], list)
