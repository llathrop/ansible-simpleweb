"""
Authorization Module for Ansible SimpleWeb

Provides role-based access control (RBAC) functionality including:
- Permission checking
- Role resolution
- Route protection decorators
- Resource filtering
"""

from functools import wraps
from flask import g, jsonify, request
from typing import List, Set, Dict, Optional, Callable
import re


class AuthorizationError(Exception):
    """Raised when authorization fails"""
    pass


# Built-in role definitions
# These are the default roles created on first run
BUILTIN_ROLES = {
    'admin': {
        'name': 'Administrator',
        'description': 'Full access to all resources',
        'permissions': ['*:*'],
        'inherits': []
    },
    'operator': {
        'name': 'Operator',
        'description': 'Run playbooks, manage schedules, view logs',
        'permissions': [
            'playbooks:*',
            'schedules:*',
            'jobs:*',
            'logs:view',
            'inventory:view',
            'workers:view',
            'cmdb:view',
            'agent:view',
            'agent:generate',
            'agent:analyze'
        ],
        'inherits': []
    },
    'monitor': {
        'name': 'Monitor',
        'description': 'Read-only access for monitoring',
        'permissions': [
            'playbooks:view',
            'logs:view',
            'jobs:view',
            'workers:view',
            'cmdb:view',
            'schedules:view',
            'inventory:view',
            'agent:view'
        ],
        'inherits': []
    },
    'servers_admin': {
        'name': 'Server Administrator',
        'description': 'Full access to server resources',
        'permissions': [
            'playbooks.servers:*',
            'inventory.servers:*',
            'schedules:*',
            'logs:view',
            'jobs:view',
            'cmdb:view'
        ],
        'inherits': []
    },
    'servers_operator': {
        'name': 'Server Operator',
        'description': 'Run server playbooks only',
        'permissions': [
            'playbooks.servers:run',
            'playbooks.servers:view',
            'logs:view',
            'inventory.servers:view',
            'jobs:view',
            'cmdb:view'
        ],
        'inherits': []
    },
    'network_admin': {
        'name': 'Network Administrator',
        'description': 'Full access to network resources',
        'permissions': [
            'playbooks.network:*',
            'inventory.network:*',
            'schedules:*',
            'logs:view',
            'jobs:view',
            'cmdb:view'
        ],
        'inherits': []
    },
    'network_operator': {
        'name': 'Network Operator',
        'description': 'Run network playbooks only',
        'permissions': [
            'playbooks.network:run',
            'playbooks.network:view',
            'logs:view',
            'inventory.network:view',
            'jobs:view',
            'cmdb:view'
        ],
        'inherits': []
    },
    'developer': {
        'name': 'Developer',
        'description': 'Create/edit playbooks, test inventory',
        'permissions': [
            'playbooks:edit',
            'playbooks:view',
            'inventory:view',
            'schedules.own:*',
            'jobs:view',
            'logs:view',
            'agent:view',
            'agent:generate'
        ],
        'inherits': []
    },
    'auditor': {
        'name': 'Auditor',
        'description': 'Read-only access including audit logs',
        'permissions': [
            '*:view',
            'audit:view'
        ],
        'inherits': []
    }
}


def permission_matches(permission: str, required_permission: str) -> bool:
    """
    Check if a permission matches a required permission.

    Supports wildcards:
    - '*:*' matches everything
    - 'playbooks:*' matches all playbook actions
    - 'playbooks.servers:*' matches all server playbook actions
    - '*:view' matches all view permissions

    Args:
        permission: Permission to check (e.g., 'playbooks.servers:run')
        required_permission: Required permission pattern (e.g., 'playbooks.servers:run')

    Returns:
        True if permission matches, False otherwise
    """
    # Exact match
    if permission == required_permission:
        return True

    # Full wildcard
    if permission == '*:*':
        return True

    # Parse permissions
    if ':' not in permission or ':' not in required_permission:
        return False

    perm_resource, perm_action = permission.split(':', 1)
    req_resource, req_action = required_permission.split(':', 1)

    # Check action match
    action_match = (perm_action == '*' or perm_action == req_action or req_action == '*')
    if not action_match:
        return False

    # Check resource match
    if perm_resource == '*':
        return True

    if perm_resource == req_resource:
        return True

    # Check hierarchical resource match (e.g., 'playbooks.servers' matches 'playbooks.servers.some')
    if req_resource.startswith(perm_resource + '.'):
        return True

    # Check if required resource is more general (for reverse checking)
    if perm_resource.startswith(req_resource + '.'):
        return True

    return False


def resolve_user_permissions(user: Dict, storage_backend=None) -> Set[str]:
    """
    Resolve all permissions for a user based on their roles.

    Args:
        user: User dict with 'roles' field
        storage_backend: Storage backend to load role definitions (optional)

    Returns:
        Set of permission strings
    """
    permissions = set()
    roles = user.get('roles', [])

    # Get role definitions
    role_defs = {}
    if storage_backend:
        try:
            all_roles = storage_backend.get_all_roles()
            role_defs = {r['name']: r for r in all_roles}
        except Exception:
            pass

    # Fall back to built-in roles if storage fails
    if not role_defs:
        role_defs = BUILTIN_ROLES

    # Resolve permissions from roles (with inheritance)
    def add_role_permissions(role_name: str, visited: Set[str]):
        if role_name in visited:
            return  # Prevent circular inheritance
        visited.add(role_name)

        role_def = role_defs.get(role_name)
        if not role_def:
            return

        # Add role's direct permissions
        permissions.update(role_def.get('permissions', []))

        # Add inherited role permissions
        for inherited_role in role_def.get('inherits', []):
            add_role_permissions(inherited_role, visited)

    # Process each role
    for role in roles:
        add_role_permissions(role, set())

    return permissions


def check_permission(user: Dict, required_permission: str, storage_backend=None) -> bool:
    """
    Check if a user has a required permission.

    Args:
        user: User dict with 'roles' field
        required_permission: Permission to check (e.g., 'playbooks:run')
        storage_backend: Storage backend to load role definitions (optional)

    Returns:
        True if user has permission, False otherwise
    """
    if not user:
        return False

    # Get all user permissions
    user_permissions = resolve_user_permissions(user, storage_backend)

    # Check if any permission matches
    for permission in user_permissions:
        if permission_matches(permission, required_permission):
            return True

    return False


def require_permission(permission: str):
    """
    Decorator to require a permission for a route.

    Usage:
        @app.route('/playbooks')
        @require_permission('playbooks:view')
        def view_playbooks():
            ...

    Args:
        permission: Required permission (e.g., 'playbooks:view')

    Returns:
        Decorated function
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get current user from Flask g
            user = getattr(g, 'current_user', None)

            if not user:
                return jsonify({'error': 'Authentication required'}), 401

            # Check permission
            storage = getattr(g, 'storage_backend', None)
            if not check_permission(user, permission, storage):
                return jsonify({
                    'error': 'Permission denied',
                    'required_permission': permission
                }), 403

            return f(*args, **kwargs)

        return decorated_function
    return decorator


def require_any_permission(*permissions: str):
    """
    Decorator to require ANY of the specified permissions.

    Usage:
        @app.route('/resources')
        @require_any_permission('resources:view', 'resources:admin')
        def view_resources():
            ...

    Args:
        *permissions: List of acceptable permissions

    Returns:
        Decorated function
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = getattr(g, 'current_user', None)

            if not user:
                return jsonify({'error': 'Authentication required'}), 401

            storage = getattr(g, 'storage_backend', None)

            # Check if user has any of the required permissions
            for permission in permissions:
                if check_permission(user, permission, storage):
                    return f(*args, **kwargs)

            return jsonify({
                'error': 'Permission denied',
                'required_permissions': list(permissions)
            }), 403

        return decorated_function
    return decorator


def filter_resources_by_permission(
    user: Dict,
    resources: List[Dict],
    resource_type: str,
    action: str = 'view',
    storage_backend=None
) -> List[Dict]:
    """
    Filter a list of resources to only those the user can access.

    Args:
        user: User dict
        resources: List of resource dicts
        resource_type: Type of resource (e.g., 'playbooks', 'inventory')
        action: Action to check (default: 'view')
        storage_backend: Storage backend (optional)

    Returns:
        Filtered list of resources
    """
    if not user:
        return []

    # If user has wildcard permission, return all
    if check_permission(user, f'{resource_type}:*', storage_backend) or \
       check_permission(user, '*:*', storage_backend):
        return resources

    # Filter resources based on permissions
    filtered = []
    for resource in resources:
        # Determine specific permission for this resource
        resource_id = resource.get('id', '')
        resource_tag = resource.get('tag', resource.get('type', ''))

        # Check various permission patterns
        permission_patterns = [
            f'{resource_type}:{action}',  # General permission
            f'{resource_type}.{resource_tag}:{action}',  # Tag-specific
            f'{resource_type}.{resource_id}:{action}',  # ID-specific
        ]

        # Check ownership if resource has created_by field
        if resource.get('created_by') == user.get('id'):
            permission_patterns.append(f'{resource_type}.own:{action}')

        for pattern in permission_patterns:
            if check_permission(user, pattern, storage_backend):
                filtered.append(resource)
                break

    return filtered


def get_user_accessible_tags(user: Dict, resource_type: str, storage_backend=None) -> Set[str]:
    """
    Get the set of tags/categories the user can access for a resource type.

    Args:
        user: User dict
        resource_type: Type of resource (e.g., 'playbooks', 'inventory')
        storage_backend: Storage backend (optional)

    Returns:
        Set of accessible tag names (empty set means no access, None means all access)
    """
    if not user:
        return set()

    # Get all user permissions
    user_permissions = resolve_user_permissions(user, storage_backend)

    # Check for full access
    for perm in user_permissions:
        if permission_matches(perm, '*:*') or permission_matches(perm, f'{resource_type}:*'):
            return None  # None means all access

    # Extract tags from permissions
    tags = set()
    pattern = re.compile(rf'{re.escape(resource_type)}\.([^:]+):')

    for perm in user_permissions:
        match = pattern.match(perm)
        if match:
            tag = match.group(1)
            if tag != 'own':  # Skip 'own' pseudo-tag
                tags.add(tag)

    return tags


def can_user_modify_resource(user: Dict, resource: Dict, action: str, storage_backend=None) -> bool:
    """
    Check if a user can modify a specific resource.

    Args:
        user: User dict
        resource: Resource dict (should have 'created_by' field)
        action: Action to check (e.g., 'edit', 'delete')
        storage_backend: Storage backend (optional)

    Returns:
        True if user can perform action, False otherwise
    """
    if not user or not resource:
        return False

    resource_type = resource.get('type', 'resource')

    # Check for full permission
    if check_permission(user, f'{resource_type}:*', storage_backend) or \
       check_permission(user, f'{resource_type}.all:{action}', storage_backend):
        return True

    # Check for ownership permission
    if resource.get('created_by') == user.get('id'):
        return check_permission(user, f'{resource_type}.own:{action}', storage_backend)

    return False
