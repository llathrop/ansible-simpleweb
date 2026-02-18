"""
Authentication Routes for Ansible SimpleWeb

Provides web routes and API endpoints for:
- Login/logout functionality
- Session management
- User management (CRUD)
- Password changes
"""

import uuid
from datetime import datetime, timezone
from functools import wraps
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, g, make_response

try:
    # When running from within web directory (Flask app)
    from auth import (
        hash_password,
        verify_password,
        authenticate_user,
        authenticate_api_token,
        session_manager,
        login_tracker,
        AuthenticationError,
        AccountLockedError,
        APITokenManager
    )
    from authz import (
        check_permission,
        resolve_user_permissions,
        require_permission,
        require_any_permission
    )
    from validation import (
        ValidationError,
        validate_request,
        validate_username,
        validate_email,
        validate_password,
        validate_role_id,
        validate_permissions,
        validate_roles
    )
except ImportError:
    # When running from project root (tests)
    from web.auth import (
        hash_password,
        verify_password,
        authenticate_user,
        authenticate_api_token,
        session_manager,
        login_tracker,
        AuthenticationError,
        AccountLockedError,
        APITokenManager
    )
    from web.authz import (
        check_permission,
        resolve_user_permissions,
        require_permission,
        require_any_permission
    )
    from web.validation import (
        ValidationError,
        validate_request,
        validate_username,
        validate_email,
        validate_password,
        validate_role_id,
        validate_permissions,
        validate_roles
    )


# Create blueprint for auth routes
auth_bp = Blueprint('auth', __name__)


# Session cookie name
SESSION_COOKIE_NAME = 'ansible_session'


def get_current_user():
    """
    Get the current authenticated user from session or API token.

    Returns:
        User dict if authenticated, None otherwise
    """
    # Check if already resolved in this request
    if hasattr(g, '_current_user_resolved'):
        return g.current_user

    g._current_user_resolved = True
    g.current_user = None

    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return None

    # Try session cookie first
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session = session_manager.validate_session(session_id)
        if session:
            # Get fresh user data from storage
            user = storage.get_user(session['username'])
            if user and user.get('enabled', True):
                g.current_user = user
                return user

    # Try API token (X-API-Token header)
    api_token = request.headers.get('X-API-Token')
    if api_token:
        user = authenticate_api_token(storage, api_token)
        if user:
            g.current_user = user
            return user

    return None


def login_required(f):
    """
    Decorator to require authentication for a route.
    Redirects to login page for web routes, returns 401 for API routes.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            # Store the original URL to redirect back after login
            next_url = request.url
            return redirect(f'/login?next={next_url}')
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """
    Decorator to require admin role for a route.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect('/login')

        if not check_permission(user, 'users:*'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Admin access required'}), 403
            return render_template('error.html', error='Admin access required'), 403

        return f(*args, **kwargs)
    return decorated_function


def worker_auth_required(f):
    """
    Decorator to require worker authentication for a route.

    Worker authentication can be:
    1. Valid worker_id in request body/params that matches an existing worker
    2. X-Worker-Id header with a registered worker ID
    3. Registration token for initial registration

    Used for worker-specific endpoints like checkin, job start/complete, log streaming.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        storage = getattr(g, 'storage_backend', None)
        if not storage:
            return jsonify({'error': 'Storage backend not available'}), 500

        # Get worker_id from various sources
        worker_id = None

        # From URL parameter (e.g., /api/workers/<worker_id>/checkin)
        if 'worker_id' in kwargs:
            worker_id = kwargs['worker_id']

        # From request body
        if not worker_id and request.is_json:
            data = request.get_json(silent=True) or {}
            worker_id = data.get('worker_id')

        # From X-Worker-Id header
        if not worker_id:
            worker_id = request.headers.get('X-Worker-Id')

        if not worker_id:
            return jsonify({'error': 'Worker ID required'}), 401

        # Validate worker exists
        worker = storage.get_worker(worker_id)
        if not worker:
            return jsonify({'error': 'Invalid worker ID'}), 401

        # Store worker in request context
        g.current_worker = worker

        return f(*args, **kwargs)
    return decorated_function


def service_auth_required(f):
    """
    Decorator for service-to-service authentication.

    Used for endpoints called by the agent service or other internal services.
    Authentication can be via:
    1. X-Service-Token header matching SERVICE_TOKEN env var
    2. Admin session (admins can access service endpoints)

    If SERVICE_TOKEN is not configured, requires admin session.
    """
    import os

    @wraps(f)
    def decorated_function(*args, **kwargs):
        service_token = os.environ.get('SERVICE_TOKEN')

        # Check X-Service-Token header first
        provided_token = request.headers.get('X-Service-Token')
        if service_token and provided_token == service_token:
            return f(*args, **kwargs)

        # Fall back to admin session
        user = get_current_user()
        if user and check_permission(user, '*:*'):  # Admin check
            return f(*args, **kwargs)

        # No valid auth
        return jsonify({'error': 'Service authentication required'}), 401

    return decorated_function


# ----- Web Routes -----

@auth_bp.route('/login')
def login_page():
    """Render the login page."""
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    """Log out the current user and redirect to login page."""
    # Get user before destroying session for audit log
    user = get_current_user()

    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session_manager.destroy_session(session_id)

    # Audit log: logout
    if user:
        add_audit_entry(
            action='logout',
            resource='auth',
            resource_id=user.get('username'),
            success=True
        )

    response = make_response(redirect('/login'))
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@auth_bp.route('/users')
@admin_required
def users_page():
    """Render the user management page (admin only)."""
    return render_template('users.html')


@auth_bp.route('/users/new')
@admin_required
def new_user_page():
    """Render the new user form (admin only)."""
    return render_template('user_form.html', edit_mode=False)


@auth_bp.route('/users/<username>/edit')
@admin_required
def edit_user_page(username):
    """Render the edit user form (admin only)."""
    return render_template('user_form.html', edit_mode=True, username=username)


# ----- API Routes -----

@auth_bp.route('/api/auth/login', methods=['POST'])
def api_login():
    """
    Authenticate user and create session.

    Request body:
        {"username": "...", "password": "..."}

    Returns:
        {"ok": true, "user": {...}} on success
        {"error": "..."} on failure
    """
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400

    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    try:
        user = authenticate_user(storage, username, password)

        # Create session
        session_id = session_manager.create_session(user)

        # Build response with session cookie
        response_data = {
            'ok': True,
            'user': {
                'id': user.get('id'),
                'username': user['username'],
                'email': user.get('email', ''),
                'full_name': user.get('full_name', ''),
                'roles': user.get('roles', [])
            }
        }

        response = make_response(jsonify(response_data))

        # Set session cookie (httponly, secure in production)
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session_id,
            httponly=True,
            samesite='Lax',
            max_age=session_manager.timeout_seconds
            # secure=True  # Enable when using HTTPS
        )

        # Audit log: successful login
        add_audit_entry(
            action='login',
            resource='auth',
            resource_id=username,
            details={'roles': user.get('roles', [])},
            success=True
        )

        return response

    except AccountLockedError as e:
        # Audit log: account locked
        add_audit_entry(
            action='failed_login',
            resource='auth',
            resource_id=username,
            details={'reason': 'account_locked'},
            success=False
        )
        return jsonify({'error': str(e)}), 423  # Locked
    except AuthenticationError as e:
        # Audit log: failed login
        add_audit_entry(
            action='failed_login',
            resource='auth',
            resource_id=username,
            details={'reason': str(e)},
            success=False
        )
        return jsonify({'error': str(e)}), 401


@auth_bp.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """
    Log out the current session.

    Returns:
        {"ok": true}
    """
    # Get user before destroying session for audit log
    user = get_current_user()

    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session_manager.destroy_session(session_id)

    # Audit log: logout
    if user:
        add_audit_entry(
            action='logout',
            resource='auth',
            resource_id=user.get('username'),
            success=True
        )

    response = make_response(jsonify({'ok': True}))
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@auth_bp.route('/api/auth/session')
def api_session():
    """
    Get current session information.

    Returns:
        {"authenticated": true, "user": {...}} if logged in
        {"authenticated": false} if not logged in
    """
    user = get_current_user()
    if user:
        return jsonify({
            'authenticated': True,
            'user': {
                'id': user.get('id'),
                'username': user['username'],
                'email': user.get('email', ''),
                'full_name': user.get('full_name', ''),
                'roles': user.get('roles', []),
                'permissions': list(resolve_user_permissions(user))
            }
        })
    return jsonify({'authenticated': False})


# ----- User Management API (Admin Only) -----

@auth_bp.route('/api/users', methods=['GET'])
@admin_required
def api_list_users():
    """
    List all users (admin only).

    Returns:
        {"users": [...]}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    users = storage.get_all_users()
    return jsonify({'users': users})


@auth_bp.route('/api/users/<username>', methods=['GET'])
@admin_required
def api_get_user(username):
    """
    Get a specific user (admin only).

    Returns:
        {"user": {...}}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    user = storage.get_user(username)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Exclude password hash
    user_data = {k: v for k, v in user.items() if k != 'password_hash'}
    return jsonify({'user': user_data})


@auth_bp.route('/api/users', methods=['POST'])
@admin_required
def api_create_user():
    """
    Create a new user (admin only).

    Request body:
        {"username": "...", "password": "...", "email": "...", "roles": [...], "enabled": true}

    Returns:
        {"ok": true, "user": {...}}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    data = request.get_json() or {}

    # Validate input using validation module
    try:
        validated = validate_request(data, 'user_create')
        username = validated['username']
        password = validated['password']
        email = validated.get('email', '')
        roles = validated.get('roles', [])
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400

    # Check if user already exists
    existing = storage.get_user(username)
    if existing:
        return jsonify({'error': 'Username already exists'}), 409

    # Create user
    user = {
        'id': str(uuid.uuid4()),
        'username': username,
        'password_hash': hash_password(password),
        'email': email,
        'full_name': data.get('full_name', ''),
        'roles': roles,
        'enabled': data.get('enabled', True),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'last_login': None
    }

    if storage.save_user(username, user):
        # Return user without password hash
        user_data = {k: v for k, v in user.items() if k != 'password_hash'}

        # Audit log: user created
        add_audit_entry(
            action='create',
            resource='users',
            resource_id=username,
            details={'roles': user.get('roles', [])},
            success=True
        )

        return jsonify({'ok': True, 'user': user_data})
    else:
        return jsonify({'error': 'Failed to create user'}), 500


@auth_bp.route('/api/users/<username>', methods=['PUT'])
@admin_required
def api_update_user(username):
    """
    Update an existing user (admin only).

    Request body:
        {"email": "...", "roles": [...], "enabled": true, "password": "..." (optional)}

    Returns:
        {"ok": true, "user": {...}}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    user = storage.get_user(username)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}

    # Update allowed fields
    if 'email' in data:
        user['email'] = data['email']
    if 'full_name' in data:
        user['full_name'] = data['full_name']
    if 'roles' in data:
        user['roles'] = data['roles']
    if 'enabled' in data:
        user['enabled'] = data['enabled']

    # Update password if provided
    if data.get('password'):
        user['password_hash'] = hash_password(data['password'])

    user['updated_at'] = datetime.now(timezone.utc).isoformat()

    if storage.save_user(username, user):
        user_data = {k: v for k, v in user.items() if k != 'password_hash'}

        # Audit log: user updated
        add_audit_entry(
            action='update',
            resource='users',
            resource_id=username,
            details={'fields_updated': list(data.keys())},
            success=True
        )

        return jsonify({'ok': True, 'user': user_data})
    else:
        return jsonify({'error': 'Failed to update user'}), 500


@auth_bp.route('/api/users/<username>', methods=['DELETE'])
@admin_required
def api_delete_user(username):
    """
    Delete a user (admin only).

    Returns:
        {"ok": true}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    # Prevent deleting your own account
    current_user = get_current_user()
    if current_user and current_user.get('username') == username:
        return jsonify({'error': 'Cannot delete your own account'}), 400

    if storage.delete_user(username):
        # Audit log: user deleted
        add_audit_entry(
            action='delete',
            resource='users',
            resource_id=username,
            success=True
        )

        return jsonify({'ok': True})
    else:
        return jsonify({'error': 'User not found or could not be deleted'}), 404


@auth_bp.route('/api/users/<username>/password', methods=['PUT'])
def api_change_password(username):
    """
    Change user password.

    Users can change their own password.
    Admins can change any user's password.

    Request body:
        {"current_password": "...", "new_password": "..."}
        or for admins: {"new_password": "..."}

    Returns:
        {"ok": true}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    current_user = get_current_user()
    if not current_user:
        return jsonify({'error': 'Authentication required'}), 401

    user = storage.get_user(username)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    new_password = data.get('new_password', '')

    if not new_password:
        return jsonify({'error': 'New password is required'}), 400

    # Check if user is changing their own password
    is_self = current_user.get('username') == username
    is_admin = check_permission(current_user, 'users:*')

    if is_self and not is_admin:
        # Regular users must provide current password
        current_password = data.get('current_password', '')
        if not current_password:
            return jsonify({'error': 'Current password is required'}), 400
        if not verify_password(current_password, user['password_hash']):
            return jsonify({'error': 'Current password is incorrect'}), 401
    elif not is_self and not is_admin:
        return jsonify({'error': 'Permission denied'}), 403

    # Update password
    user['password_hash'] = hash_password(new_password)
    user['updated_at'] = datetime.now(timezone.utc).isoformat()

    if storage.save_user(username, user):
        # Audit log: password changed
        add_audit_entry(
            action='update',
            resource='users',
            resource_id=username,
            details={'field': 'password', 'changed_by': current_user.get('username')},
            success=True
        )

        return jsonify({'ok': True})
    else:
        return jsonify({'error': 'Failed to update password'}), 500


# ----- API Token Management -----

@auth_bp.route('/api/tokens', methods=['GET'])
@login_required
def api_list_tokens():
    """
    List current user's API tokens.

    Returns:
        {"tokens": [...]}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    user = get_current_user()
    tokens = storage.get_user_api_tokens(user['id'])
    return jsonify({'tokens': tokens})


@auth_bp.route('/api/tokens', methods=['POST'])
@login_required
def api_create_token():
    """
    Create a new API token for the current user.

    Request body:
        {"name": "...", "expiry_days": 365 (optional)}

    Returns:
        {"ok": true, "token": "...", "token_entry": {...}}

    Note: The raw token is only returned once at creation time.
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    user = get_current_user()
    data = request.get_json() or {}
    name = data.get('name', '').strip()

    if not name:
        return jsonify({'error': 'Token name is required'}), 400

    expiry_days = data.get('expiry_days', 365)
    if expiry_days is not None:
        try:
            expiry_days = int(expiry_days)
        except ValueError:
            return jsonify({'error': 'Invalid expiry_days value'}), 400

    # Create token
    raw_token, token_entry = APITokenManager.create_token_entry(
        user_id=user['id'],
        name=name,
        expiry_days=expiry_days
    )

    if storage.save_api_token(token_entry['id'], token_entry):
        # Return the raw token only once
        return jsonify({
            'ok': True,
            'token': raw_token,
            'token_entry': {
                'id': token_entry['id'],
                'name': token_entry['name'],
                'created_at': token_entry['created_at'],
                'expires_at': token_entry['expires_at']
            }
        })
    else:
        return jsonify({'error': 'Failed to create token'}), 500


@auth_bp.route('/api/tokens/<token_id>', methods=['DELETE'])
@login_required
def api_delete_token(token_id):
    """
    Delete an API token.

    Users can only delete their own tokens.

    Returns:
        {"ok": true}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    user = get_current_user()

    # Verify token belongs to user
    token = storage.get_api_token(token_id)
    if not token:
        return jsonify({'error': 'Token not found'}), 404

    if token.get('user_id') != user['id']:
        # Check if user is admin
        if not check_permission(user, 'users:*'):
            return jsonify({'error': 'Permission denied'}), 403

    if storage.delete_api_token(token_id):
        return jsonify({'ok': True})
    else:
        return jsonify({'error': 'Failed to delete token'}), 500


def init_auth_middleware(app, storage_backend, auth_enabled=True):
    """
    Initialize authentication middleware for the Flask app.

    Args:
        app: Flask application instance
        storage_backend: Storage backend instance
        auth_enabled: Whether authentication is enabled
    """

    # Public routes that don't require authentication
    # Note: Some routes have their own auth (worker_auth_required, registration token, etc.)
    PUBLIC_ROUTES = {
        '/login',
        '/api/auth/login',
        '/api/auth/session',
        '/health',
        '/api/status',
        '/static/',
        '/favicon.ico',
        # Worker routes - use registration token or worker_auth_required decorator
        '/api/workers/register',
        # Theme routes - read-only, allow unauthenticated for login page styling
        '/api/themes',
    }

    # Route prefixes that use their own authentication (worker_auth_required or service_auth_required)
    # These bypass general auth middleware but must have their own auth decorators
    SELF_AUTH_ROUTE_PREFIXES = {
        '/api/workers/',        # Worker checkin, etc. - uses @worker_auth_required
        '/api/jobs/',           # Job start/complete/stream - uses @worker_auth_required
        '/api/sync/',           # Content sync - uses @worker_auth_required
        '/api/test-worker/',    # Test routes - uses @worker_auth_required
        '/api/test-service/',   # Test routes - uses @service_auth_required
    }

    @app.before_request
    def auth_middleware():
        """Check authentication for each request."""
        # Make storage available in request context
        g.storage_backend = storage_backend

        # Skip auth check if disabled
        if not auth_enabled:
            return None

        # Check if route is public
        path = request.path
        for public in PUBLIC_ROUTES:
            if path == public or path.startswith(public):
                return None

        # Check if route handles its own auth (worker_auth_required, etc.)
        for prefix in SELF_AUTH_ROUTE_PREFIXES:
            if path.startswith(prefix):
                return None

        # Check authentication
        user = get_current_user()
        if not user:
            if path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(f'/login?next={request.url}')

        return None


def bootstrap_admin_user(storage_backend, username=None, password=None):
    """
    Create initial admin user if no users exist.

    Called during application startup to ensure at least one admin exists.

    Args:
        storage_backend: Storage backend instance
        username: Admin username (from env var INITIAL_ADMIN_USER)
        password: Admin password (from env var INITIAL_ADMIN_PASSWORD)

    Returns:
        True if admin was created, False otherwise
    """
    import os

    username = username or os.environ.get('INITIAL_ADMIN_USER', 'admin')
    password = password or os.environ.get('INITIAL_ADMIN_PASSWORD')

    if not password:
        print("WARNING: No INITIAL_ADMIN_PASSWORD set, skipping admin bootstrap")
        return False

    # Check if any users exist
    existing_users = storage_backend.get_all_users()
    if existing_users:
        return False

    # Create admin user
    admin_user = {
        'id': str(uuid.uuid4()),
        'username': username,
        'password_hash': hash_password(password),
        'email': '',
        'full_name': 'Administrator',
        'roles': ['admin'],
        'enabled': True,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'last_login': None
    }

    if storage_backend.save_user(username, admin_user):
        print(f"Initial admin user '{username}' created successfully")
        return True
    else:
        print(f"ERROR: Failed to create initial admin user")
        return False


# =============================================================================
# Audit Logging
# =============================================================================

def add_audit_entry(action: str, resource: str, resource_id: str = None, details: dict = None, success: bool = True):
    """
    Add an audit log entry.

    Helper function to log actions for audit trail.

    Args:
        action: Action performed (login, logout, create, update, delete, execute, view)
        resource: Resource type (users, playbooks, schedules, inventory, etc.)
        resource_id: Optional ID or name of specific resource
        details: Optional dict with additional context
        success: Whether the action was successful
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return

    user = get_current_user()

    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'user': user.get('username') if user else None,
        'user_id': user.get('id') if user else None,
        'action': action,
        'resource': resource,
        'resource_id': resource_id,
        'details': details or {},
        'ip_address': request.remote_addr,
        'user_agent': request.headers.get('User-Agent', '')[:200],  # Truncate
        'success': success
    }

    storage.add_audit_entry(entry)


def audit_action(action: str, resource: str, get_resource_id=None, get_details=None):
    """
    Decorator to automatically log route actions to audit trail.

    Args:
        action: Action type (create, update, delete, execute, view)
        resource: Resource type (users, playbooks, schedules, etc.)
        get_resource_id: Optional callable(args, kwargs) to extract resource ID
        get_details: Optional callable(args, kwargs, response) to extract details

    Example:
        @audit_action('execute', 'playbooks', lambda a, k: k.get('playbook'))
        def run_playbook(playbook):
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            resource_id = None
            details = {}

            if get_resource_id:
                try:
                    resource_id = get_resource_id(args, kwargs)
                except Exception:
                    pass

            try:
                response = f(*args, **kwargs)

                # Get details from response if handler provided
                if get_details:
                    try:
                        details = get_details(args, kwargs, response)
                    except Exception:
                        pass

                add_audit_entry(action, resource, resource_id, details, success=True)
                return response

            except Exception as e:
                details['error'] = str(e)
                add_audit_entry(action, resource, resource_id, details, success=False)
                raise

        return decorated_function
    return decorator


# ----- Audit Log Routes -----

@auth_bp.route('/audit')
@require_permission('audit:view')
def audit_page():
    """Render the audit log viewer page."""
    return render_template('audit.html')


@auth_bp.route('/api/audit', methods=['GET'])
@require_permission('audit:view')
def api_audit_log():
    """
    Get audit log entries with optional filters.

    Query parameters:
        - user: Filter by username
        - action: Filter by action (login, logout, create, update, delete, execute)
        - resource: Filter by resource type
        - start_time: Filter entries after this time (ISO format)
        - end_time: Filter entries before this time (ISO format)
        - success: Filter by success (true/false)
        - limit: Number of entries to return (default 100, max 1000)
        - offset: Number of entries to skip for pagination

    Returns:
        {
            "entries": [...],
            "total": 1234,
            "limit": 100,
            "offset": 0
        }
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    # Build filters from query params
    filters = {}

    if request.args.get('user'):
        filters['user'] = request.args['user']

    if request.args.get('action'):
        filters['action'] = request.args['action']

    if request.args.get('resource'):
        filters['resource'] = request.args['resource']

    if request.args.get('start_time'):
        filters['start_time'] = request.args['start_time']

    if request.args.get('end_time'):
        filters['end_time'] = request.args['end_time']

    if request.args.get('success') is not None:
        filters['success'] = request.args['success'].lower() == 'true'

    # Pagination
    limit = min(1000, max(1, int(request.args.get('limit', 100))))
    offset = max(0, int(request.args.get('offset', 0)))

    entries = storage.get_audit_log(filters=filters, limit=limit, offset=offset)

    # Get total count (without pagination) for UI
    all_entries = storage.get_audit_log(filters=filters, limit=100000, offset=0)
    total = len(all_entries)

    return jsonify({
        'entries': entries,
        'total': total,
        'limit': limit,
        'offset': offset
    })


@auth_bp.route('/api/audit/export', methods=['GET'])
@require_permission('audit:view')
def api_audit_export():
    """
    Export audit log entries as CSV.

    Query parameters same as /api/audit.

    Returns:
        CSV file download
    """
    import csv
    import io

    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    # Build filters from query params
    filters = {}

    if request.args.get('user'):
        filters['user'] = request.args['user']

    if request.args.get('action'):
        filters['action'] = request.args['action']

    if request.args.get('resource'):
        filters['resource'] = request.args['resource']

    if request.args.get('start_time'):
        filters['start_time'] = request.args['start_time']

    if request.args.get('end_time'):
        filters['end_time'] = request.args['end_time']

    # Get all entries (up to 100k for export)
    entries = storage.get_audit_log(filters=filters, limit=100000, offset=0)

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(['Timestamp', 'User', 'Action', 'Resource', 'Resource ID', 'Success', 'IP Address', 'Details'])

    # Data rows
    for entry in entries:
        writer.writerow([
            entry.get('timestamp', ''),
            entry.get('user', ''),
            entry.get('action', ''),
            entry.get('resource', ''),
            entry.get('resource_id', ''),
            'Yes' if entry.get('success') else 'No',
            entry.get('ip_address', ''),
            str(entry.get('details', {}))
        ])

    output.seek(0)

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=audit_log.csv'

    return response


@auth_bp.route('/api/audit/stats', methods=['GET'])
@require_permission('audit:view')
def api_audit_stats():
    """
    Get audit log statistics.

    Returns summary counts by action and resource type.
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    # Get recent entries for stats
    entries = storage.get_audit_log(limit=10000, offset=0)

    # Count by action
    action_counts = {}
    resource_counts = {}
    user_counts = {}
    success_count = 0
    failure_count = 0

    for entry in entries:
        action = entry.get('action') or 'unknown'
        resource = entry.get('resource') or 'unknown'
        user = entry.get('user') or 'anonymous'

        action_counts[action] = action_counts.get(action, 0) + 1
        resource_counts[resource] = resource_counts.get(resource, 0) + 1
        user_counts[user] = user_counts.get(user, 0) + 1

        if entry.get('success'):
            success_count += 1
        else:
            failure_count += 1

    # Sort top users safely (handle potential None keys)
    sorted_users = sorted(
        [(k, v) for k, v in user_counts.items() if k is not None],
        key=lambda x: x[1],
        reverse=True
    )[:10]

    return jsonify({
        'total_entries': len(entries),
        'by_action': action_counts,
        'by_resource': resource_counts,
        'top_users': dict(sorted_users),
        'success_count': success_count,
        'failure_count': failure_count
    })


# =============================================================================
# Role Management Routes
# =============================================================================

@auth_bp.route('/roles')
@admin_required
def roles_page():
    """Render the role management page (admin only)."""
    return render_template('roles.html')


@auth_bp.route('/roles/new')
@admin_required
def new_role_page():
    """Render the new role form (admin only)."""
    return render_template('role_form.html', edit_mode=False)


@auth_bp.route('/roles/<role_name>/edit')
@admin_required
def edit_role_page(role_name):
    """Render the edit role form (admin only)."""
    return render_template('role_form.html', edit_mode=True, role_name=role_name)


@auth_bp.route('/api/roles', methods=['GET'])
@admin_required
def api_list_roles():
    """
    List all roles (admin only).

    Returns:
        {"roles": [...], "builtin_roles": {...}}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    try:
        from authz import BUILTIN_ROLES
    except ImportError:
        from web.authz import BUILTIN_ROLES

    # Get custom roles from storage
    custom_roles = storage.get_all_roles()

    # Combine with builtin roles (mark which are builtin)
    all_roles = []

    # Add builtin roles first
    for role_id, role_def in BUILTIN_ROLES.items():
        role_data = {
            'id': role_id,
            'name': role_def.get('name', role_id),
            'description': role_def.get('description', ''),
            'permissions': role_def.get('permissions', []),
            'inherits': role_def.get('inherits', []),
            'builtin': True
        }
        all_roles.append(role_data)

    # Add custom roles
    for role in custom_roles:
        role['builtin'] = False
        all_roles.append(role)

    return jsonify({
        'roles': all_roles,
        'builtin_role_ids': list(BUILTIN_ROLES.keys())
    })


@auth_bp.route('/api/roles/<role_name>', methods=['GET'])
@admin_required
def api_get_role(role_name):
    """
    Get a specific role (admin only).

    Returns:
        {"role": {...}}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    try:
        from authz import BUILTIN_ROLES
    except ImportError:
        from web.authz import BUILTIN_ROLES

    # Check builtin roles first
    if role_name in BUILTIN_ROLES:
        role_def = BUILTIN_ROLES[role_name]
        return jsonify({
            'role': {
                'id': role_name,
                'name': role_def.get('name', role_name),
                'description': role_def.get('description', ''),
                'permissions': role_def.get('permissions', []),
                'inherits': role_def.get('inherits', []),
                'builtin': True
            }
        })

    # Check custom roles
    role = storage.get_role(role_name)
    if not role:
        return jsonify({'error': 'Role not found'}), 404

    role['builtin'] = False
    return jsonify({'role': role})


@auth_bp.route('/api/roles', methods=['POST'])
@admin_required
def api_create_role():
    """
    Create a new custom role (admin only).

    Request body:
        {
            "id": "role_id",
            "name": "Role Display Name",
            "description": "Role description",
            "permissions": ["resource:action", ...],
            "inherits": ["other_role_id", ...]
        }

    Returns:
        {"ok": true, "role": {...}}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    try:
        from authz import BUILTIN_ROLES
    except ImportError:
        from web.authz import BUILTIN_ROLES

    data = request.get_json() or {}

    # Validate input using validation module
    try:
        validated = validate_request(data, 'role_create')
        role_id = validated['id']
        permissions = validated.get('permissions', [])
        inherits = validated.get('inherits', [])
    except ValidationError as e:
        return jsonify({'error': str(e)}), 400

    # Check if role already exists (builtin or custom)
    if role_id in BUILTIN_ROLES:
        return jsonify({'error': 'Cannot create role with builtin role name'}), 409

    existing = storage.get_role(role_id)
    if existing:
        return jsonify({'error': 'Role already exists'}), 409

    # Validate inherits references
    for parent_role in inherits:
        if parent_role not in BUILTIN_ROLES and not storage.get_role(parent_role):
            return jsonify({'error': f'Inherited role "{parent_role}" does not exist'}), 400

    # Create role
    from datetime import datetime, timezone
    role = {
        'id': role_id,
        'name': validated.get('name', role_id),
        'description': validated.get('description', ''),
        'permissions': permissions,
        'inherits': inherits,
        'created_at': datetime.now(timezone.utc).isoformat()
    }

    if storage.save_role(role_id, role):
        # Audit log
        add_audit_entry(
            action='create',
            resource='roles',
            resource_id=role_id,
            details={'permissions_count': len(role['permissions'])},
            success=True
        )
        return jsonify({'ok': True, 'role': role})
    else:
        return jsonify({'error': 'Failed to create role'}), 500


@auth_bp.route('/api/roles/<role_name>', methods=['PUT'])
@admin_required
def api_update_role(role_name):
    """
    Update an existing custom role (admin only).

    Builtin roles cannot be modified.

    Request body:
        {
            "name": "Role Display Name",
            "description": "Role description",
            "permissions": ["resource:action", ...],
            "inherits": ["other_role_id", ...]
        }

    Returns:
        {"ok": true, "role": {...}}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    try:
        from authz import BUILTIN_ROLES
    except ImportError:
        from web.authz import BUILTIN_ROLES

    # Cannot modify builtin roles
    if role_name in BUILTIN_ROLES:
        return jsonify({'error': 'Cannot modify builtin roles'}), 403

    role = storage.get_role(role_name)
    if not role:
        return jsonify({'error': 'Role not found'}), 404

    data = request.get_json() or {}

    # Update allowed fields
    if 'name' in data:
        role['name'] = data['name']
    if 'description' in data:
        role['description'] = data['description']
    if 'permissions' in data:
        role['permissions'] = data['permissions']
    if 'inherits' in data:
        # Validate inherits references
        for parent_role in data['inherits']:
            if parent_role not in BUILTIN_ROLES and not storage.get_role(parent_role):
                return jsonify({'error': f'Inherited role "{parent_role}" does not exist'}), 400
        role['inherits'] = data['inherits']

    from datetime import datetime, timezone
    role['updated_at'] = datetime.now(timezone.utc).isoformat()

    if storage.save_role(role_name, role):
        # Audit log
        add_audit_entry(
            action='update',
            resource='roles',
            resource_id=role_name,
            details={'fields_updated': list(data.keys())},
            success=True
        )
        return jsonify({'ok': True, 'role': role})
    else:
        return jsonify({'error': 'Failed to update role'}), 500


@auth_bp.route('/api/roles/<role_name>', methods=['DELETE'])
@admin_required
def api_delete_role(role_name):
    """
    Delete a custom role (admin only).

    Builtin roles cannot be deleted.

    Returns:
        {"ok": true}
    """
    storage = getattr(g, 'storage_backend', None)
    if not storage:
        return jsonify({'error': 'Storage backend not available'}), 500

    try:
        from authz import BUILTIN_ROLES
    except ImportError:
        from web.authz import BUILTIN_ROLES

    # Cannot delete builtin roles
    if role_name in BUILTIN_ROLES:
        return jsonify({'error': 'Cannot delete builtin roles'}), 403

    # Check if any users have this role
    all_users = storage.get_all_users()
    users_with_role = [u['username'] for u in all_users if role_name in u.get('roles', [])]
    if users_with_role:
        return jsonify({
            'error': f'Cannot delete role that is assigned to users: {", ".join(users_with_role[:5])}'
        }), 400

    if storage.delete_role(role_name):
        # Audit log
        add_audit_entry(
            action='delete',
            resource='roles',
            resource_id=role_name,
            success=True
        )
        return jsonify({'ok': True})
    else:
        return jsonify({'error': 'Role not found or could not be deleted'}), 404


@auth_bp.route('/api/permissions', methods=['GET'])
@admin_required
def api_list_permissions():
    """
    List all available permission patterns for reference.

    Returns:
        {"permissions": [...]}
    """
    # Common permission patterns
    permissions = [
        # Playbooks
        {'resource': 'playbooks', 'actions': ['view', 'run', 'edit'], 'description': 'Ansible playbooks'},
        {'resource': 'playbooks.servers', 'actions': ['view', 'run', 'edit'], 'description': 'Server playbooks'},
        {'resource': 'playbooks.network', 'actions': ['view', 'run', 'edit'], 'description': 'Network playbooks'},
        {'resource': 'playbooks.database', 'actions': ['view', 'run', 'edit'], 'description': 'Database playbooks'},
        {'resource': 'playbooks.security', 'actions': ['view', 'run', 'edit'], 'description': 'Security playbooks'},
        # Inventory
        {'resource': 'inventory', 'actions': ['view', 'edit'], 'description': 'Host inventory'},
        {'resource': 'inventory.servers', 'actions': ['view', 'edit'], 'description': 'Server inventory'},
        {'resource': 'inventory.network', 'actions': ['view', 'edit'], 'description': 'Network inventory'},
        # Schedules
        {'resource': 'schedules', 'actions': ['view', 'edit', 'create', 'delete'], 'description': 'Scheduled jobs'},
        {'resource': 'schedules.own', 'actions': ['view', 'edit', 'delete'], 'description': 'Own scheduled jobs'},
        # Jobs
        {'resource': 'jobs', 'actions': ['view', 'submit', 'cancel'], 'description': 'Job management'},
        {'resource': 'jobs.own', 'actions': ['cancel'], 'description': 'Cancel own jobs'},
        # Logs
        {'resource': 'logs', 'actions': ['view'], 'description': 'Execution logs'},
        # Workers
        {'resource': 'workers', 'actions': ['view', 'admin'], 'description': 'Worker management'},
        # CMDB
        {'resource': 'cmdb', 'actions': ['view', 'edit'], 'description': 'Configuration Management DB'},
        # Agent
        {'resource': 'agent', 'actions': ['view', 'generate', 'analyze'], 'description': 'AI Agent features'},
        # Config
        {'resource': 'config', 'actions': ['view', 'edit'], 'description': 'System configuration'},
        # Users
        {'resource': 'users', 'actions': ['view', 'edit', 'create', 'delete'], 'description': 'User management'},
        # Audit
        {'resource': 'audit', 'actions': ['view'], 'description': 'Audit log access'},
    ]

    return jsonify({
        'permissions': permissions,
        'wildcards': {
            '*:*': 'Full access to everything',
            'resource:*': 'All actions on a resource',
            '*:action': 'Action on all resources'
        }
    })
