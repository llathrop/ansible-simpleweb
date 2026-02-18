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
    from authz import check_permission, resolve_user_permissions
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
    from web.authz import check_permission, resolve_user_permissions


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


# ----- Web Routes -----

@auth_bp.route('/login')
def login_page():
    """Render the login page."""
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    """Log out the current user and redirect to login page."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session_manager.destroy_session(session_id)

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

        return response

    except AccountLockedError as e:
        return jsonify({'error': str(e)}), 423  # Locked
    except AuthenticationError as e:
        return jsonify({'error': str(e)}), 401


@auth_bp.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """
    Log out the current session.

    Returns:
        {"ok": true}
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session_manager.destroy_session(session_id)

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
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username:
        return jsonify({'error': 'Username is required'}), 400
    if not password:
        return jsonify({'error': 'Password is required'}), 400

    # Check if user already exists
    existing = storage.get_user(username)
    if existing:
        return jsonify({'error': 'Username already exists'}), 409

    # Create user
    user = {
        'id': str(uuid.uuid4()),
        'username': username,
        'password_hash': hash_password(password),
        'email': data.get('email', ''),
        'full_name': data.get('full_name', ''),
        'roles': data.get('roles', []),
        'enabled': data.get('enabled', True),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'last_login': None
    }

    if storage.save_user(username, user):
        # Return user without password hash
        user_data = {k: v for k, v in user.items() if k != 'password_hash'}
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
    PUBLIC_ROUTES = {
        '/login',
        '/api/auth/login',
        '/api/auth/session',
        '/health',
        '/api/status',
        '/static/',
        '/favicon.ico'
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
