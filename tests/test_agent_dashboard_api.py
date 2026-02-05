"""
Phase 7.2: Agent API & Dashboard Repair

Tests for agent dashboard API endpoints. Verifies response formats,
error handling when agent is unreachable, and timeout behavior.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock flask_socketio before importing web.app
mock_socketio = MagicMock()
sys.modules['flask_socketio'] = mock_socketio

os.environ.setdefault('SECRET_KEY', 'test-key')
os.environ.setdefault('CLUSTER_MODE', 'standalone')
os.environ.setdefault('AGENT_SERVICE_URL', 'http://mock-agent:5000')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import app as flask_app


class TestAgentDashboardAPI(unittest.TestCase):
    """Verify agent dashboard API response formats and error handling."""

    def setUp(self):
        self.client = flask_app.test_client()
        self.client.testing = True

    @patch('web.app.requests.get')
    def test_overview_success_returns_status_and_model(self, mock_get):
        """Overview returns status and model when agent is online."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': 'online',
            'model': 'llama3.2:3b',
        }

        resp = self.client.get('/api/agent/overview')

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'online')
        self.assertEqual(data['model'], 'llama3.2:3b')

    @patch('web.app.requests.get')
    def test_overview_agent_unreachable_returns_503(self, mock_get):
        """Overview returns 503 with status=offline when agent unreachable."""
        mock_get.side_effect = Exception('Connection refused')

        resp = self.client.get('/api/agent/overview')

        self.assertEqual(resp.status_code, 503)
        data = resp.get_json()
        self.assertIn('status', data)
        self.assertIn('error', data)
        self.assertEqual(data['status'], 'offline')

    @patch('web.app.requests.get')
    def test_reviews_success_returns_array(self, mock_get):
        """Reviews returns array when agent responds."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = []

        resp = self.client.get('/api/agent/reviews')

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)

    @patch('web.app.requests.get')
    def test_reviews_agent_unreachable_returns_500(self, mock_get):
        """Reviews returns 500 when agent unreachable."""
        mock_get.side_effect = Exception('Connection refused')

        resp = self.client.get('/api/agent/reviews')

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn('error', data)

    @patch('web.app.requests.get')
    def test_proposals_success_returns_array(self, mock_get):
        """Proposals returns array when agent responds."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = []

        resp = self.client.get('/api/agent/proposals')

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)

    @patch('web.app.requests.get')
    def test_proposals_agent_unreachable_returns_500(self, mock_get):
        """Proposals returns 500 when agent unreachable."""
        mock_get.side_effect = Exception('Connection refused')

        resp = self.client.get('/api/agent/proposals')

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn('error', data)

    @patch('web.app.requests.get')
    def test_reports_success_returns_array(self, mock_get):
        """Reports returns array when agent responds."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = []

        resp = self.client.get('/api/agent/reports')

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)

    @patch('web.app.requests.get')
    def test_reports_agent_unreachable_returns_500(self, mock_get):
        """Reports returns 500 when agent unreachable."""
        mock_get.side_effect = Exception('Connection refused')

        resp = self.client.get('/api/agent/reports')

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertIn('error', data)

    def test_agent_dashboard_renders(self):
        """Agent dashboard page renders without error."""
        resp = self.client.get('/agent')

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Agent Dashboard', resp.data)
        self.assertIn(b'loadDashboard', resp.data)


if __name__ == '__main__':
    unittest.main()
