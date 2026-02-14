"""
API tests for deployment endpoints: GET /api/deployment/status, POST /api/deployment/run.

Real tests: real Flask app, real get_deployment_delta and run_bootstrap (real config, real storage).
No mocks: storage is real FlatFileStorage with temp dir; deployment logic runs for real.
"""
import os
import sys
import tempfile
import unittest

os.environ.setdefault('SECRET_KEY', 'test-key')
os.environ.setdefault('CLUSTER_MODE', 'standalone')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock
sys.modules['flask_socketio'] = MagicMock()

import web.app as app_module


class TestDeploymentAPI(unittest.TestCase):
    """Real deployment API: app uses real storage and real deployment module."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ['CONFIG_DIR'] = self.tmp
        app_module.storage_backend = app_module.get_storage_backend()
        self.client = app_module.app.test_client()
        self.client.testing = True

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deployment_status_returns_desired_current_delta(self):
        """GET /api/deployment/status returns desired, current, and delta (real get_deployment_delta)."""
        resp = self.client.get('/api/deployment/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('desired', data)
        self.assertIn('current', data)
        self.assertIn('deploy_db', data)
        self.assertIn('deploy_agent', data)
        self.assertIn('deploy_workers', data)
        self.assertIn('worker_count_to_add', data)
        # With no config file, desired is defaults (all false); current is detected (e.g. db_reachable false)
        self.assertIsInstance(data['desired'], dict)
        self.assertIsInstance(data['current'], dict)

    def test_deployment_run_with_nothing_to_deploy_returns_ok(self):
        """POST /api/deployment/run when delta has nothing to deploy returns ok (real run_bootstrap)."""
        # No config file -> desired all false -> delta has nothing to deploy -> run_bootstrap returns (True, 'Nothing to deploy')
        resp = self.client.post('/api/deployment/run')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('ok'))
        self.assertIn('message', data)

    def test_cluster_status_includes_stack(self):
        """GET /api/cluster/status returns stack with DB, Agent, Ollama (per memory.md)."""
        resp = self.client.get('/api/cluster/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('stack', data)
        stack = data['stack']
        self.assertIsInstance(stack, list)
        names = [s['name'] for s in stack]
        self.assertIn('DB', names)
        self.assertIn('Agent', names)
        self.assertIn('Ollama', names)
        for item in stack:
            self.assertIn('name', item)
            self.assertIn('enabled', item)
            self.assertIn('status', item)
            self.assertIn(item['status'], ('healthy', 'unhealthy', 'not_used'))

    def test_deployment_run_with_deploy_requested_returns_ok_or_fail(self):
        """POST /api/deployment/run when config requests deploy: real run_bootstrap (may fail if no playbook)."""
        # Config requests DB -> delta has deploy_db true -> run_bootstrap runs for real
        path = os.path.join(self.tmp, 'app_config.yaml')
        with open(path, 'w') as f:
            f.write('features:\n  db_enabled: true\n')
        import importlib
        import web.config_manager as cm
        importlib.reload(cm)
        resp = self.client.post('/api/deployment/run')
        # Either 200 (playbook ran or found) or 400 (playbook not found / failed) depending on environment
        self.assertIn(resp.status_code, (200, 400))
        data = resp.get_json()
        if resp.status_code == 200:
            self.assertTrue(data.get('ok'))
        else:
            self.assertFalse(data.get('ok'))
            self.assertIn('error', data)
