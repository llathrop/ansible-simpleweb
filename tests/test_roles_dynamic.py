"""Tests for dynamic role CRUD operations."""
import pytest
import json
import sys
import os
import uuid
import tempfile
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, g
from web.storage.flatfile import FlatFileStorage
from web.auth import hash_password
from web.auth_routes import auth_bp, init_auth_middleware


@pytest.fixture
def app_with_storage():
    """Create a test Flask app with auth routes."""
    template_dir = os.path.join(os.path.dirname(__file__), '..', 'web', 'templates')

    app = Flask(__name__, template_folder=template_dir)
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['TESTING'] = True

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FlatFileStorage(config_dir=tmpdir)

        # Create admin user
        admin_user = {
            'id': str(uuid.uuid4()),
            'username': 'admin',
            'password_hash': hash_password('testpass123'),
            'email': 'admin@example.com',
            'roles': ['admin'],
            'enabled': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_user('admin', admin_user)

        # Register blueprint
        app.register_blueprint(auth_bp)

        # Initialize auth middleware
        init_auth_middleware(app, storage, auth_enabled=True)

        yield app, storage


@pytest.fixture
def client(app_with_storage):
    """Create test client."""
    app, storage = app_with_storage
    return app.test_client()


@pytest.fixture
def admin_session(app_with_storage):
    """Create admin user and login session."""
    app, storage = app_with_storage
    client = app.test_client()

    # Login
    response = client.post('/api/auth/login', json={
        'username': 'admin',
        'password': 'testpass123'
    })
    assert response.status_code == 200
    return client


class TestRoleListAPI:
    """Tests for listing roles."""

    def test_list_roles_requires_auth(self, client):
        """Listing roles requires authentication."""
        response = client.get('/api/roles')
        assert response.status_code == 401

    def test_list_roles_returns_builtin(self, admin_session):
        """Listing roles returns builtin roles."""
        response = admin_session.get('/api/roles')
        assert response.status_code == 200
        data = response.get_json()
        assert 'roles' in data
        assert 'builtin_role_ids' in data

        # Check builtin roles are present
        role_ids = [r['id'] for r in data['roles']]
        assert 'admin' in role_ids
        assert 'operator' in role_ids
        assert 'monitor' in role_ids

    def test_builtin_roles_marked(self, admin_session):
        """Builtin roles are marked as builtin."""
        response = admin_session.get('/api/roles')
        data = response.get_json()

        admin_role = next(r for r in data['roles'] if r['id'] == 'admin')
        assert admin_role['builtin'] is True


class TestGetRoleAPI:
    """Tests for getting individual roles."""

    def test_get_builtin_role(self, admin_session):
        """Can get builtin role details."""
        response = admin_session.get('/api/roles/admin')
        assert response.status_code == 200
        data = response.get_json()
        assert data['role']['id'] == 'admin'
        assert data['role']['builtin'] is True
        assert '*:*' in data['role']['permissions']

    def test_get_nonexistent_role(self, admin_session):
        """Getting nonexistent role returns 404."""
        response = admin_session.get('/api/roles/nonexistent')
        assert response.status_code == 404


class TestCreateRoleAPI:
    """Tests for creating custom roles."""

    def test_create_role(self, admin_session):
        """Can create a custom role."""
        response = admin_session.post('/api/roles', json={
            'id': 'custom_viewer',
            'name': 'Custom Viewer',
            'description': 'Custom read-only role',
            'permissions': ['playbooks:view', 'logs:view'],
            'inherits': []
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert data['role']['id'] == 'custom_viewer'

    def test_create_role_with_inheritance(self, admin_session):
        """Can create role that inherits from another."""
        response = admin_session.post('/api/roles', json={
            'id': 'super_monitor',
            'name': 'Super Monitor',
            'description': 'Monitor with extra permissions',
            'permissions': ['schedules:edit'],
            'inherits': ['monitor']
        })
        assert response.status_code == 200
        data = response.get_json()
        assert 'monitor' in data['role']['inherits']

    def test_create_role_empty_id(self, admin_session):
        """Cannot create role with empty ID."""
        response = admin_session.post('/api/roles', json={
            'id': '',
            'name': 'Empty ID Role',
            'permissions': []
        })
        assert response.status_code == 400
        assert 'required' in response.get_json()['error'].lower()

    def test_create_role_invalid_id_format(self, admin_session):
        """Cannot create role with invalid ID format."""
        response = admin_session.post('/api/roles', json={
            'id': 'Invalid Role!',
            'name': 'Invalid',
            'permissions': []
        })
        assert response.status_code == 400

    def test_cannot_create_builtin_role_name(self, admin_session):
        """Cannot create role with builtin role name."""
        response = admin_session.post('/api/roles', json={
            'id': 'admin',
            'name': 'Fake Admin',
            'permissions': ['*:*']
        })
        assert response.status_code == 409

    def test_create_duplicate_role(self, admin_session):
        """Cannot create duplicate custom role."""
        # Create first role
        admin_session.post('/api/roles', json={
            'id': 'duplicate_test',
            'name': 'First',
            'permissions': []
        })

        # Try to create duplicate
        response = admin_session.post('/api/roles', json={
            'id': 'duplicate_test',
            'name': 'Second',
            'permissions': []
        })
        assert response.status_code == 409

    def test_create_role_invalid_inherit(self, admin_session):
        """Cannot create role inheriting from nonexistent role."""
        response = admin_session.post('/api/roles', json={
            'id': 'bad_inherit',
            'name': 'Bad Inherit',
            'permissions': [],
            'inherits': ['nonexistent_role']
        })
        assert response.status_code == 400
        assert 'does not exist' in response.get_json()['error']


class TestUpdateRoleAPI:
    """Tests for updating custom roles."""

    def test_update_custom_role(self, admin_session):
        """Can update a custom role."""
        # Create role first
        admin_session.post('/api/roles', json={
            'id': 'update_test',
            'name': 'Original Name',
            'permissions': ['playbooks:view']
        })

        # Update role
        response = admin_session.put('/api/roles/update_test', json={
            'name': 'Updated Name',
            'description': 'New description',
            'permissions': ['playbooks:view', 'logs:view']
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['role']['name'] == 'Updated Name'
        assert data['role']['description'] == 'New description'
        assert len(data['role']['permissions']) == 2

    def test_cannot_update_builtin_role(self, admin_session):
        """Cannot update builtin roles."""
        response = admin_session.put('/api/roles/admin', json={
            'name': 'Hacked Admin'
        })
        assert response.status_code == 403
        assert 'builtin' in response.get_json()['error'].lower()

    def test_update_nonexistent_role(self, admin_session):
        """Updating nonexistent role returns 404."""
        response = admin_session.put('/api/roles/nonexistent', json={
            'name': 'New Name'
        })
        assert response.status_code == 404


class TestDeleteRoleAPI:
    """Tests for deleting custom roles."""

    def test_delete_custom_role(self, admin_session):
        """Can delete a custom role."""
        # Create role first
        admin_session.post('/api/roles', json={
            'id': 'delete_test',
            'name': 'Delete Test',
            'permissions': []
        })

        # Delete role
        response = admin_session.delete('/api/roles/delete_test')
        assert response.status_code == 200
        assert response.get_json()['ok'] is True

        # Verify deleted
        response = admin_session.get('/api/roles/delete_test')
        assert response.status_code == 404

    def test_cannot_delete_builtin_role(self, admin_session):
        """Cannot delete builtin roles."""
        response = admin_session.delete('/api/roles/admin')
        assert response.status_code == 403
        assert 'builtin' in response.get_json()['error'].lower()

    def test_delete_nonexistent_role(self, admin_session):
        """Deleting nonexistent role returns 404."""
        response = admin_session.delete('/api/roles/nonexistent')
        assert response.status_code == 404

    def test_cannot_delete_role_assigned_to_users(self, admin_session):
        """Cannot delete role that is assigned to users."""
        # Create custom role
        admin_session.post('/api/roles', json={
            'id': 'assigned_role',
            'name': 'Assigned Role',
            'permissions': ['playbooks:view']
        })

        # Create user with this role
        admin_session.post('/api/users', json={
            'username': 'roleuser',
            'password': 'testpass123',
            'roles': ['assigned_role']
        })

        # Try to delete role
        response = admin_session.delete('/api/roles/assigned_role')
        assert response.status_code == 400
        assert 'assigned to users' in response.get_json()['error']


class TestPermissionsAPI:
    """Tests for permission reference endpoint."""

    def test_list_permissions(self, admin_session):
        """Can list available permissions."""
        response = admin_session.get('/api/permissions')
        assert response.status_code == 200
        data = response.get_json()
        assert 'permissions' in data
        assert 'wildcards' in data

        # Check some expected permissions
        resources = [p['resource'] for p in data['permissions']]
        assert 'playbooks' in resources
        assert 'inventory' in resources
        assert 'users' in resources


class TestRolePages:
    """Tests for role management UI pages."""

    def test_roles_page_requires_auth(self, client):
        """Roles page requires authentication."""
        response = client.get('/roles')
        assert response.status_code == 302
        assert '/login' in response.location

    def test_roles_page_accessible_to_admin(self, admin_session):
        """Admin can access roles page."""
        response = admin_session.get('/roles')
        assert response.status_code == 200

    def test_new_role_page_accessible(self, admin_session):
        """Admin can access new role page."""
        response = admin_session.get('/roles/new')
        assert response.status_code == 200

    def test_edit_role_page_accessible(self, admin_session):
        """Admin can access edit role page."""
        # Create role first
        admin_session.post('/api/roles', json={
            'id': 'edit_page_test',
            'name': 'Edit Page Test',
            'permissions': []
        })

        response = admin_session.get('/roles/edit_page_test/edit')
        assert response.status_code == 200


class TestRoleUsageInPermissions:
    """Tests for using custom roles in permission checks."""

    def test_custom_role_can_be_assigned_to_user(self, admin_session):
        """Custom role can be assigned to a user."""
        # Create custom role
        response = admin_session.post('/api/roles', json={
            'id': 'test_custom',
            'name': 'Test Custom',
            'permissions': ['playbooks:view', 'logs:view']
        })
        assert response.status_code == 200

        # Create user with custom role
        response = admin_session.post('/api/users', json={
            'username': 'customuser',
            'password': 'testpass123',
            'roles': ['test_custom']
        })
        assert response.status_code == 200

        # Verify user has the role assigned
        response = admin_session.get('/api/users/customuser')
        data = response.get_json()
        assert 'test_custom' in data['user']['roles']

    def test_inherited_role_can_be_created(self, admin_session):
        """Custom role inheriting from builtin can be created."""
        # Create custom role inheriting from monitor
        response = admin_session.post('/api/roles', json={
            'id': 'monitor_plus',
            'name': 'Monitor Plus',
            'permissions': ['schedules:edit'],  # Extra permission
            'inherits': ['monitor']
        })
        assert response.status_code == 200
        data = response.get_json()
        assert 'monitor' in data['role']['inherits']
        assert 'schedules:edit' in data['role']['permissions']


class TestRoleAuditLogging:
    """Tests for audit logging of role operations.

    Note: Full audit logging is tested in test_audit_log.py. These tests verify
    that role CRUD operations complete without error (audit logging happens
    as a side effect).
    """

    def test_create_role_succeeds(self, admin_session):
        """Role creation completes successfully (audit is logged as side effect)."""
        response = admin_session.post('/api/roles', json={
            'id': 'audit_create_test',
            'name': 'Audit Create Test',
            'permissions': []
        })
        assert response.status_code == 200
        assert response.get_json()['ok'] is True

    def test_update_role_succeeds(self, admin_session):
        """Role update completes successfully (audit is logged as side effect)."""
        admin_session.post('/api/roles', json={
            'id': 'audit_update_test',
            'name': 'Original',
            'permissions': []
        })

        response = admin_session.put('/api/roles/audit_update_test', json={
            'name': 'Updated'
        })
        assert response.status_code == 200
        assert response.get_json()['ok'] is True

    def test_delete_role_succeeds(self, admin_session):
        """Role deletion completes successfully (audit is logged as side effect)."""
        admin_session.post('/api/roles', json={
            'id': 'audit_delete_test',
            'name': 'Delete Test',
            'permissions': []
        })

        response = admin_session.delete('/api/roles/audit_delete_test')
        assert response.status_code == 200
        assert response.get_json()['ok'] is True
