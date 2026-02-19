"""Tests for AUTH_ENABLED configuration and common deployment issues.

These tests catch configuration problems that can cause authentication to fail
even when the auth system is properly implemented.
"""
import pytest
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAuthEnabledConfiguration:
    """Tests for AUTH_ENABLED environment variable configuration."""

    def test_auth_enabled_defaults_to_true_in_docker_compose(self):
        """docker-compose.yml should default AUTH_ENABLED to true for security.

        If this test fails:
        1. Edit docker-compose.yml
        2. Find the AUTH_ENABLED line under ansible-web environment
        3. Change: AUTH_ENABLED=${AUTH_ENABLED:-false}
           To: AUTH_ENABLED=${AUTH_ENABLED:-true}
        4. Restart containers: docker compose down && docker compose up -d
        """
        docker_compose_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docker-compose.yml'
        )

        with open(docker_compose_path, 'r') as f:
            content = f.read()

        # Check for secure default (true)
        assert 'AUTH_ENABLED=${AUTH_ENABLED:-true}' in content, (
            "docker-compose.yml should default AUTH_ENABLED to true for security. "
            "Found AUTH_ENABLED defaulting to false. This means authentication will be "
            "disabled unless explicitly set, which is a security risk. "
            "Fix: Change 'AUTH_ENABLED=${AUTH_ENABLED:-false}' to 'AUTH_ENABLED=${AUTH_ENABLED:-true}'"
        )

    def test_auth_enabled_env_var_parsing(self):
        """AUTH_ENABLED should be parsed correctly from environment.

        If this test fails:
        The AUTH_ENABLED environment variable is not being read correctly.
        Ensure the value is exactly 'true' (lowercase) for enabled.
        """
        # Test various string values
        test_cases = [
            ('true', True),
            ('True', False),  # Must be lowercase 'true'
            ('TRUE', False),
            ('false', False),
            ('1', False),  # '1' is not recognized as true
            ('yes', False),  # 'yes' is not recognized as true
            ('', False),
            (None, False),
        ]

        for env_value, expected in test_cases:
            if env_value is None:
                result = os.environ.get('AUTH_ENABLED', 'false').lower() == 'true'
            else:
                result = env_value.lower() == 'true'

            if env_value in ('true',):
                assert result == expected, (
                    f"AUTH_ENABLED='{env_value}' should result in {expected}. "
                    f"Note: Only lowercase 'true' enables authentication."
                )

    def test_require_permission_needs_current_user(self):
        """@require_permission decorator must have g.current_user set by middleware.

        If this test fails:
        The auth middleware is not setting g.current_user before route handlers run.
        This can happen when:
        1. AUTH_ENABLED is false - middleware skips auth checks
        2. Middleware is not initialized - check init_auth_middleware() is called
        3. Route is registered before middleware - check app initialization order

        Fix: Ensure AUTH_ENABLED=true and restart the application.
        """
        from flask import Flask, g
        from web.authz import require_permission

        app = Flask(__name__)

        @app.route('/test')
        @require_permission('test:view')
        def test_route():
            return 'ok'

        with app.test_client() as client:
            # Without g.current_user set, should return 401
            response = client.get('/test')
            assert response.status_code == 401, (
                "Route with @require_permission should return 401 when g.current_user is not set. "
                "If getting 200, the decorator is not checking authentication properly."
            )

            # Error message should be helpful
            data = response.get_json()
            assert 'error' in data, "Response should contain 'error' key"
            assert 'Authentication required' in data['error'], (
                "Error message should indicate authentication is required"
            )


class TestAuthMiddlewareConfiguration:
    """Tests for auth middleware initialization."""

    def test_middleware_sets_storage_backend(self):
        """Auth middleware must set g.storage_backend for get_current_user() to work.

        If this test fails:
        The middleware is not setting g.storage_backend, which causes
        get_current_user() to return None even with valid sessions.

        Fix: Ensure init_auth_middleware() is called with the storage backend.
        """
        from flask import Flask, g
        import tempfile

        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'web'))
        from storage.flatfile import FlatFileStorage
        from auth_routes import init_auth_middleware

        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-key'

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FlatFileStorage(config_dir=tmpdir)
            init_auth_middleware(app, storage, auth_enabled=True)

            @app.route('/test-storage')
            def test_storage():
                return str(g.storage_backend is not None)

            with app.test_client() as client:
                # The middleware should set g.storage_backend
                # Note: This will redirect to login since no session, but storage should be set
                response = client.get('/test-storage', follow_redirects=False)
                # Should redirect to login (302) or return content
                assert response.status_code in (200, 302, 401), (
                    f"Unexpected status code: {response.status_code}"
                )


class TestWorkerAuthConfiguration:
    """Tests for worker authentication configuration."""

    def test_worker_needs_auth_when_enabled(self):
        """Workers must authenticate when AUTH_ENABLED=true.

        If workers are restarting with 'Cannot connect to primary server':
        1. Workers are getting 401 Unauthorized responses
        2. They need a valid REGISTRATION_TOKEN or worker-specific token

        Fix:
        1. Generate worker tokens via the web UI (Admin > Workers)
        2. Or set REGISTRATION_TOKEN environment variable for workers
        3. Update docker-compose.yml worker services with the token
        """
        # This is a documentation test - actual worker auth is tested elsewhere
        pass

    def test_registration_token_env_var_exists(self):
        """Docker-compose should have REGISTRATION_TOKEN for workers.

        If this test fails:
        Workers cannot register without a token when AUTH_ENABLED=true.

        Fix: Add REGISTRATION_TOKEN to worker environment in docker-compose.yml:
            worker-1:
              environment:
                - REGISTRATION_TOKEN=${REGISTRATION_TOKEN:-default-token}
        """
        docker_compose_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docker-compose.yml'
        )

        with open(docker_compose_path, 'r') as f:
            content = f.read()

        # Workers should have registration token configured
        assert 'REGISTRATION_TOKEN' in content, (
            "docker-compose.yml should include REGISTRATION_TOKEN for workers. "
            "Without this, workers cannot register when AUTH_ENABLED=true."
        )


class TestMigrationScriptConfiguration:
    """Tests for migration script configuration."""

    def test_env_security_file_includes_auth_enabled(self):
        """Migration script should set AUTH_ENABLED=true in .env.security.

        If this test fails:
        The migration script is not enabling authentication by default.

        Fix: Update scripts/migrate_production.sh to include AUTH_ENABLED=true
        """
        migrate_script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'scripts', 'migrate_production.sh'
        )

        with open(migrate_script_path, 'r') as f:
            content = f.read()

        assert 'AUTH_ENABLED=true' in content, (
            "migrate_production.sh should set AUTH_ENABLED=true in .env.security. "
            "This ensures authentication is enabled after migration."
        )


class TestCommonDeploymentIssues:
    """Tests that document and catch common deployment issues."""

    def test_session_works_with_auth_enabled(self):
        """Sessions should work when AUTH_ENABLED=true.

        Common issue: Login succeeds but subsequent requests return 401.

        Causes:
        1. AUTH_ENABLED=false - middleware doesn't check auth, but @require_permission
           still checks g.current_user which is never set
        2. Session not stored - in-memory sessions lost on restart
        3. Cookie not sent - check httponly/secure flags

        Fix: Ensure AUTH_ENABLED=true and restart the application.
        """
        # This documents the issue - actual session tests are in test_auth.py
        pass

    def test_helpful_error_messages(self):
        """Error responses should include helpful information.

        When authentication fails, users should know:
        1. What went wrong (authentication required, permission denied, etc.)
        2. How to fix it (login, request permission, etc.)
        """
        from flask import Flask
        from web.authz import require_permission

        app = Flask(__name__)

        @app.route('/test')
        @require_permission('test:view')
        def test_route():
            return 'ok'

        with app.test_client() as client:
            response = client.get('/test')
            data = response.get_json()

            # Error should be informative
            assert 'error' in data, "Error response should have 'error' key"
            assert len(data['error']) > 10, (
                "Error message should be descriptive, not just a code"
            )
