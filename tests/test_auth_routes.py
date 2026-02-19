"""
Tests for web/auth_routes.py - Authentication Routes

Tests:
- Login/logout functionality
- Session management
- Cookie handling
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

from flask import Flask, g
from web.storage.flatfile import FlatFileStorage
from web.auth import hash_password, session_manager
from web.auth_routes import auth_bp, init_auth_middleware, bootstrap_admin_user


@pytest.fixture
def app_with_auth():
    """Create a test Flask app with auth routes."""
    # Get templates directory
    template_dir = os.path.join(os.path.dirname(__file__), '..', 'web', 'templates')

    app = Flask(__name__, template_folder=template_dir)
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['TESTING'] = True

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FlatFileStorage(config_dir=tmpdir)

        # Reset login tracker state for clean tests
        from web.auth import login_tracker
        login_tracker.attempts.clear()
        login_tracker.lockouts.clear()

        # Create test user
        test_user = {
            'id': str(uuid.uuid4()),
            'username': 'testuser',
            'password_hash': hash_password('testpassword'),
            'email': 'test@example.com',
            'roles': ['admin'],
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_user('testuser', test_user)

        # Register blueprint
        app.register_blueprint(auth_bp)

        # Initialize auth middleware
        init_auth_middleware(app, storage, auth_enabled=True)

        yield app, storage


@pytest.fixture
def client(app_with_auth):
    """Create test client."""
    app, storage = app_with_auth
    return app.test_client()


class TestLoginEndpoint:
    """Tests for /api/auth/login endpoint."""

    def test_login_success(self, client):
        """Should return session on successful login."""
        response = client.post('/api/auth/login',
                               json={'username': 'testuser', 'password': 'testpassword'},
                               content_type='application/json')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['ok'] is True
        assert data['user']['username'] == 'testuser'

        # Should set session cookie
        assert 'ansible_session' in response.headers.get('Set-Cookie', '')

    def test_login_invalid_password(self, client):
        """Should return 401 on invalid password."""
        response = client.post('/api/auth/login',
                               json={'username': 'testuser', 'password': 'wrongpassword'},
                               content_type='application/json')

        assert response.status_code == 401
        data = json.loads(response.data)
        assert 'error' in data

    def test_login_invalid_username(self, client):
        """Should return 401 on invalid username."""
        response = client.post('/api/auth/login',
                               json={'username': 'nonexistent', 'password': 'testpassword'},
                               content_type='application/json')

        assert response.status_code == 401
        data = json.loads(response.data)
        assert 'error' in data

    def test_login_missing_credentials(self, client):
        """Should return 400 on missing credentials."""
        response = client.post('/api/auth/login',
                               json={},
                               content_type='application/json')

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data


class TestLogoutEndpoint:
    """Tests for logout endpoints."""

    def test_api_logout(self, client):
        """Should destroy session on logout."""
        # First login
        login_response = client.post('/api/auth/login',
                                     json={'username': 'testuser', 'password': 'testpassword'},
                                     content_type='application/json')
        assert login_response.status_code == 200

        # Then logout via API
        logout_response = client.post('/api/auth/logout')
        assert logout_response.status_code == 200

        data = json.loads(logout_response.data)
        assert data['ok'] is True

    def test_web_logout_redirect(self, client):
        """Should redirect to login page on web logout."""
        # First login
        client.post('/api/auth/login',
                    json={'username': 'testuser', 'password': 'testpassword'},
                    content_type='application/json')

        # Logout via web route
        response = client.get('/logout')
        assert response.status_code == 302
        assert '/login' in response.headers.get('Location', '')


class TestSessionEndpoint:
    """Tests for /api/auth/session endpoint."""

    def test_session_authenticated(self, client):
        """Should return user info when authenticated."""
        # Login first
        client.post('/api/auth/login',
                    json={'username': 'testuser', 'password': 'testpassword'},
                    content_type='application/json')

        # Check session
        response = client.get('/api/auth/session')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['authenticated'] is True
        assert data['user']['username'] == 'testuser'
        assert 'permissions' in data['user']

    def test_session_not_authenticated(self, client):
        """Should return authenticated=false when not logged in."""
        response = client.get('/api/auth/session')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['authenticated'] is False


class TestLoginPage:
    """Tests for /login web route."""

    def test_login_page_renders(self, client):
        """Should render login page."""
        response = client.get('/login')
        assert response.status_code == 200
        assert b'Sign in' in response.data or b'login' in response.data.lower()


class TestBootstrapAdminUser:
    """Tests for bootstrap_admin_user function."""

    def test_bootstrap_creates_admin(self):
        """Should create admin when no users exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FlatFileStorage(config_dir=tmpdir)

            # Should be no users initially
            assert len(storage.get_all_users()) == 0

            # Bootstrap admin
            result = bootstrap_admin_user(storage, username='admin', password='adminpass')
            assert result is True

            # Should now have one user
            users = storage.get_all_users()
            assert len(users) == 1
            assert users[0]['username'] == 'admin'

    def test_bootstrap_skips_if_users_exist(self):
        """Should not create admin if users already exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FlatFileStorage(config_dir=tmpdir)

            # Create existing user
            storage.save_user('existing', {
                'id': str(uuid.uuid4()),
                'username': 'existing',
                'password_hash': 'hash',
                'roles': []
            })

            # Try to bootstrap
            result = bootstrap_admin_user(storage, username='admin', password='adminpass')
            assert result is False

            # Should still have only one user
            users = storage.get_all_users()
            assert len(users) == 1
            assert users[0]['username'] == 'existing'


class TestAccountLockout:
    """Tests for account lockout on failed logins."""

    def test_lockout_after_failed_attempts(self, app_with_auth):
        """Should lock account after 5 failed attempts."""
        app, storage = app_with_auth

        # Clear login tracker for this specific test
        from web.auth import login_tracker
        login_tracker.attempts.clear()
        login_tracker.lockouts.clear()

        client = app.test_client()

        # Make 4 failed login attempts (returns 401 with decreasing attempts remaining)
        for i in range(4):
            response = client.post('/api/auth/login',
                                   json={'username': 'testuser', 'password': 'wrong'},
                                   content_type='application/json')
            assert response.status_code == 401, f"Attempt {i+1} should be 401"

        # 5th attempt triggers lockout immediately (returns 423)
        response = client.post('/api/auth/login',
                               json={'username': 'testuser', 'password': 'wrong'},
                               content_type='application/json')

        assert response.status_code == 423
        data = json.loads(response.data)
        assert 'locked' in data['error'].lower()

        # Even correct password should be locked
        response = client.post('/api/auth/login',
                               json={'username': 'testuser', 'password': 'testpassword'},
                               content_type='application/json')
        assert response.status_code == 423


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
