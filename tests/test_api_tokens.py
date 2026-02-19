"""
Tests for API Token Authentication - Phase 1.3

Tests:
- API token creation and validation
- Token-based authentication for routes
- Token expiry handling
- Token revocation
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

from flask import Flask, jsonify
from web.storage.flatfile import FlatFileStorage
from web.auth import hash_password, APITokenManager
from web.auth_routes import auth_bp, init_auth_middleware, login_required


@pytest.fixture
def app_with_tokens():
    """Create a test Flask app with a user and API tokens."""
    # Get templates directory
    template_dir = os.path.join(os.path.dirname(__file__), '..', 'web', 'templates')

    app = Flask(__name__, template_folder=template_dir)
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['TESTING'] = True

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FlatFileStorage(config_dir=tmpdir)

        # Reset login tracker state
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

        # Create a valid API token
        raw_token, token_entry = APITokenManager.create_token_entry(
            user_id=user_id,
            name='Test Token',
            expiry_days=365
        )
        storage.save_api_token(token_entry['id'], token_entry)

        # Create an expired token
        expired_raw, expired_entry = APITokenManager.create_token_entry(
            user_id=user_id,
            name='Expired Token',
            expiry_days=-1  # Already expired
        )
        storage.save_api_token(expired_entry['id'], expired_entry)

        # Register auth blueprint
        app.register_blueprint(auth_bp)

        # Add test protected route
        @app.route('/api/test-protected')
        @login_required
        def test_protected_route():
            return jsonify({'message': 'authenticated'})

        # Initialize auth middleware
        init_auth_middleware(app, storage, auth_enabled=True)

        yield app, storage, {
            'user': test_user,
            'valid_token': raw_token,
            'valid_token_entry': token_entry,
            'expired_token': expired_raw,
            'expired_token_entry': expired_entry
        }


@pytest.fixture
def client(app_with_tokens):
    """Create test client."""
    app, storage, tokens = app_with_tokens
    return app.test_client()


@pytest.fixture
def logged_in_client(app_with_tokens):
    """Create test client logged in via session."""
    app, storage, tokens = app_with_tokens
    client = app.test_client()
    client.post('/api/auth/login',
                json={'username': 'testuser', 'password': 'testpassword'},
                content_type='application/json')
    return client


class TestAPITokenManager:
    """Tests for APITokenManager class."""

    def test_generate_token(self):
        """Should generate unique tokens."""
        token1 = APITokenManager.generate_token()
        token2 = APITokenManager.generate_token()

        assert token1 is not None
        assert len(token1) == 64  # 32 bytes * 2 hex chars
        assert token1 != token2  # Should be unique

    def test_hash_token(self):
        """Should hash tokens consistently."""
        token = 'test-token-value'
        hash1 = APITokenManager.hash_token(token)
        hash2 = APITokenManager.hash_token(token)

        assert hash1 == hash2  # Same token should produce same hash
        assert hash1 != token  # Hash should differ from original

    def test_create_token_entry(self):
        """Should create token with hash and metadata."""
        user_id = str(uuid.uuid4())
        raw_token, entry = APITokenManager.create_token_entry(
            user_id=user_id,
            name='My Token',
            expiry_days=30
        )

        assert raw_token is not None
        assert len(raw_token) == 64  # Should be a 64-char hex token
        assert entry['user_id'] == user_id
        assert entry['name'] == 'My Token'
        assert 'token_hash' in entry
        assert 'expires_at' in entry
        assert entry['id'] is not None

    def test_create_token_entry_no_expiry(self):
        """Should create token without expiry."""
        user_id = str(uuid.uuid4())
        raw_token, entry = APITokenManager.create_token_entry(
            user_id=user_id,
            name='Permanent Token',
            expiry_days=None
        )

        assert raw_token is not None
        assert entry['expires_at'] is None


class TestAPITokenAuthentication:
    """Tests for API token authentication on routes."""

    def test_valid_token_authenticates(self, client, app_with_tokens):
        """Valid API token should authenticate requests."""
        app, storage, tokens = app_with_tokens

        response = client.get('/api/test-protected',
                              headers={'X-API-Token': tokens['valid_token']})
        assert response.status_code == 200

    def test_invalid_token_rejected(self, client):
        """Invalid API token should be rejected."""
        response = client.get('/api/test-protected',
                              headers={'X-API-Token': 'invalid-token'})
        assert response.status_code == 401

    def test_expired_token_rejected(self, client, app_with_tokens):
        """Expired API token should be rejected."""
        app, storage, tokens = app_with_tokens

        response = client.get('/api/test-protected',
                              headers={'X-API-Token': tokens['expired_token']})
        assert response.status_code == 401

    def test_missing_token_and_session_rejected(self, client):
        """Request without token or session should be rejected."""
        response = client.get('/api/test-protected')
        assert response.status_code == 401


class TestTokenWithDisabledUser:
    """Tests for tokens when user is disabled."""

    def test_token_rejected_for_disabled_user(self, app_with_tokens):
        """Token should be rejected if user is disabled."""
        app, storage, tokens = app_with_tokens
        client = app.test_client()

        # Disable the user
        user = storage.get_user('testuser')
        user['enabled'] = False
        storage.save_user('testuser', user)

        response = client.get('/api/test-protected',
                              headers={'X-API-Token': tokens['valid_token']})
        assert response.status_code == 401


class TestTokenManagementAPI:
    """Tests for token management API endpoints."""

    def test_list_tokens(self, logged_in_client, app_with_tokens):
        """Should list user's tokens."""
        app, storage, tokens = app_with_tokens

        response = logged_in_client.get('/api/tokens')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'tokens' in data
        # Should have at least the test tokens
        assert len(data['tokens']) >= 1

    def test_create_token(self, logged_in_client):
        """Should create new token."""
        response = logged_in_client.post('/api/tokens',
                                         json={'name': 'New Test Token'},
                                         content_type='application/json')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'token' in data
        # Token should be returned once for user to copy
        assert len(data['token']) == 64

    def test_create_token_with_expiry(self, logged_in_client):
        """Should create token with custom expiry."""
        response = logged_in_client.post('/api/tokens',
                                         json={
                                             'name': 'Short-lived Token',
                                             'expiry_days': 7
                                         },
                                         content_type='application/json')
        assert response.status_code == 200

        data = json.loads(response.data)
        # Token entry should have expires_at
        assert 'token_entry' in data
        assert 'expires_at' in data['token_entry']

    def test_revoke_token(self, logged_in_client, app_with_tokens):
        """Should revoke token."""
        app, storage, tokens = app_with_tokens
        token_id = tokens['valid_token_entry']['id']

        response = logged_in_client.delete(f'/api/tokens/{token_id}')
        assert response.status_code == 200

    def test_cannot_use_revoked_token(self, app_with_tokens):
        """Revoked token should not authenticate."""
        app, storage, tokens = app_with_tokens
        client = app.test_client()

        # Login to revoke the token
        client.post('/api/auth/login',
                    json={'username': 'testuser', 'password': 'testpassword'},
                    content_type='application/json')

        # Revoke the token
        token_id = tokens['valid_token_entry']['id']
        client.delete(f'/api/tokens/{token_id}')

        # Try to use the revoked token
        new_client = app.test_client()
        response = new_client.get('/api/test-protected',
                                  headers={'X-API-Token': tokens['valid_token']})
        assert response.status_code == 401


class TestTokenPermissions:
    """Tests that tokens inherit user permissions."""

    def test_token_has_user_permissions(self, app_with_tokens):
        """Token should have same permissions as user."""
        app, storage, tokens = app_with_tokens
        client = app.test_client()

        # Admin token should access admin routes
        response = client.get('/api/users',
                              headers={'X-API-Token': tokens['valid_token']})
        assert response.status_code == 200

    def test_token_respects_permission_limits(self):
        """Token should respect user's role limits."""
        # Create a monitor user with token
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'web', 'templates')

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FlatFileStorage(config_dir=tmpdir)

            # Reset state
            from web.auth import login_tracker, session_manager
            login_tracker.attempts.clear()
            login_tracker.lockouts.clear()
            session_manager.sessions.clear()

            # Create monitor user
            user_id = str(uuid.uuid4())
            monitor_user = {
                'id': user_id,
                'username': 'monitor',
                'password_hash': hash_password('monitorpass'),
                'email': 'monitor@example.com',
                'roles': ['monitor'],
                'enabled': True,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            storage.save_user('monitor', monitor_user)

            # Create token for monitor
            raw_token, token_entry = APITokenManager.create_token_entry(
                user_id=user_id,
                name='Monitor Token',
                expiry_days=365
            )
            storage.save_api_token(token_entry['id'], token_entry)

            # Create app
            app = Flask(__name__, template_folder=template_dir)
            app.config['SECRET_KEY'] = 'test'
            app.config['TESTING'] = True

            app.register_blueprint(auth_bp)
            init_auth_middleware(app, storage, auth_enabled=True)

            client = app.test_client()

            # Monitor token should NOT access admin routes
            response = client.get('/api/users',
                                  headers={'X-API-Token': raw_token})
            assert response.status_code == 403


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
