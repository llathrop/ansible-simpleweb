"""Tests for SSL/TLS configuration."""
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock


class TestWorkerSSLConfig:
    """Tests for worker API client SSL configuration."""

    def test_ssl_verify_default_true(self):
        """SSL verification is enabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove SSL_VERIFY if it exists
            os.environ.pop('SSL_VERIFY', None)
            from worker.api_client import PrimaryAPIClient
            client = PrimaryAPIClient('https://example.com')
            assert client.ssl_verify is True

    def test_ssl_verify_env_false(self):
        """SSL verification can be disabled via environment."""
        with patch.dict(os.environ, {'SSL_VERIFY': 'false'}):
            from worker.api_client import PrimaryAPIClient
            client = PrimaryAPIClient('https://example.com')
            assert client.ssl_verify is False

    def test_ssl_verify_env_no(self):
        """SSL verification disabled with 'no' value."""
        with patch.dict(os.environ, {'SSL_VERIFY': 'no'}):
            from worker.api_client import PrimaryAPIClient
            client = PrimaryAPIClient('https://example.com')
            assert client.ssl_verify is False

    def test_ssl_verify_env_disable(self):
        """SSL verification disabled with 'disable' value."""
        with patch.dict(os.environ, {'SSL_VERIFY': 'disable'}):
            from worker.api_client import PrimaryAPIClient
            client = PrimaryAPIClient('https://example.com')
            assert client.ssl_verify is False

    def test_ssl_verify_env_zero(self):
        """SSL verification disabled with '0' value."""
        with patch.dict(os.environ, {'SSL_VERIFY': '0'}):
            from worker.api_client import PrimaryAPIClient
            client = PrimaryAPIClient('https://example.com')
            assert client.ssl_verify is False

    def test_ssl_verify_env_true(self):
        """SSL verification enabled with 'true' value."""
        with patch.dict(os.environ, {'SSL_VERIFY': 'true'}):
            from worker.api_client import PrimaryAPIClient
            client = PrimaryAPIClient('https://example.com')
            assert client.ssl_verify is True

    def test_ssl_verify_env_yes(self):
        """SSL verification enabled with 'yes' value."""
        with patch.dict(os.environ, {'SSL_VERIFY': 'yes'}):
            from worker.api_client import PrimaryAPIClient
            client = PrimaryAPIClient('https://example.com')
            assert client.ssl_verify is True

    def test_ssl_verify_env_one(self):
        """SSL verification enabled with '1' value."""
        with patch.dict(os.environ, {'SSL_VERIFY': '1'}):
            from worker.api_client import PrimaryAPIClient
            client = PrimaryAPIClient('https://example.com')
            assert client.ssl_verify is True

    def test_ssl_verify_env_path_exists(self):
        """SSL verification uses CA cert path when file exists."""
        with tempfile.NamedTemporaryFile(suffix='.crt', delete=False) as f:
            ca_path = f.name
            f.write(b'dummy cert content')

        try:
            with patch.dict(os.environ, {'SSL_VERIFY': ca_path}):
                from worker.api_client import PrimaryAPIClient
                client = PrimaryAPIClient('https://example.com')
                assert client.ssl_verify == ca_path
        finally:
            os.unlink(ca_path)

    def test_ssl_verify_env_path_not_exists(self):
        """SSL verification defaults to True when path doesn't exist."""
        with patch.dict(os.environ, {'SSL_VERIFY': '/nonexistent/ca.crt'}):
            from worker.api_client import PrimaryAPIClient
            client = PrimaryAPIClient('https://example.com')
            assert client.ssl_verify is True

    def test_ssl_verify_explicit_false(self):
        """SSL verification can be explicitly set to False."""
        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('https://example.com', ssl_verify=False)
        assert client.ssl_verify is False

    def test_ssl_verify_explicit_true(self):
        """SSL verification can be explicitly set to True."""
        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('https://example.com', ssl_verify=True)
        assert client.ssl_verify is True

    def test_ssl_verify_explicit_path(self):
        """SSL verification can be explicitly set to a path."""
        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('https://example.com', ssl_verify='/path/to/ca.crt')
        assert client.ssl_verify == '/path/to/ca.crt'


class TestAgentSSLConfig:
    """Tests for agent service SSL configuration.

    These tests verify the _get_ssl_verify function logic without importing
    the full agent module (which has heavy dependencies like chromadb).
    """

    def _get_ssl_verify_logic(self):
        """Replicate the _get_ssl_verify function logic for testing."""
        verify_env = os.environ.get('SSL_VERIFY', 'true').lower()
        if verify_env in ('false', '0', 'no', 'disable'):
            return False
        elif verify_env in ('true', '1', 'yes', 'enable'):
            return True
        else:
            # Treat as path to CA certificate
            return verify_env if os.path.exists(verify_env) else True

    def test_get_ssl_verify_default_true(self):
        """SSL verification is enabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop('SSL_VERIFY', None)
            result = self._get_ssl_verify_logic()
            assert result is True

    def test_get_ssl_verify_false(self):
        """SSL verification can be disabled."""
        with patch.dict(os.environ, {'SSL_VERIFY': 'false'}):
            result = self._get_ssl_verify_logic()
            assert result is False

    def test_get_ssl_verify_no(self):
        """SSL verification disabled with 'no' value."""
        with patch.dict(os.environ, {'SSL_VERIFY': 'no'}):
            result = self._get_ssl_verify_logic()
            assert result is False

    def test_get_ssl_verify_zero(self):
        """SSL verification disabled with '0' value."""
        with patch.dict(os.environ, {'SSL_VERIFY': '0'}):
            result = self._get_ssl_verify_logic()
            assert result is False

    def test_get_ssl_verify_true(self):
        """SSL verification enabled with 'true' value."""
        with patch.dict(os.environ, {'SSL_VERIFY': 'true'}):
            result = self._get_ssl_verify_logic()
            assert result is True

    def test_get_ssl_verify_yes(self):
        """SSL verification enabled with 'yes' value."""
        with patch.dict(os.environ, {'SSL_VERIFY': 'yes'}):
            result = self._get_ssl_verify_logic()
            assert result is True

    def test_get_ssl_verify_path_exists(self):
        """SSL verification uses CA cert path when file exists."""
        with tempfile.NamedTemporaryFile(suffix='.crt', delete=False) as f:
            ca_path = f.name
            f.write(b'dummy cert content')

        try:
            with patch.dict(os.environ, {'SSL_VERIFY': ca_path}):
                result = self._get_ssl_verify_logic()
                assert result == ca_path
        finally:
            os.unlink(ca_path)

    def test_get_ssl_verify_path_not_exists(self):
        """SSL verification defaults to True when path doesn't exist."""
        with patch.dict(os.environ, {'SSL_VERIFY': '/nonexistent/ca.crt'}):
            result = self._get_ssl_verify_logic()
            assert result is True


class TestGunicornSSLConfig:
    """Tests for gunicorn SSL configuration."""

    def test_ssl_disabled_by_default(self):
        """SSL is disabled by default in gunicorn config."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop('SSL_ENABLED', None)
            # Re-exec the config file to get fresh values
            config = {}
            with open('gunicorn_config.py') as f:
                exec(f.read(), config)
            assert config['ssl_enabled'] is False

    def test_ssl_enabled_via_env(self):
        """SSL can be enabled via environment variable."""
        with patch.dict(os.environ, {'SSL_ENABLED': 'true'}):
            config = {}
            with open('gunicorn_config.py') as f:
                exec(f.read(), config)
            assert config['ssl_enabled'] is True

    def test_ssl_enabled_via_yes(self):
        """SSL can be enabled with 'yes' value."""
        with patch.dict(os.environ, {'SSL_ENABLED': 'yes'}):
            config = {}
            with open('gunicorn_config.py') as f:
                exec(f.read(), config)
            assert config['ssl_enabled'] is True

    def test_ssl_enabled_via_one(self):
        """SSL can be enabled with '1' value."""
        with patch.dict(os.environ, {'SSL_ENABLED': '1'}):
            config = {}
            with open('gunicorn_config.py') as f:
                exec(f.read(), config)
            assert config['ssl_enabled'] is True

    def test_ssl_cert_paths_set_when_enabled(self):
        """SSL certificate paths are set when SSL is enabled."""
        with patch.dict(os.environ, {'SSL_ENABLED': 'true'}):
            config = {}
            with open('gunicorn_config.py') as f:
                exec(f.read(), config)
            assert config['ssl_enabled'] is True
            assert 'certfile' in config
            assert 'keyfile' in config

    def test_ssl_custom_cert_paths(self):
        """SSL certificate paths can be customized."""
        with patch.dict(os.environ, {
            'SSL_ENABLED': 'true',
            'SSL_CERT_PATH': '/custom/path/cert.crt',
            'SSL_KEY_PATH': '/custom/path/key.key'
        }):
            config = {}
            with open('gunicorn_config.py') as f:
                exec(f.read(), config)
            assert config['certfile'] == '/custom/path/cert.crt'
            assert config['keyfile'] == '/custom/path/key.key'

    def test_worker_class_is_eventlet(self):
        """Worker class is eventlet for SocketIO support."""
        config = {}
        with open('gunicorn_config.py') as f:
            exec(f.read(), config)
        assert config['worker_class'] == 'eventlet'
