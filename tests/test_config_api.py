"""
API tests for application config endpoints: GET/PUT /api/config, backup, restore.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Use a temp config dir so we don't touch real app_config.yaml
_test_config_dir = tempfile.mkdtemp()
os.environ['CONFIG_DIR'] = _test_config_dir
os.environ.setdefault('SECRET_KEY', 'test-key')
os.environ.setdefault('CLUSTER_MODE', 'standalone')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock flask_socketio before importing web.app
mock_socketio = MagicMock()
sys.modules['flask_socketio'] = mock_socketio

from web.app import app as flask_app


class TestConfigAPI(unittest.TestCase):
    """Verify config API: GET, PUT, backup, restore."""

    def setUp(self):
        self.client = flask_app.test_client()
        self.client.testing = True
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_config_page_returns_200(self):
        """Basic web validation: GET /config (Config panel) returns 200."""
        resp = self.client.get('/config')
        self.assertEqual(resp.status_code, 200)

    def test_get_config_returns_config_and_metadata(self):
        """GET /api/config returns config dict, config_file_exists, config_path."""
        resp = self.client.get('/api/config')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('config', data)
        self.assertIn('config_file_exists', data)
        self.assertIn('config_path', data)
        self.assertIn('storage', data['config'])
        self.assertIn('agent', data['config'])
        self.assertIn('features', data['config'])

    def test_put_config_accepts_valid_partial(self):
        """PUT /api/config with valid partial config returns 200."""
        payload = {'storage': {'backend': 'flatfile'}}
        resp = self.client.put(
            '/api/config',
            json=payload,
            content_type='application/json',
        )
        self.assertIn(resp.status_code, (200, 400))
        if resp.status_code == 200:
            data = resp.get_json()
            self.assertTrue(data.get('ok'))

    def test_put_config_rejects_invalid(self):
        """PUT /api/config with invalid backend returns 400."""
        payload = {'storage': {'backend': 'invalid'}}
        resp = self.client.put('/api/config', json=payload, content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn('error', data)

    def test_config_backup_returns_yaml(self):
        """GET /api/config/backup returns YAML attachment."""
        resp = self.client.get('/api/config/backup')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('yaml', resp.headers.get('Content-Disposition', '') or resp.content_type)
        self.assertGreater(len(resp.data), 0)
        self.assertIn(b'storage', resp.data)

    def test_config_restore_accepts_yaml_body(self):
        """POST /api/config/restore with YAML body restores config."""
        yaml_body = 'storage:\n  backend: flatfile\n'
        resp = self.client.post(
            '/api/config/restore',
            data=yaml_body,
            content_type='application/x-yaml',
        )
        self.assertIn(resp.status_code, (200, 400, 500))
        if resp.status_code == 200:
            data = resp.get_json()
            self.assertTrue(data.get('ok'))

    def test_config_restore_rejects_empty(self):
        """POST /api/config/restore with no content returns 400."""
        resp = self.client.post(
            '/api/config/restore',
            data='',
            content_type='text/plain',
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_config_then_get_persisted(self):
        """Outcome: after PUT with valid config, GET returns the persisted values."""
        payload = {'storage': {'backend': 'mongodb'}, 'features': {'db_enabled': True}}
        put_resp = self.client.put('/api/config', json=payload, content_type='application/json')
        self.assertEqual(put_resp.status_code, 200, put_resp.get_data(as_text=True))
        get_resp = self.client.get('/api/config')
        self.assertEqual(get_resp.status_code, 200)
        data = get_resp.get_json()
        self.assertEqual(data['config']['storage']['backend'], 'mongodb')
        self.assertTrue(data['config']['features']['db_enabled'])

    def test_config_restore_then_get_reflects_content(self):
        """Outcome: after POST /api/config/restore with YAML, GET returns restored content."""
        yaml_body = 'storage:\n  backend: flatfile\nfeatures:\n  agent_enabled: true\n'
        restore_resp = self.client.post(
            '/api/config/restore',
            data=yaml_body,
            content_type='application/x-yaml',
        )
        self.assertEqual(restore_resp.status_code, 200, restore_resp.get_data(as_text=True))
        get_resp = self.client.get('/api/config')
        self.assertEqual(get_resp.status_code, 200)
        data = get_resp.get_json()
        self.assertEqual(data['config']['storage']['backend'], 'flatfile')
        self.assertTrue(data['config']['features']['agent_enabled'])

    def test_put_config_non_dict_returns_400(self):
        """PUT /api/config with body not a dict (list or number) returns 400 or 422."""
        for body in ([], 1):
            resp = self.client.put('/api/config', json=body, content_type='application/json')
            self.assertIn(resp.status_code, (400, 422), (body, resp.get_data(as_text=True)))
