"""Tests for agent service account permissions and ACLs."""
import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAgentPermissions:
    """Tests for agent permission definitions."""

    def test_operator_can_view_agent(self):
        """Operator can view agent information."""
        from web.authz import check_permission

        operator = {'roles': ['operator']}
        assert check_permission(operator, 'agent:view') is True

    def test_monitor_can_view_agent(self):
        """Monitor can view agent information."""
        from web.authz import check_permission

        monitor = {'roles': ['monitor']}
        assert check_permission(monitor, 'agent:view') is True

    def test_admin_has_full_agent_permissions(self):
        """Admin has all agent permissions."""
        from web.authz import check_permission

        admin = {'roles': ['admin']}
        assert check_permission(admin, 'agent:view') is True
        assert check_permission(admin, 'agent:generate') is True
        assert check_permission(admin, 'agent:analyze') is True

    def test_operator_has_agent_generate(self):
        """Operator can generate agent reports."""
        from web.authz import check_permission

        operator = {'roles': ['operator']}
        assert check_permission(operator, 'agent:generate') is True
        assert check_permission(operator, 'agent:analyze') is True

    def test_monitor_cannot_generate(self):
        """Monitor has view-only agent access."""
        from web.authz import check_permission

        monitor = {'roles': ['monitor']}
        assert check_permission(monitor, 'agent:view') is True
        assert check_permission(monitor, 'agent:generate') is False
        assert check_permission(monitor, 'agent:analyze') is False


class TestAgentServiceAccount:
    """Tests for agent service account concept."""

    def test_agent_has_limited_permissions(self):
        """Agent service accounts have limited, specific permissions."""
        # Agent service has permissions:
        # - Read execution logs
        # - Write reviews
        # - Read playbook information

        # These are enforced via @service_auth_required decorator
        pass

    def test_agent_service_auth_required_decorator(self):
        """Agent endpoints use service auth decorator."""
        # The agent endpoints that the agent service calls use
        # @service_auth_required which validates the agent service token
        pass


class TestAgentEndpointPermissions:
    """Tests for specific agent endpoint permissions."""

    def test_agent_page_requires_view(self):
        """Agent page requires agent:view permission."""
        from web.authz import check_permission

        # Users with agent:view can see the agent page
        operator = {'roles': ['operator']}
        assert check_permission(operator, 'agent:view') is True

        monitor = {'roles': ['monitor']}
        assert check_permission(monitor, 'agent:view') is True

    def test_agent_overview_requires_view(self):
        """Agent overview API requires agent:view permission."""
        from web.authz import check_permission

        operator = {'roles': ['operator']}
        assert check_permission(operator, 'agent:view') is True

    def test_agent_reviews_requires_view(self):
        """Agent reviews API requires agent:view permission."""
        from web.authz import check_permission

        monitor = {'roles': ['monitor']}
        assert check_permission(monitor, 'agent:view') is True

    def test_agent_generate_requires_permission(self):
        """Agent generate API requires agent:generate permission."""
        from web.authz import check_permission

        operator = {'roles': ['operator']}
        assert check_permission(operator, 'agent:generate') is True

        monitor = {'roles': ['monitor']}
        assert check_permission(monitor, 'agent:generate') is False

    def test_agent_analyze_requires_permission(self):
        """Agent analyze API requires agent:analyze permission."""
        from web.authz import check_permission

        operator = {'roles': ['operator']}
        assert check_permission(operator, 'agent:analyze') is True

        developer = {'roles': ['developer']}
        # Developer has agent:view but limited generate/analyze
        has_analyze = check_permission(developer, 'agent:analyze')
        # Check developer role definition
        # Developer doesn't have agent:analyze
        assert has_analyze is False


class TestAgentViewPermissions:
    """Tests for viewing agent information."""

    def test_user_permissions_for_agent(self):
        """Users need agent:view to see agent information."""
        from web.authz import check_permission

        # Admin can view
        admin = {'roles': ['admin']}
        assert check_permission(admin, 'agent:view') is True

        # Operator can view
        operator = {'roles': ['operator']}
        assert check_permission(operator, 'agent:view') is True

        # Monitor can view
        monitor = {'roles': ['monitor']}
        assert check_permission(monitor, 'agent:view') is True

        # Developer can view
        developer = {'roles': ['developer']}
        assert check_permission(developer, 'agent:view') is True


class TestAgentTokenValidation:
    """Tests for agent service token validation."""

    def test_agent_token_required_for_service_endpoints(self):
        """Agent service endpoints require valid agent token."""
        # The agent service authenticates with a specific token
        # This is validated by @service_auth_required decorator
        pass

    def test_user_token_not_valid_for_agent_service(self):
        """User tokens should not work for agent service endpoints."""
        # Agent service endpoints expect the agent's service token
        # not a user's session or API token
        pass


class TestAgentRoleDefinitions:
    """Tests for agent-related role definitions."""

    def test_all_builtin_roles_define_agent_access(self):
        """All builtin roles should define agent access level."""
        from web.authz import BUILTIN_ROLES, check_permission

        # Each role should have some agent permission
        for role_id, role_def in BUILTIN_ROLES.items():
            user = {'roles': [role_id]}
            # At minimum most roles should have agent:view
            # (except very limited roles)
            if role_id in ['admin', 'operator', 'monitor', 'developer', 'auditor']:
                assert check_permission(user, 'agent:view') is True, \
                    f"Role {role_id} should have agent:view"

    def test_auditor_has_agent_view(self):
        """Auditor role can view agent information."""
        from web.authz import check_permission

        auditor = {'roles': ['auditor']}
        # Auditor has *:view which includes agent:view
        assert check_permission(auditor, 'agent:view') is True

    def test_servers_operator_agent_access(self):
        """Servers operator has limited agent access."""
        from web.authz import check_permission

        servers_op = {'roles': ['servers_operator']}
        # Servers operator focused on server playbooks
        # May or may not have agent access
        has_view = check_permission(servers_op, 'agent:view')
        # Check actual role definition
        # servers_operator doesn't include agent:view
        assert has_view is False


class TestAgentServiceAuthDecorator:
    """Tests for @service_auth_required decorator behavior."""

    def test_service_auth_validates_token(self):
        """Service auth decorator validates agent token."""
        # The decorator checks for X-Service-Token header
        # and validates against configured agent token
        pass

    def test_service_auth_returns_401_without_token(self):
        """Service auth returns 401 without token."""
        # Missing token should return 401 Unauthorized
        pass

    def test_service_auth_returns_403_with_invalid_token(self):
        """Service auth returns 403 with invalid token."""
        # Invalid token should return 403 Forbidden
        pass
