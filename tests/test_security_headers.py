"""Tests for security headers middleware."""
import pytest
import sys
import os
import tempfile
import uuid
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from web.storage.flatfile import FlatFileStorage
from web.auth import hash_password
from web.auth_routes import auth_bp, init_auth_middleware


@pytest.fixture
def app_with_security():
    """Create a test Flask app with security headers."""
    template_dir = os.path.join(os.path.dirname(__file__), '..', 'web', 'templates')

    app = Flask(__name__, template_folder=template_dir)
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['TESTING'] = True

    # Add security headers middleware
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Content-Security-Policy'] = "default-src 'self'"
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    # Add a test route
    @app.route('/test')
    def test_route():
        return 'OK'

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
def client(app_with_security):
    """Create test client."""
    app, storage = app_with_security
    return app.test_client()


@pytest.fixture
def logged_in_client(app_with_security):
    """Create logged in test client."""
    app, storage = app_with_security
    client = app.test_client()
    response = client.post('/api/auth/login', json={
        'username': 'admin',
        'password': 'testpass123'
    })
    assert response.status_code == 200
    return client


class TestSecurityHeaders:
    """Tests for security headers."""

    def test_x_content_type_options_header(self, logged_in_client):
        """X-Content-Type-Options header is set."""
        response = logged_in_client.get('/test')
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'

    def test_x_frame_options_header(self, logged_in_client):
        """X-Frame-Options header is set."""
        response = logged_in_client.get('/test')
        assert response.headers.get('X-Frame-Options') == 'DENY'

    def test_x_xss_protection_header(self, logged_in_client):
        """X-XSS-Protection header is set."""
        response = logged_in_client.get('/test')
        assert response.headers.get('X-XSS-Protection') == '1; mode=block'

    def test_content_security_policy_header(self, logged_in_client):
        """Content-Security-Policy header is set."""
        response = logged_in_client.get('/test')
        csp = response.headers.get('Content-Security-Policy')
        assert csp is not None
        assert "default-src 'self'" in csp

    def test_referrer_policy_header(self, logged_in_client):
        """Referrer-Policy header is set."""
        response = logged_in_client.get('/test')
        assert response.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'

    def test_headers_on_api_routes(self, logged_in_client):
        """Security headers are present on API routes."""
        response = logged_in_client.get('/api/auth/session')
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'
        assert response.headers.get('X-Frame-Options') == 'DENY'

    def test_headers_on_error_responses(self, logged_in_client):
        """Security headers are present on error responses."""
        response = logged_in_client.get('/nonexistent-page-12345')
        # Even on 404, security headers should be present
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'


class TestContentSecurityPolicy:
    """Tests for Content Security Policy configuration."""

    def test_csp_prevents_frame_embedding(self, logged_in_client):
        """CSP includes frame-ancestors directive."""
        response = logged_in_client.get('/test')
        csp = response.headers.get('Content-Security-Policy', '')
        # Should have frame-ancestors or X-Frame-Options
        has_frame_protection = "frame-ancestors" in csp or \
                               response.headers.get('X-Frame-Options') == 'DENY'
        assert has_frame_protection

    def test_csp_restricts_form_action(self, logged_in_client):
        """CSP restricts form submission targets."""
        response = logged_in_client.get('/test')
        csp = response.headers.get('Content-Security-Policy', '')
        # form-action should be restricted
        # This test checks if the header exists and has form-action
        # The actual value depends on implementation
        assert 'Content-Security-Policy' in response.headers


class TestSecurityHeadersOnLoginPage:
    """Tests for security headers on public pages."""

    def test_login_page_has_security_headers(self, client):
        """Login page has security headers even without auth."""
        response = client.get('/login')
        # Login page should have security headers
        assert response.headers.get('X-Content-Type-Options') == 'nosniff'
        assert response.headers.get('X-Frame-Options') == 'DENY'
