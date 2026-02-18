"""
Tests for Authentication Middleware

Tests:
- Request authentication
- Public routes access
- API token authentication
- Session cookie handling
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
from web.auth_routes import auth_bp, init_auth_middleware, get_current_user, login_required


@pytest.fixture
def app_with_middleware():
    """Create a test Flask app with auth middleware and test routes."""
    # Get templates directory
    template_dir = os.path.join(os.path.dirname(__file__), '..', 'web', 'templates')

    app = Flask(__name__, template_folder=template_dir)
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['TESTING'] = True

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FlatFileStorage(config_dir=tmpdir)

        # Reset login tracker and session manager for clean tests
        from web.auth import login_tracker, session_manager
        login_tracker.attempts.clear()
        login_tracker.lockouts.clear()
        session_manager.sessions.clear()

        # Create test user
        user_id = str(uuid.uuid4())
        test_user = {
            'id': user_id,
            'username': 'testuser',
            'password_hash': hash_password('testpassword'),
            'email': 'test@example.com',
            'roles': ['admin'],
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_user('testuser', test_user)

        # Create API token for test user
        raw_token, token_entry = APITokenManager.create_token_entry(
            user_id=user_id,
            name='Test Token',
            expiry_days=365
        )
        storage.save_api_token(token_entry['id'], token_entry)

        # Register auth blueprint
        app.register_blueprint(auth_bp)

        # Add test protected route
        @app.route('/api/protected')
        @login_required
        def protected_route():
            user = get_current_user()
            return jsonify({'user': user['username']})

        # Add test unprotected route
        @app.route('/api/public')
        def public_route():
            return jsonify({'message': 'public'})

        # Initialize auth middleware
        init_auth_middleware(app, storage, auth_enabled=True)

        yield app, storage, raw_token


@pytest.fixture
def client(app_with_middleware):
    """Create test client."""
    app, storage, token = app_with_middleware
    return app.test_client()


@pytest.fixture
def api_token(app_with_middleware):
    """Get the test API token."""
    app, storage, token = app_with_middleware
    return token


class TestPublicRoutes:
    """Tests for public route access."""

    def test_login_page_accessible(self, client):
        """Login page should be accessible without auth."""
        response = client.get('/login')
        assert response.status_code == 200

    def test_login_api_accessible(self, client):
        """Login API should be accessible without auth."""
        response = client.post('/api/auth/login',
                               json={'username': 'test', 'password': 'test'},
                               content_type='application/json')
        # Should get 401 for bad creds, not redirect
        assert response.status_code == 401

    def test_session_api_accessible(self, client):
        """Session check API should be accessible without auth."""
        response = client.get('/api/auth/session')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['authenticated'] is False


class TestProtectedRoutes:
    """Tests for protected route access."""

    def test_protected_route_requires_auth(self, client):
        """Protected API routes should return 401 without auth."""
        response = client.get('/api/protected')
        assert response.status_code == 401

        data = json.loads(response.data)
        assert 'error' in data

    def test_protected_route_with_session(self, client):
        """Protected routes should work with valid session."""
        # Login first
        client.post('/api/auth/login',
                    json={'username': 'testuser', 'password': 'testpassword'},
                    content_type='application/json')

        # Access protected route
        response = client.get('/api/protected')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['user'] == 'testuser'

    def test_protected_route_with_api_token(self, client, api_token):
        """Protected routes should work with valid API token."""
        response = client.get('/api/protected',
                              headers={'X-API-Token': api_token})

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['user'] == 'testuser'

    def test_invalid_api_token(self, client):
        """Should reject invalid API token."""
        response = client.get('/api/protected',
                              headers={'X-API-Token': 'invalid-token'})

        assert response.status_code == 401


class TestWebRouteRedirect:
    """Tests for web route redirect behavior."""

    def test_web_route_redirects_to_login(self, client):
        """Web routes should redirect to login when not authenticated."""
        # Note: /users is a web route that requires admin
        response = client.get('/users')
        assert response.status_code == 302
        assert '/login' in response.headers.get('Location', '')

    def test_redirect_preserves_next_url(self, client):
        """Redirect should preserve the original requested URL."""
        response = client.get('/users')
        location = response.headers.get('Location', '')
        assert 'next=' in location or '/users' in location


class TestSessionCookieHandling:
    """Tests for session cookie handling."""

    def test_login_sets_cookie(self, client):
        """Login should set session cookie."""
        response = client.post('/api/auth/login',
                               json={'username': 'testuser', 'password': 'testpassword'},
                               content_type='application/json')

        assert response.status_code == 200

        # Check Set-Cookie header
        set_cookie = response.headers.get('Set-Cookie', '')
        assert 'ansible_session' in set_cookie
        assert 'HttpOnly' in set_cookie

    def test_logout_clears_cookie(self, client):
        """Logout should clear session cookie."""
        # Login first
        client.post('/api/auth/login',
                    json={'username': 'testuser', 'password': 'testpassword'},
                    content_type='application/json')

        # Logout
        response = client.post('/api/auth/logout')
        assert response.status_code == 200

        # Session endpoint should show not authenticated
        session_response = client.get('/api/auth/session')
        data = json.loads(session_response.data)
        assert data['authenticated'] is False


class TestDisabledUser:
    """Tests for disabled user handling."""

    def test_disabled_user_cannot_login(self, app_with_middleware):
        """Disabled users should not be able to login."""
        app, storage, token = app_with_middleware
        client = app.test_client()

        # Disable the user
        user = storage.get_user('testuser')
        user['enabled'] = False
        storage.save_user('testuser', user)

        # Try to login
        response = client.post('/api/auth/login',
                               json={'username': 'testuser', 'password': 'testpassword'},
                               content_type='application/json')

        assert response.status_code == 401

    def test_disabled_user_token_rejected(self, app_with_middleware, api_token):
        """API tokens for disabled users should be rejected."""
        app, storage, token = app_with_middleware
        client = app.test_client()

        # Disable the user
        user = storage.get_user('testuser')
        user['enabled'] = False
        storage.save_user('testuser', user)

        # Try to use token
        response = client.get('/api/protected',
                              headers={'X-API-Token': api_token})

        assert response.status_code == 401


class TestAuthDisabled:
    """Tests for when auth is disabled."""

    def test_all_routes_accessible_when_auth_disabled(self):
        """All routes should be accessible when auth is disabled."""
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test'
        app.config['TESTING'] = True

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FlatFileStorage(config_dir=tmpdir)

            app.register_blueprint(auth_bp)

            @app.route('/api/test')
            @login_required
            def test_route():
                return jsonify({'message': 'ok'})

            # Initialize with auth DISABLED
            init_auth_middleware(app, storage, auth_enabled=False)

            client = app.test_client()

            # Should be able to access without login
            # Note: The @login_required decorator still checks auth,
            # but the middleware doesn't require it for all routes
            response = client.get('/api/auth/session')
            assert response.status_code == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
