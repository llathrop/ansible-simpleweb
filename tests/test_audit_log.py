"""
Tests for Audit Logging - Phase 1.4

Tests:
- Audit entry creation and storage
- Audit log filtering and pagination
- Audit log export
- Audit statistics
- Security event logging (login/logout, failed attempts)
"""

import pytest
import tempfile
import os
import sys
import json
import uuid
from datetime import datetime, timezone, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, g, jsonify
from web.storage.flatfile import FlatFileStorage
from web.auth import hash_password
from web.auth_routes import (
    auth_bp,
    init_auth_middleware,
    add_audit_entry,
    audit_action,
    require_permission
)


@pytest.fixture
def storage_with_audit():
    """Create a storage backend with audit log capabilities."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FlatFileStorage(config_dir=tmpdir)
        yield storage


@pytest.fixture
def app_with_audit():
    """Create a test Flask app with audit capabilities."""
    template_dir = os.path.join(os.path.dirname(__file__), '..', 'web', 'templates')

    app = Flask(__name__, template_folder=template_dir)
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['TESTING'] = True

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FlatFileStorage(config_dir=tmpdir)

        # Reset state
        from web.auth import login_tracker, session_manager
        login_tracker.attempts.clear()
        login_tracker.lockouts.clear()
        session_manager.sessions.clear()

        # Create admin user
        admin_id = str(uuid.uuid4())
        admin_user = {
            'id': admin_id,
            'username': 'admin',
            'password_hash': hash_password('adminpass'),
            'email': 'admin@example.com',
            'roles': ['admin'],
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_user('admin', admin_user)

        # Create auditor user (can view audit logs)
        auditor_id = str(uuid.uuid4())
        auditor_user = {
            'id': auditor_id,
            'username': 'auditor',
            'password_hash': hash_password('auditorpass'),
            'email': 'auditor@example.com',
            'roles': ['auditor'],
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_user('auditor', auditor_user)

        # Create operator user (cannot view audit logs)
        operator_id = str(uuid.uuid4())
        operator_user = {
            'id': operator_id,
            'username': 'operator',
            'password_hash': hash_password('operatorpass'),
            'email': 'operator@example.com',
            'roles': ['operator'],
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_user('operator', operator_user)

        # Register auth blueprint
        app.register_blueprint(auth_bp)

        # Add a test route with audit decorator
        @app.route('/api/test-action', methods=['POST'])
        @require_permission('playbooks:run')
        @audit_action('execute', 'playbooks', lambda a, k: 'test-playbook')
        def test_audited_action():
            return jsonify({'ok': True})

        # Initialize auth middleware
        init_auth_middleware(app, storage, auth_enabled=True)

        yield app, storage, {
            'admin': admin_user,
            'auditor': auditor_user,
            'operator': operator_user
        }


@pytest.fixture
def admin_client(app_with_audit):
    """Create test client logged in as admin."""
    app, storage, users = app_with_audit
    client = app.test_client()
    client.post('/api/auth/login',
                json={'username': 'admin', 'password': 'adminpass'},
                content_type='application/json')
    return client


@pytest.fixture
def auditor_client(app_with_audit):
    """Create test client logged in as auditor."""
    app, storage, users = app_with_audit
    client = app.test_client()
    client.post('/api/auth/login',
                json={'username': 'auditor', 'password': 'auditorpass'},
                content_type='application/json')
    return client


@pytest.fixture
def operator_client(app_with_audit):
    """Create test client logged in as operator."""
    app, storage, users = app_with_audit
    client = app.test_client()
    client.post('/api/auth/login',
                json={'username': 'operator', 'password': 'operatorpass'},
                content_type='application/json')
    return client


class TestAuditEntryCreation:
    """Tests for creating audit log entries."""

    def test_add_audit_entry(self, storage_with_audit):
        """Should add audit entry to storage."""
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'user': 'testuser',
            'user_id': 'user-123',
            'action': 'login',
            'resource': 'auth',
            'resource_id': None,
            'details': {},
            'ip_address': '127.0.0.1',
            'user_agent': 'test-agent',
            'success': True
        }

        result = storage_with_audit.add_audit_entry(entry)
        assert result is True

        # Verify entry was stored
        entries = storage_with_audit.get_audit_log()
        assert len(entries) == 1
        assert entries[0]['user'] == 'testuser'
        assert entries[0]['action'] == 'login'

    def test_audit_entry_auto_timestamp(self, storage_with_audit):
        """Should auto-add timestamp if not provided."""
        entry = {
            'user': 'testuser',
            'action': 'create',
            'resource': 'users',
            'success': True
        }

        storage_with_audit.add_audit_entry(entry)

        entries = storage_with_audit.get_audit_log()
        assert len(entries) == 1
        assert 'timestamp' in entries[0]

    def test_multiple_audit_entries(self, storage_with_audit):
        """Should store multiple entries in order (newest first)."""
        for i in range(5):
            entry = {
                'user': f'user{i}',
                'action': 'view',
                'resource': 'playbooks',
                'success': True
            }
            storage_with_audit.add_audit_entry(entry)

        entries = storage_with_audit.get_audit_log()
        assert len(entries) == 5
        # Newest first
        assert entries[0]['user'] == 'user4'
        assert entries[4]['user'] == 'user0'


class TestAuditLogFiltering:
    """Tests for filtering audit log entries."""

    def test_filter_by_user(self, storage_with_audit):
        """Should filter entries by username."""
        storage_with_audit.add_audit_entry({'user': 'alice', 'action': 'login', 'resource': 'auth', 'success': True})
        storage_with_audit.add_audit_entry({'user': 'bob', 'action': 'login', 'resource': 'auth', 'success': True})
        storage_with_audit.add_audit_entry({'user': 'alice', 'action': 'view', 'resource': 'playbooks', 'success': True})

        entries = storage_with_audit.get_audit_log(filters={'user': 'alice'})
        assert len(entries) == 2
        assert all(e['user'] == 'alice' for e in entries)

    def test_filter_by_action(self, storage_with_audit):
        """Should filter entries by action."""
        storage_with_audit.add_audit_entry({'user': 'test', 'action': 'login', 'resource': 'auth', 'success': True})
        storage_with_audit.add_audit_entry({'user': 'test', 'action': 'create', 'resource': 'users', 'success': True})
        storage_with_audit.add_audit_entry({'user': 'test', 'action': 'login', 'resource': 'auth', 'success': True})

        entries = storage_with_audit.get_audit_log(filters={'action': 'login'})
        assert len(entries) == 2
        assert all(e['action'] == 'login' for e in entries)

    def test_filter_by_resource(self, storage_with_audit):
        """Should filter entries by resource."""
        storage_with_audit.add_audit_entry({'user': 'test', 'action': 'view', 'resource': 'playbooks', 'success': True})
        storage_with_audit.add_audit_entry({'user': 'test', 'action': 'view', 'resource': 'users', 'success': True})
        storage_with_audit.add_audit_entry({'user': 'test', 'action': 'run', 'resource': 'playbooks', 'success': True})

        entries = storage_with_audit.get_audit_log(filters={'resource': 'playbooks'})
        assert len(entries) == 2
        assert all(e['resource'] == 'playbooks' for e in entries)

    def test_filter_by_success(self, storage_with_audit):
        """Should filter entries by success status."""
        storage_with_audit.add_audit_entry({'user': 'test', 'action': 'login', 'resource': 'auth', 'success': True})
        storage_with_audit.add_audit_entry({'user': 'test', 'action': 'login', 'resource': 'auth', 'success': False})
        storage_with_audit.add_audit_entry({'user': 'test', 'action': 'login', 'resource': 'auth', 'success': True})

        # Filter failures
        failures = storage_with_audit.get_audit_log(filters={'success': False})
        assert len(failures) == 1
        assert failures[0]['success'] is False

        # Filter successes
        successes = storage_with_audit.get_audit_log(filters={'success': True})
        assert len(successes) == 2


class TestAuditLogPagination:
    """Tests for audit log pagination."""

    def test_limit_entries(self, storage_with_audit):
        """Should limit number of returned entries."""
        for i in range(20):
            storage_with_audit.add_audit_entry({
                'user': f'user{i}',
                'action': 'view',
                'resource': 'playbooks',
                'success': True
            })

        entries = storage_with_audit.get_audit_log(limit=5)
        assert len(entries) == 5

    def test_offset_entries(self, storage_with_audit):
        """Should offset entries correctly."""
        for i in range(10):
            storage_with_audit.add_audit_entry({
                'user': f'user{i}',
                'action': 'view',
                'resource': 'playbooks',
                'success': True
            })

        # Skip first 5 entries
        entries = storage_with_audit.get_audit_log(limit=5, offset=5)
        assert len(entries) == 5
        # Should get user4 through user0 (oldest 5)
        assert entries[0]['user'] == 'user4'

    def test_pagination_with_filters(self, storage_with_audit):
        """Should paginate filtered results."""
        for i in range(20):
            storage_with_audit.add_audit_entry({
                'user': 'alice' if i % 2 == 0 else 'bob',
                'action': 'view',
                'resource': 'playbooks',
                'success': True
            })

        # Get page 1 of alice's entries
        entries = storage_with_audit.get_audit_log(
            filters={'user': 'alice'},
            limit=3,
            offset=0
        )
        assert len(entries) == 3
        assert all(e['user'] == 'alice' for e in entries)


class TestAuditLogAPI:
    """Tests for audit log API endpoints."""

    def test_admin_can_view_audit_log(self, admin_client, app_with_audit):
        """Admin should access audit log."""
        response = admin_client.get('/api/audit')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'entries' in data
        assert 'total' in data

    def test_auditor_can_view_audit_log(self, auditor_client, app_with_audit):
        """Auditor should access audit log."""
        response = auditor_client.get('/api/audit')
        assert response.status_code == 200

    def test_operator_cannot_view_audit_log(self, operator_client):
        """Operator should not access audit log."""
        response = operator_client.get('/api/audit')
        assert response.status_code == 403

    def test_audit_page_requires_auth(self, app_with_audit):
        """Audit page should require authentication."""
        app, storage, users = app_with_audit
        client = app.test_client()

        response = client.get('/audit')
        # Should redirect to login or return 401
        assert response.status_code in [302, 401]

    def test_audit_api_filtering(self, admin_client, app_with_audit):
        """Should filter audit entries via API."""
        app, storage, users = app_with_audit

        # Add some entries directly
        storage.add_audit_entry({
            'user': 'alice',
            'action': 'login',
            'resource': 'auth',
            'success': True
        })
        storage.add_audit_entry({
            'user': 'bob',
            'action': 'create',
            'resource': 'users',
            'success': True
        })

        # Filter by user
        response = admin_client.get('/api/audit?user=alice')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert all(e['user'] == 'alice' for e in data['entries'] if e.get('user'))


class TestAuditLogExport:
    """Tests for audit log CSV export."""

    def test_export_csv(self, admin_client, app_with_audit):
        """Should export audit log as CSV."""
        app, storage, users = app_with_audit

        # Add some entries
        storage.add_audit_entry({
            'user': 'testuser',
            'action': 'login',
            'resource': 'auth',
            'success': True,
            'ip_address': '192.168.1.1'
        })

        response = admin_client.get('/api/audit/export')
        assert response.status_code == 200
        assert response.content_type == 'text/csv'

        # Check CSV headers
        content = response.data.decode('utf-8')
        assert 'Timestamp' in content
        assert 'User' in content
        assert 'Action' in content

    def test_export_csv_requires_permission(self, operator_client):
        """Export should require audit:view permission."""
        response = operator_client.get('/api/audit/export')
        assert response.status_code == 403


class TestAuditLogStats:
    """Tests for audit log statistics."""

    def test_get_stats(self, admin_client, app_with_audit):
        """Should return audit statistics."""
        app, storage, users = app_with_audit

        # Add various entries
        storage.add_audit_entry({'user': 'alice', 'action': 'login', 'resource': 'auth', 'success': True})
        storage.add_audit_entry({'user': 'bob', 'action': 'login', 'resource': 'auth', 'success': True})
        storage.add_audit_entry({'user': 'alice', 'action': 'failed_login', 'resource': 'auth', 'success': False})

        response = admin_client.get('/api/audit/stats')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'total_entries' in data
        assert 'by_action' in data
        assert 'by_resource' in data
        assert 'success_count' in data
        assert 'failure_count' in data


class TestAuditDecorator:
    """Tests for @audit_action decorator."""

    def test_successful_action_logged(self, admin_client, app_with_audit):
        """Successful actions should be logged."""
        app, storage, users = app_with_audit

        # Execute audited action
        response = admin_client.post('/api/test-action',
                                     json={},
                                     content_type='application/json')
        assert response.status_code == 200

        # Check audit log
        entries = storage.get_audit_log(filters={'action': 'execute'})
        assert len(entries) >= 1
        assert entries[0]['resource'] == 'playbooks'
        assert entries[0]['success'] is True


class TestLoginAuditLogging:
    """Tests for login/logout audit logging."""

    def test_successful_login_logged(self, app_with_audit):
        """Successful login should be logged."""
        app, storage, users = app_with_audit
        client = app.test_client()

        # Login
        response = client.post('/api/auth/login',
                               json={'username': 'admin', 'password': 'adminpass'},
                               content_type='application/json')
        assert response.status_code == 200

        # Check audit log for login entry
        # Note: At login time, the user is identified by resource_id since
        # g.current_user is not yet set when the audit entry is created
        entries = storage.get_audit_log(filters={'action': 'login'})
        login_entries = [e for e in entries if e.get('resource_id') == 'admin']
        assert len(login_entries) >= 1
        assert login_entries[0]['success'] is True

    def test_failed_login_logged(self, app_with_audit):
        """Failed login should be logged."""
        app, storage, users = app_with_audit
        client = app.test_client()

        # Attempt login with wrong password
        response = client.post('/api/auth/login',
                               json={'username': 'admin', 'password': 'wrongpassword'},
                               content_type='application/json')
        assert response.status_code == 401

        # Check audit log for failed login entry
        entries = storage.get_audit_log(filters={'action': 'failed_login'})
        failed_entries = [e for e in entries if e.get('resource_id') == 'admin']
        assert len(failed_entries) >= 1
        assert failed_entries[0]['success'] is False


class TestAuditSecurityMonitoring:
    """Tests for security monitoring via audit log."""

    def test_multiple_failed_logins_tracked(self, app_with_audit):
        """Multiple failed logins should be tracked in audit log."""
        app, storage, users = app_with_audit
        client = app.test_client()

        # Make multiple failed login attempts
        for _ in range(3):
            client.post('/api/auth/login',
                        json={'username': 'admin', 'password': 'wrong'},
                        content_type='application/json')

        entries = storage.get_audit_log(filters={'action': 'failed_login'})
        failed_entries = [e for e in entries if e.get('resource_id') == 'admin']
        assert len(failed_entries) >= 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
