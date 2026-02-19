"""
Tests for User Storage Operations

Tests user CRUD operations for both FlatFile and MongoDB backends.
"""

import pytest
import tempfile
import os
import sys
import uuid
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from web.storage.flatfile import FlatFileStorage


class TestFlatFileUserStorage:
    """Tests for FlatFileStorage user operations."""

    @pytest.fixture
    def storage(self):
        """Create a temporary storage directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FlatFileStorage(config_dir=tmpdir)

    def test_save_and_get_user(self, storage):
        """Should save and retrieve a user."""
        user = {
            'id': str(uuid.uuid4()),
            'username': 'testuser',
            'password_hash': '$2b$12$test_hash',
            'email': 'test@example.com',
            'roles': ['admin'],
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        result = storage.save_user('testuser', user)
        assert result is True

        retrieved = storage.get_user('testuser')
        assert retrieved is not None
        assert retrieved['username'] == 'testuser'
        assert retrieved['email'] == 'test@example.com'

    def test_get_user_not_found(self, storage):
        """Should return None for non-existent user."""
        result = storage.get_user('nonexistent')
        assert result is None

    def test_get_user_by_id(self, storage):
        """Should retrieve user by ID."""
        user_id = str(uuid.uuid4())
        user = {
            'id': user_id,
            'username': 'testuser',
            'password_hash': '$2b$12$test_hash',
            'roles': ['admin']
        }

        storage.save_user('testuser', user)
        retrieved = storage.get_user_by_id(user_id)

        assert retrieved is not None
        assert retrieved['id'] == user_id

    def test_get_all_users_excludes_password(self, storage):
        """get_all_users should exclude password_hash."""
        user = {
            'id': str(uuid.uuid4()),
            'username': 'testuser',
            'password_hash': '$2b$12$secret_hash',
            'email': 'test@example.com',
            'roles': ['admin']
        }

        storage.save_user('testuser', user)
        users = storage.get_all_users()

        assert len(users) == 1
        assert 'password_hash' not in users[0]
        assert users[0]['username'] == 'testuser'

    def test_delete_user(self, storage):
        """Should delete a user."""
        user = {
            'id': str(uuid.uuid4()),
            'username': 'testuser',
            'password_hash': '$2b$12$test_hash',
            'roles': []
        }

        storage.save_user('testuser', user)
        assert storage.get_user('testuser') is not None

        result = storage.delete_user('testuser')
        assert result is True
        assert storage.get_user('testuser') is None

    def test_delete_user_not_found(self, storage):
        """Should return False when deleting non-existent user."""
        result = storage.delete_user('nonexistent')
        assert result is False

    def test_update_user(self, storage):
        """Should update existing user."""
        user = {
            'id': str(uuid.uuid4()),
            'username': 'testuser',
            'password_hash': '$2b$12$test_hash',
            'email': 'old@example.com',
            'roles': ['admin']
        }

        storage.save_user('testuser', user)

        # Update email
        user['email'] = 'new@example.com'
        storage.save_user('testuser', user)

        retrieved = storage.get_user('testuser')
        assert retrieved['email'] == 'new@example.com'


class TestFlatFileGroupStorage:
    """Tests for FlatFileStorage group operations."""

    @pytest.fixture
    def storage(self):
        """Create a temporary storage directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FlatFileStorage(config_dir=tmpdir)

    def test_save_and_get_group(self, storage):
        """Should save and retrieve a group."""
        group = {
            'id': str(uuid.uuid4()),
            'name': 'admins',
            'description': 'Administrator group',
            'roles': ['admin'],
            'members': [],
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        result = storage.save_group('admins', group)
        assert result is True

        retrieved = storage.get_group('admins')
        assert retrieved is not None
        assert retrieved['name'] == 'admins'
        assert retrieved['description'] == 'Administrator group'

    def test_get_all_groups(self, storage):
        """Should get all groups."""
        group1 = {'id': str(uuid.uuid4()), 'name': 'group1', 'roles': []}
        group2 = {'id': str(uuid.uuid4()), 'name': 'group2', 'roles': []}

        storage.save_group('group1', group1)
        storage.save_group('group2', group2)

        groups = storage.get_all_groups()
        assert len(groups) == 2

    def test_delete_group(self, storage):
        """Should delete a group."""
        group = {'id': str(uuid.uuid4()), 'name': 'testgroup', 'roles': []}
        storage.save_group('testgroup', group)

        result = storage.delete_group('testgroup')
        assert result is True
        assert storage.get_group('testgroup') is None


class TestFlatFileRoleStorage:
    """Tests for FlatFileStorage role operations."""

    @pytest.fixture
    def storage(self):
        """Create a temporary storage directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FlatFileStorage(config_dir=tmpdir)

    def test_save_and_get_role(self, storage):
        """Should save and retrieve a role."""
        role = {
            'id': str(uuid.uuid4()),
            'name': 'custom_role',
            'description': 'Custom test role',
            'permissions': ['playbooks:view', 'logs:view'],
            'inherits': [],
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        result = storage.save_role('custom_role', role)
        assert result is True

        retrieved = storage.get_role('custom_role')
        assert retrieved is not None
        assert retrieved['name'] == 'custom_role'
        assert 'playbooks:view' in retrieved['permissions']

    def test_get_all_roles(self, storage):
        """Should get all roles."""
        role1 = {'id': str(uuid.uuid4()), 'name': 'role1', 'permissions': []}
        role2 = {'id': str(uuid.uuid4()), 'name': 'role2', 'permissions': []}

        storage.save_role('role1', role1)
        storage.save_role('role2', role2)

        roles = storage.get_all_roles()
        assert len(roles) == 2


class TestFlatFileAPITokenStorage:
    """Tests for FlatFileStorage API token operations."""

    @pytest.fixture
    def storage(self):
        """Create a temporary storage directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FlatFileStorage(config_dir=tmpdir)

    def test_save_and_get_api_token(self, storage):
        """Should save and retrieve an API token."""
        token_id = str(uuid.uuid4())
        token = {
            'id': token_id,
            'user_id': 'user123',
            'name': 'Test Token',
            'token_hash': 'abc123hash',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'expires_at': None,
            'last_used': None
        }

        result = storage.save_api_token(token_id, token)
        assert result is True

        retrieved = storage.get_api_token(token_id)
        assert retrieved is not None
        assert retrieved['name'] == 'Test Token'

    def test_get_api_token_by_hash(self, storage):
        """Should retrieve token by hash."""
        token_id = str(uuid.uuid4())
        token_hash = 'unique_hash_123'
        token = {
            'id': token_id,
            'user_id': 'user123',
            'name': 'Test Token',
            'token_hash': token_hash,
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        storage.save_api_token(token_id, token)

        retrieved = storage.get_api_token_by_hash(token_hash)
        assert retrieved is not None
        assert retrieved['id'] == token_id

    def test_get_user_api_tokens_excludes_hash(self, storage):
        """get_user_api_tokens should exclude token_hash."""
        user_id = 'user123'
        token = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'name': 'Test Token',
            'token_hash': 'secret_hash',
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        storage.save_api_token(token['id'], token)

        tokens = storage.get_user_api_tokens(user_id)
        assert len(tokens) == 1
        assert 'token_hash' not in tokens[0]

    def test_delete_api_token(self, storage):
        """Should delete an API token."""
        token_id = str(uuid.uuid4())
        token = {
            'id': token_id,
            'user_id': 'user123',
            'name': 'Test Token',
            'token_hash': 'hash123'
        }

        storage.save_api_token(token_id, token)
        result = storage.delete_api_token(token_id)

        assert result is True
        assert storage.get_api_token(token_id) is None


class TestFlatFileAuditLogStorage:
    """Tests for FlatFileStorage audit log operations."""

    @pytest.fixture
    def storage(self):
        """Create a temporary storage directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FlatFileStorage(config_dir=tmpdir)

    def test_add_audit_entry(self, storage):
        """Should add an audit entry."""
        entry = {
            'user': 'testuser',
            'action': 'login',
            'resource': 'auth',
            'success': True,
            'ip_address': '192.168.1.1'
        }

        result = storage.add_audit_entry(entry)
        assert result is True

    def test_get_audit_log(self, storage):
        """Should retrieve audit log entries."""
        entry1 = {'user': 'user1', 'action': 'login', 'resource': 'auth', 'success': True}
        entry2 = {'user': 'user2', 'action': 'logout', 'resource': 'auth', 'success': True}

        storage.add_audit_entry(entry1)
        storage.add_audit_entry(entry2)

        entries = storage.get_audit_log()
        assert len(entries) == 2

    def test_get_audit_log_with_filters(self, storage):
        """Should filter audit log entries."""
        entry1 = {'user': 'user1', 'action': 'login', 'resource': 'auth', 'success': True}
        entry2 = {'user': 'user2', 'action': 'login', 'resource': 'auth', 'success': False}

        storage.add_audit_entry(entry1)
        storage.add_audit_entry(entry2)

        # Filter by user
        entries = storage.get_audit_log(filters={'user': 'user1'})
        assert len(entries) == 1
        assert entries[0]['user'] == 'user1'

        # Filter by success
        entries = storage.get_audit_log(filters={'success': False})
        assert len(entries) == 1
        assert entries[0]['user'] == 'user2'

    def test_get_audit_log_pagination(self, storage):
        """Should support pagination."""
        for i in range(10):
            storage.add_audit_entry({
                'user': f'user{i}',
                'action': 'test',
                'resource': 'test',
                'success': True
            })

        # Get first 5
        entries = storage.get_audit_log(limit=5)
        assert len(entries) == 5

        # Get next 5
        entries = storage.get_audit_log(limit=5, offset=5)
        assert len(entries) == 5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
