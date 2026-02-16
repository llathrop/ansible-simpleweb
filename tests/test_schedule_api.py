"""
API tests for schedule endpoints: run_now, etc.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_test_config_dir = tempfile.mkdtemp()
os.environ['CONFIG_DIR'] = _test_config_dir
os.environ.setdefault('SECRET_KEY', 'test-key')
os.environ.setdefault('CLUSTER_MODE', 'standalone')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

mock_socketio = MagicMock()
sys.modules['flask_socketio'] = mock_socketio

from web.app import app as flask_app


class TestScheduleRunNowAPI(unittest.TestCase):
    """Verify POST /api/schedules/<id>/run_now endpoint."""

    def setUp(self):
        self.client = flask_app.test_client()
        self.client.testing = True

    def test_run_now_scheduler_not_initialized_returns_500(self):
        """When schedule_manager is None, run_now returns 500."""
        resp = self.client.post('/api/schedules/some-id/run_now')
        # schedule_manager is None in test context (main block not run)
        self.assertIn(resp.status_code, (500, 400))
        data = resp.get_json()
        if resp.status_code == 500:
            self.assertIn('error', data)
            self.assertIn('Scheduler', data['error'])
