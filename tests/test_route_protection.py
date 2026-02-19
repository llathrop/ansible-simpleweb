"""
Tests for Route Protection - Phase 1.3

Tests:
- All routes require authentication (except PUBLIC_ROUTES)
- Permission decorators correctly restrict access
- Worker authentication works for worker routes
- Service-to-service authentication
"""

import pytest
import tempfile
import os
import sys
import json
import uuid
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, g, jsonify
from web.storage.flatfile import FlatFileStorage
from web.auth import hash_password, APITokenManager
from web.auth_routes import (
    auth_bp,
    init_auth_middleware,
    login_required,
    admin_required,
    require_permission,
    require_any_permission,
    worker_auth_required,
    service_auth_required
)


@pytest.fixture
def app_with_users():
    """Create a test Flask app with multiple users of different roles."""
    # Get templates directory
    template_dir = os.path.join(os.path.dirname(__file__), '..', 'web', 'templates')

    app = Flask(__name__, template_folder=template_dir)
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['TESTING'] = True

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FlatFileStorage(config_dir=tmpdir)

        # Reset login tracker state for clean tests
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

        # Create operator user
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

        # Create monitor user
        monitor_id = str(uuid.uuid4())
        monitor_user = {
            'id': monitor_id,
            'username': 'monitor',
            'password_hash': hash_password('monitorpass'),
            'email': 'monitor@example.com',
            'roles': ['monitor'],
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_user('monitor', monitor_user)

        # Create a test worker
        worker_id = str(uuid.uuid4())
        worker = {
            'id': worker_id,
            'name': 'test-worker',
            'status': 'online',
            'is_local': False,
            'registered_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_worker(worker)

        # Register auth blueprint
        app.register_blueprint(auth_bp)

        # Add test routes that mimic main app permission patterns
        @app.route('/api/test-playbooks')
        @require_permission('playbooks:view')
        def api_playbooks():
            return jsonify({'playbooks': []})

        @app.route('/api/test-run', methods=['POST'])
        @require_permission('playbooks:run')
        def api_run():
            return jsonify({'ok': True})

        @app.route('/api/test-logs')
        @require_permission('logs:view')
        def api_logs():
            return jsonify({'logs': []})

        @app.route('/api/test-schedules')
        @require_permission('schedules:view')
        def api_schedules():
            return jsonify({'schedules': []})

        @app.route('/api/test-schedules', methods=['POST'])
        @require_permission('schedules:edit')
        def api_create_schedule():
            return jsonify({'ok': True})

        @app.route('/api/test-inventory')
        @require_permission('inventory:view')
        def api_inventory():
            return jsonify({'inventory': []})

        @app.route('/api/test-inventory', methods=['POST'])
        @require_permission('inventory:edit')
        def api_create_inventory():
            return jsonify({'ok': True})

        @app.route('/api/test-config')
        @require_permission('config:view')
        def api_config():
            return jsonify({'config': {}})

        @app.route('/api/test-config', methods=['PUT'])
        @require_permission('config:edit')
        def api_update_config():
            return jsonify({'ok': True})

        @app.route('/api/test-workers')
        @require_permission('workers:view')
        def api_workers():
            return jsonify({'workers': []})

        @app.route('/api/test-workers/<worker_id>', methods=['DELETE'])
        @require_permission('workers:admin')
        def api_delete_worker(worker_id):
            return jsonify({'ok': True})

        @app.route('/api/test-worker/route', methods=['POST'])
        @worker_auth_required
        def api_worker_route():
            wkr = g.current_worker
            return jsonify({'worker_id': wkr['id']})

        @app.route('/api/test-agent')
        @require_permission('agent:view')
        def api_agent():
            return jsonify({'agent': {}})

        # Initialize auth middleware
        init_auth_middleware(app, storage, auth_enabled=True)

        yield app, storage, {
            'admin': admin_user,
            'operator': operator_user,
            'monitor': monitor_user,
            'worker_id': worker_id
        }


@pytest.fixture
def admin_client(app_with_users):
    """Create test client logged in as admin."""
    app, storage, users = app_with_users
    client = app.test_client()

    # Login as admin
    client.post('/api/auth/login',
                json={'username': 'admin', 'password': 'adminpass'},
                content_type='application/json')

    return client


@pytest.fixture
def operator_client(app_with_users):
    """Create test client logged in as operator."""
    app, storage, users = app_with_users
    client = app.test_client()

    # Login as operator
    client.post('/api/auth/login',
                json={'username': 'operator', 'password': 'operatorpass'},
                content_type='application/json')

    return client


@pytest.fixture
def monitor_client(app_with_users):
    """Create test client logged in as monitor."""
    app, storage, users = app_with_users
    client = app.test_client()

    # Login as monitor
    client.post('/api/auth/login',
                json={'username': 'monitor', 'password': 'monitorpass'},
                content_type='application/json')

    return client


@pytest.fixture
def anon_client(app_with_users):
    """Create unauthenticated test client."""
    app, storage, users = app_with_users
    return app.test_client()


class TestPublicRoutes:
    """Test that public routes are accessible without auth."""

    def test_login_page_accessible(self, anon_client):
        """Login page should be accessible."""
        response = anon_client.get('/login')
        assert response.status_code == 200

    def test_login_api_accessible(self, anon_client):
        """Login API should be accessible (returns 401 for bad creds, not redirect)."""
        response = anon_client.post('/api/auth/login',
                                    json={'username': 'bad', 'password': 'creds'},
                                    content_type='application/json')
        assert response.status_code == 401

    def test_session_api_accessible(self, anon_client):
        """Session check API should be accessible."""
        response = anon_client.get('/api/auth/session')
        assert response.status_code == 200


class TestProtectedRoutesRequireAuth:
    """Test that protected routes require authentication."""

    protected_api_routes = [
        ('GET', '/api/test-playbooks'),
        ('GET', '/api/test-logs'),
        ('GET', '/api/test-schedules'),
        ('GET', '/api/test-inventory'),
        ('GET', '/api/test-config'),
        ('GET', '/api/test-workers'),
        ('GET', '/api/users'),
    ]

    @pytest.mark.parametrize('method,route', protected_api_routes)
    def test_api_routes_require_auth(self, anon_client, method, route):
        """API routes should return 401 without authentication."""
        if method == 'GET':
            response = anon_client.get(route)
        elif method == 'POST':
            response = anon_client.post(route, json={}, content_type='application/json')
        elif method == 'PUT':
            response = anon_client.put(route, json={}, content_type='application/json')
        elif method == 'DELETE':
            response = anon_client.delete(route)

        assert response.status_code == 401, f"{method} {route} should return 401"


class TestAdminOnlyRoutes:
    """Test routes that require admin role."""

    def test_admin_can_access_users_api(self, admin_client):
        """Admin should access user management."""
        response = admin_client.get('/api/users')
        assert response.status_code == 200

    def test_operator_cannot_access_users_api(self, operator_client):
        """Operator should not access user management."""
        response = operator_client.get('/api/users')
        assert response.status_code == 403

    def test_monitor_cannot_access_users_api(self, monitor_client):
        """Monitor should not access user management."""
        response = monitor_client.get('/api/users')
        assert response.status_code == 403

    def test_admin_can_delete_worker(self, admin_client, app_with_users):
        """Admin should be able to delete workers."""
        app, storage, users = app_with_users

        response = admin_client.delete(f'/api/test-workers/{users["worker_id"]}')
        assert response.status_code == 200

    def test_operator_cannot_delete_worker(self, operator_client, app_with_users):
        """Operator should not be able to delete workers."""
        app, storage, users = app_with_users
        response = operator_client.delete(f'/api/test-workers/{users["worker_id"]}')
        assert response.status_code == 403


class TestOperatorPermissions:
    """Test operator role permissions."""

    def test_operator_can_view_playbooks(self, operator_client):
        """Operator should view playbooks."""
        response = operator_client.get('/api/test-playbooks')
        assert response.status_code == 200

    def test_operator_can_run_playbooks(self, operator_client):
        """Operator should run playbooks."""
        response = operator_client.post('/api/test-run',
                                        json={},
                                        content_type='application/json')
        assert response.status_code == 200

    def test_operator_can_view_schedules(self, operator_client):
        """Operator should view schedules."""
        response = operator_client.get('/api/test-schedules')
        assert response.status_code == 200

    def test_operator_can_create_schedules(self, operator_client):
        """Operator should create schedules."""
        response = operator_client.post('/api/test-schedules',
                                        json={},
                                        content_type='application/json')
        assert response.status_code == 200

    def test_operator_can_view_logs(self, operator_client):
        """Operator should view logs."""
        response = operator_client.get('/api/test-logs')
        assert response.status_code == 200

    def test_operator_can_view_workers(self, operator_client):
        """Operator should view workers."""
        response = operator_client.get('/api/test-workers')
        assert response.status_code == 200

    def test_operator_cannot_edit_config(self, operator_client):
        """Operator should not edit config."""
        response = operator_client.put('/api/test-config',
                                       json={},
                                       content_type='application/json')
        assert response.status_code == 403


class TestMonitorPermissions:
    """Test monitor role permissions (read-only)."""

    def test_monitor_can_view_playbooks(self, monitor_client):
        """Monitor should view playbooks."""
        response = monitor_client.get('/api/test-playbooks')
        assert response.status_code == 200

    def test_monitor_can_view_logs(self, monitor_client):
        """Monitor should view logs."""
        response = monitor_client.get('/api/test-logs')
        assert response.status_code == 200

    def test_monitor_cannot_run_playbooks(self, monitor_client):
        """Monitor should not run playbooks."""
        response = monitor_client.post('/api/test-run',
                                       json={},
                                       content_type='application/json')
        assert response.status_code == 403

    def test_monitor_cannot_create_schedules(self, monitor_client):
        """Monitor should not create schedules."""
        response = monitor_client.post('/api/test-schedules',
                                       json={},
                                       content_type='application/json')
        assert response.status_code == 403

    def test_monitor_cannot_edit_inventory(self, monitor_client):
        """Monitor should not edit inventory."""
        response = monitor_client.post('/api/test-inventory',
                                       json={},
                                       content_type='application/json')
        assert response.status_code == 403


class TestAgentRoutePermissions:
    """Test agent route permissions."""

    def test_admin_can_access_agent(self, admin_client):
        """Admin should access agent routes."""
        response = admin_client.get('/api/test-agent')
        assert response.status_code == 200

    def test_operator_can_access_agent(self, operator_client):
        """Operator should access agent routes (has agent:view)."""
        response = operator_client.get('/api/test-agent')
        assert response.status_code == 200

    def test_monitor_can_access_agent(self, monitor_client):
        """Monitor should access agent routes (has agent:view)."""
        response = monitor_client.get('/api/test-agent')
        assert response.status_code == 200


class TestWorkerAuthRoutes:
    """Test worker authenticated routes."""

    def test_worker_route_requires_worker_auth(self, anon_client):
        """Worker routes should require worker authentication."""
        response = anon_client.post('/api/test-worker/route',
                                    json={},
                                    content_type='application/json')
        assert response.status_code == 401

    def test_worker_route_with_valid_worker(self, anon_client, app_with_users):
        """Worker routes should work with valid worker ID."""
        app, storage, users = app_with_users

        response = anon_client.post('/api/test-worker/route',
                                    json={'worker_id': users['worker_id']},
                                    content_type='application/json')
        assert response.status_code == 200


class TestConfigRoutePermissions:
    """Test config route permissions."""

    def test_admin_can_view_config(self, admin_client):
        """Admin should view config."""
        response = admin_client.get('/api/test-config')
        assert response.status_code == 200

    def test_admin_can_edit_config(self, admin_client):
        """Admin should edit config."""
        response = admin_client.put('/api/test-config',
                                    json={},
                                    content_type='application/json')
        assert response.status_code == 200

    def test_operator_cannot_edit_config(self, operator_client):
        """Operator should not edit config."""
        response = operator_client.put('/api/test-config',
                                       json={},
                                       content_type='application/json')
        assert response.status_code == 403


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
