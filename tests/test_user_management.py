"""
Tests for User Management API Endpoints

Tests:
- User CRUD via API
- Password changes
- Admin-only access control
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
from web.auth import hash_password
from web.auth_routes import auth_bp, init_auth_middleware


@pytest.fixture
def app_and_storage():
    """Create a test Flask app with auth routes and storage."""
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

        # Create admin user
        admin_user = {
            'id': str(uuid.uuid4()),
            'username': 'admin',
            'password_hash': hash_password('adminpass'),
            'email': 'admin@example.com',
            'roles': ['admin'],
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_user('admin', admin_user)

        # Create regular user
        regular_user = {
            'id': str(uuid.uuid4()),
            'username': 'regular',
            'password_hash': hash_password('regularpass'),
            'email': 'regular@example.com',
            'roles': ['monitor'],
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_user('regular', regular_user)

        # Register blueprint
        app.register_blueprint(auth_bp)

        # Initialize auth middleware
        init_auth_middleware(app, storage, auth_enabled=True)

        yield app, storage


@pytest.fixture
def admin_client(app_and_storage):
    """Create test client logged in as admin."""
    app, storage = app_and_storage
    client = app.test_client()

    # Login as admin
    client.post('/api/auth/login',
                json={'username': 'admin', 'password': 'adminpass'},
                content_type='application/json')

    return client


@pytest.fixture
def regular_client(app_and_storage):
    """Create test client logged in as regular user."""
    app, storage = app_and_storage
    client = app.test_client()

    # Login as regular user
    client.post('/api/auth/login',
                json={'username': 'regular', 'password': 'regularpass'},
                content_type='application/json')

    return client


@pytest.fixture
def anon_client(app_and_storage):
    """Create test client without login."""
    app, storage = app_and_storage
    return app.test_client()


class TestListUsers:
    """Tests for GET /api/users endpoint."""

    def test_admin_can_list_users(self, admin_client):
        """Admin should be able to list all users."""
        response = admin_client.get('/api/users')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'users' in data
        assert len(data['users']) == 2  # admin + regular

        # Users should not have password_hash
        for user in data['users']:
            assert 'password_hash' not in user

    def test_regular_user_cannot_list_users(self, regular_client):
        """Regular user should not be able to list users."""
        response = regular_client.get('/api/users')
        assert response.status_code == 403

    def test_anon_cannot_list_users(self, anon_client):
        """Anonymous user should not be able to list users."""
        response = anon_client.get('/api/users')
        assert response.status_code == 401


class TestGetUser:
    """Tests for GET /api/users/<username> endpoint."""

    def test_admin_can_get_user(self, admin_client):
        """Admin should be able to get user details."""
        response = admin_client.get('/api/users/regular')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'user' in data
        assert data['user']['username'] == 'regular'
        assert 'password_hash' not in data['user']

    def test_get_nonexistent_user(self, admin_client):
        """Should return 404 for nonexistent user."""
        response = admin_client.get('/api/users/nonexistent')
        assert response.status_code == 404


class TestCreateUser:
    """Tests for POST /api/users endpoint."""

    def test_admin_can_create_user(self, admin_client):
        """Admin should be able to create a new user."""
        response = admin_client.post('/api/users',
                                     json={
                                         'username': 'newuser',
                                         'password': 'newpassword',
                                         'email': 'new@example.com',
                                         'roles': ['operator']
                                     },
                                     content_type='application/json')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['ok'] is True
        assert data['user']['username'] == 'newuser'

    def test_create_duplicate_user(self, admin_client):
        """Should reject duplicate username."""
        response = admin_client.post('/api/users',
                                     json={
                                         'username': 'admin',
                                         'password': 'somepass'
                                     },
                                     content_type='application/json')

        assert response.status_code == 409
        data = json.loads(response.data)
        assert 'error' in data

    def test_create_user_missing_password(self, admin_client):
        """Should reject user without password."""
        response = admin_client.post('/api/users',
                                     json={'username': 'nopass'},
                                     content_type='application/json')

        assert response.status_code == 400

    def test_regular_user_cannot_create_user(self, regular_client):
        """Regular user should not be able to create users."""
        response = regular_client.post('/api/users',
                                       json={
                                           'username': 'newuser',
                                           'password': 'pass'
                                       },
                                       content_type='application/json')

        assert response.status_code == 403


class TestUpdateUser:
    """Tests for PUT /api/users/<username> endpoint."""

    def test_admin_can_update_user(self, admin_client):
        """Admin should be able to update user."""
        response = admin_client.put('/api/users/regular',
                                    json={
                                        'email': 'updated@example.com',
                                        'roles': ['operator']
                                    },
                                    content_type='application/json')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['ok'] is True
        assert data['user']['email'] == 'updated@example.com'

    def test_admin_can_change_user_password(self, admin_client):
        """Admin should be able to change any user's password."""
        response = admin_client.put('/api/users/regular',
                                    json={'password': 'newpassword'},
                                    content_type='application/json')

        assert response.status_code == 200

    def test_update_nonexistent_user(self, admin_client):
        """Should return 404 for nonexistent user."""
        response = admin_client.put('/api/users/nonexistent',
                                    json={'email': 'test@test.com'},
                                    content_type='application/json')

        assert response.status_code == 404


class TestDeleteUser:
    """Tests for DELETE /api/users/<username> endpoint."""

    def test_admin_can_delete_user(self, admin_client, app_and_storage):
        """Admin should be able to delete user."""
        app, storage = app_and_storage

        # Create a user to delete
        storage.save_user('deleteme', {
            'id': str(uuid.uuid4()),
            'username': 'deleteme',
            'password_hash': 'hash',
            'roles': []
        })

        response = admin_client.delete('/api/users/deleteme')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['ok'] is True

        # User should be deleted
        assert storage.get_user('deleteme') is None

    def test_cannot_delete_self(self, admin_client):
        """Admin should not be able to delete their own account."""
        response = admin_client.delete('/api/users/admin')
        assert response.status_code == 400

        data = json.loads(response.data)
        assert 'own account' in data['error'].lower() or 'cannot delete' in data['error'].lower()

    def test_delete_nonexistent_user(self, admin_client):
        """Should return 404 for nonexistent user."""
        response = admin_client.delete('/api/users/nonexistent')
        assert response.status_code == 404


class TestChangePassword:
    """Tests for PUT /api/users/<username>/password endpoint."""

    def test_user_can_change_own_password(self, regular_client):
        """User should be able to change their own password."""
        response = regular_client.put('/api/users/regular/password',
                                      json={
                                          'current_password': 'regularpass',
                                          'new_password': 'newregularpass'
                                      },
                                      content_type='application/json')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['ok'] is True

    def test_change_password_wrong_current(self, regular_client):
        """Should reject wrong current password."""
        response = regular_client.put('/api/users/regular/password',
                                      json={
                                          'current_password': 'wrongpassword',
                                          'new_password': 'newpass'
                                      },
                                      content_type='application/json')

        assert response.status_code == 401

    def test_admin_can_change_other_password(self, admin_client):
        """Admin should be able to change any user's password without current."""
        response = admin_client.put('/api/users/regular/password',
                                    json={'new_password': 'adminreset'},
                                    content_type='application/json')

        assert response.status_code == 200

    def test_regular_cannot_change_other_password(self, regular_client):
        """Regular user should not be able to change other's password."""
        response = regular_client.put('/api/users/admin/password',
                                      json={
                                          'current_password': 'anything',
                                          'new_password': 'hacked'
                                      },
                                      content_type='application/json')

        assert response.status_code == 403


class TestUsersPage:
    """Tests for /users web routes."""

    def test_admin_can_access_users_page(self, admin_client):
        """Admin should be able to access users page."""
        response = admin_client.get('/users')
        assert response.status_code == 200

    def test_regular_cannot_access_users_page(self, regular_client):
        """Regular user should not be able to access users page."""
        response = regular_client.get('/users')
        assert response.status_code == 403


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
