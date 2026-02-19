"""
Tests for Worker Authentication - Phase 1.3

Tests:
- Worker registration
- Worker authentication on protected routes
- Worker-specific routes require worker auth
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
from web.auth import hash_password
from web.auth_routes import (
    auth_bp,
    init_auth_middleware,
    worker_auth_required,
    service_auth_required
)


@pytest.fixture
def app_with_workers():
    """Create a test Flask app with workers."""
    # Get templates directory
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

        # Create admin user for session-based auth tests
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

        # Create a test worker
        worker_id = str(uuid.uuid4())
        worker = {
            'id': worker_id,
            'name': 'test-worker',
            'status': 'online',
            'is_local': False,
            'registered_at': datetime.now(timezone.utc).isoformat(),
            'tags': ['tag1', 'tag2']
        }
        storage.save_worker(worker)

        # Create a second worker
        worker2_id = str(uuid.uuid4())
        worker2 = {
            'id': worker2_id,
            'name': 'test-worker-2',
            'status': 'offline',
            'is_local': False,
            'registered_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_worker(worker2)

        # Register auth blueprint
        app.register_blueprint(auth_bp)

        # Add test routes with worker auth (use /api/ prefix so middleware treats as API)
        @app.route('/api/test-worker/route', methods=['POST'])
        @worker_auth_required
        def test_worker_route():
            """Test route requiring worker auth."""
            wkr = g.current_worker
            return jsonify({
                'worker_id': wkr['id'],
                'worker_name': wkr.get('name')
            })

        @app.route('/api/test-service/route', methods=['POST'])
        @service_auth_required
        def test_service_route():
            """Test route requiring service auth."""
            return jsonify({'service': 'authenticated'})

        # Initialize auth middleware
        init_auth_middleware(app, storage, auth_enabled=True)

        yield app, storage, {
            'worker_id': worker_id,
            'worker': worker,
            'worker2_id': worker2_id,
            'admin': admin_user
        }


@pytest.fixture
def client(app_with_workers):
    """Create test client."""
    app, storage, data = app_with_workers
    return app.test_client()


@pytest.fixture
def admin_client(app_with_workers):
    """Create test client logged in as admin."""
    app, storage, data = app_with_workers
    client = app.test_client()
    client.post('/api/auth/login',
                json={'username': 'admin', 'password': 'adminpass'},
                content_type='application/json')
    return client


class TestWorkerAuthRequired:
    """Tests for @worker_auth_required decorator."""

    def test_worker_id_in_body(self, client, app_with_workers):
        """Should authenticate worker via request body."""
        app, storage, data = app_with_workers

        response = client.post('/api/test-worker/route',
                               json={'worker_id': data['worker_id']},
                               content_type='application/json')
        assert response.status_code == 200

        result = json.loads(response.data)
        assert result['worker_id'] == data['worker_id']

    def test_worker_id_in_header(self, client, app_with_workers):
        """Should authenticate worker via X-Worker-Id header."""
        app, storage, data = app_with_workers

        response = client.post('/api/test-worker/route',
                               headers={'X-Worker-Id': data['worker_id']},
                               content_type='application/json')
        assert response.status_code == 200

        result = json.loads(response.data)
        assert result['worker_id'] == data['worker_id']

    def test_missing_worker_id(self, client):
        """Should reject request without worker ID."""
        response = client.post('/api/test-worker/route',
                               json={},
                               content_type='application/json')
        assert response.status_code == 401

        result = json.loads(response.data)
        assert 'error' in result

    def test_invalid_worker_id(self, client):
        """Should reject request with invalid worker ID."""
        response = client.post('/api/test-worker/route',
                               json={'worker_id': 'nonexistent-worker'},
                               content_type='application/json')
        assert response.status_code == 401

        result = json.loads(response.data)
        assert 'error' in result

    def test_worker_available_in_g(self, client, app_with_workers):
        """Should make worker data available in flask.g."""
        app, storage, data = app_with_workers

        response = client.post('/api/test-worker/route',
                               json={'worker_id': data['worker_id']},
                               content_type='application/json')

        result = json.loads(response.data)
        assert result['worker_name'] == data['worker']['name']


class TestServiceAuthRequired:
    """Tests for @service_auth_required decorator."""

    def test_service_token_required(self, client):
        """Should require service authentication."""
        response = client.post('/api/test-service/route',
                               json={},
                               content_type='application/json')
        # Service auth should be required
        assert response.status_code == 401

    def test_admin_can_access_service_route(self, admin_client):
        """Admin session should access service routes."""
        response = admin_client.post('/api/test-service/route',
                                     json={},
                                     content_type='application/json')
        assert response.status_code == 200


class TestWorkerRegistration:
    """Tests for worker registration endpoint.

    Note: These tests are skipped as they require the full app.py routes,
    not just auth_bp. Worker registration is tested in integration tests.
    """

    @pytest.mark.skip(reason="Requires full app.py routes")
    def test_register_new_worker(self, client, app_with_workers):
        """Should register new worker."""
        pass

    @pytest.mark.skip(reason="Requires full app.py routes")
    def test_registration_is_public(self, client):
        """Worker registration should be accessible without auth."""
        pass


class TestWorkerViewRoutes:
    """Tests for viewing worker info (admin routes).

    Note: Most tests are skipped as they require full app.py routes.
    Worker view routes are tested in integration tests.
    """

    @pytest.mark.skip(reason="Requires full app.py routes")
    def test_list_workers_requires_admin(self, client):
        """Listing workers should require auth."""
        pass

    @pytest.mark.skip(reason="Requires full app.py routes")
    def test_admin_can_list_workers(self, admin_client, app_with_workers):
        """Admin should list workers."""
        pass

    @pytest.mark.skip(reason="Requires full app.py routes")
    def test_admin_can_view_worker(self, admin_client, app_with_workers):
        """Admin should view specific worker."""
        pass


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
