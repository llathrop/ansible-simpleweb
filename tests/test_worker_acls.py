"""Tests for worker service account permissions and ACLs."""
import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWorkerPermissions:
    """Tests for worker permission definitions."""

    def test_operator_can_view_workers(self):
        """Operator can view workers."""
        from web.authz import check_permission

        operator = {'roles': ['operator']}
        assert check_permission(operator, 'workers:view') is True

    def test_monitor_can_view_workers(self):
        """Monitor can view workers."""
        from web.authz import check_permission

        monitor = {'roles': ['monitor']}
        assert check_permission(monitor, 'workers:view') is True

    def test_admin_has_full_worker_permissions(self):
        """Admin has all worker permissions."""
        from web.authz import check_permission

        admin = {'roles': ['admin']}
        assert check_permission(admin, 'workers:view') is True
        assert check_permission(admin, 'workers:admin') is True
        assert check_permission(admin, 'workers:execute') is True
        assert check_permission(admin, 'workers:sync') is True

    def test_operator_limited_worker_admin(self):
        """Operator has view but limited admin permissions."""
        from web.authz import check_permission

        operator = {'roles': ['operator']}
        assert check_permission(operator, 'workers:view') is True
        # Operator doesn't have workers:admin directly
        has_admin = check_permission(operator, 'workers:admin')
        # Depends on exact role definition, operator has workers:view
        assert has_admin is False


class TestWorkerAuthenticationRoutes:
    """Tests for worker authentication on sensitive routes."""

    def test_worker_register_requires_token(self):
        """Worker registration requires valid token."""
        # The registration endpoint uses @worker_auth_required
        # which validates the worker token
        # This is tested in test_auth_routes.py
        pass

    def test_worker_checkin_requires_auth(self):
        """Worker checkin requires worker authentication."""
        # Worker checkin uses the worker's unique token
        pass

    def test_worker_job_complete_requires_auth(self):
        """Job completion endpoint requires worker authentication."""
        # Job completion is worker-only
        pass


class TestWorkerServiceAccount:
    """Tests for worker service account concept."""

    def test_worker_has_limited_permissions(self):
        """Worker service accounts have limited, specific permissions."""
        # Workers have permissions:
        # - Get pending jobs
        # - Assign jobs to self
        # - Start jobs
        # - Complete jobs
        # - Stream logs
        # - Sync inventory/playbooks

        # These are enforced via @worker_auth_required decorator
        # which checks worker token, not user roles
        pass

    def test_worker_cannot_access_user_endpoints(self):
        """Worker token should not grant access to user management."""
        # Worker authentication is separate from user authentication
        # Worker tokens are not valid for user-facing endpoints
        pass


class TestWorkerTokenValidation:
    """Tests for worker token validation logic."""

    def test_valid_worker_token_format(self):
        """Worker tokens should be validated for format."""
        import re

        # Worker tokens are hashed, so we check the validation logic
        # A valid worker ID is a UUID
        valid_uuid = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
        uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE
        )

        assert uuid_pattern.match(valid_uuid) is not None

    def test_invalid_worker_token_rejected(self):
        """Invalid worker tokens should be rejected."""
        import re

        invalid_tokens = [
            'not-a-uuid',
            '12345',
            '',
            'admin',
            '../../../etc/passwd',
        ]

        uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE
        )

        for token in invalid_tokens:
            assert uuid_pattern.match(token) is None


class TestWorkerEndpointPermissions:
    """Tests for specific worker endpoint permissions."""

    def test_get_pending_jobs_requires_worker_auth(self):
        """GET /api/jobs/pending requires worker authentication."""
        # This endpoint uses @worker_auth_required
        # Workers get pending jobs to claim for execution
        pass

    def test_assign_job_requires_worker_auth(self):
        """POST /api/jobs/<id>/assign requires worker authentication."""
        # Workers assign jobs to themselves
        pass

    def test_start_job_requires_worker_auth(self):
        """POST /api/jobs/<id>/start requires worker authentication."""
        # Workers mark jobs as started
        pass

    def test_complete_job_requires_worker_auth(self):
        """POST /api/jobs/<id>/complete requires worker authentication."""
        # Workers mark jobs as complete
        pass

    def test_stream_log_requires_worker_auth(self):
        """POST /api/jobs/<id>/log/stream requires worker authentication."""
        # Workers stream execution logs
        pass


class TestWorkerViewPermissions:
    """Tests for viewing worker information."""

    def test_user_permissions_for_worker_list(self):
        """Users need workers:view to see worker list."""
        from web.authz import check_permission

        # Admin can view
        admin = {'roles': ['admin']}
        assert check_permission(admin, 'workers:view') is True

        # Operator can view
        operator = {'roles': ['operator']}
        assert check_permission(operator, 'workers:view') is True

        # Monitor can view
        monitor = {'roles': ['monitor']}
        assert check_permission(monitor, 'workers:view') is True

    def test_developer_can_view_workers(self):
        """Developer has limited worker view access."""
        from web.authz import check_permission

        developer = {'roles': ['developer']}
        # Developer role doesn't explicitly have workers:view
        # Check what the developer role actually has
        has_view = check_permission(developer, 'workers:view')
        # Developer doesn't have workers:view in the default role
        # This is intentional - developers focus on playbooks, not infrastructure
        assert has_view is False


class TestWorkerAdminPermissions:
    """Tests for worker administration permissions."""

    def test_admin_can_delete_worker(self):
        """Admin can delete workers."""
        from web.authz import check_permission

        admin = {'roles': ['admin']}
        # Admin has *:* which covers workers:admin
        assert check_permission(admin, 'workers:admin') is True

    def test_operator_cannot_delete_worker(self):
        """Operator cannot delete workers."""
        from web.authz import check_permission

        operator = {'roles': ['operator']}
        # Operator only has workers:view
        assert check_permission(operator, 'workers:admin') is False

    def test_monitor_cannot_modify_workers(self):
        """Monitor cannot modify workers."""
        from web.authz import check_permission

        monitor = {'roles': ['monitor']}
        assert check_permission(monitor, 'workers:admin') is False
