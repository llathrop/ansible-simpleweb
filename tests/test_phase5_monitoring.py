import unittest
import json
import os
from unittest.mock import MagicMock, patch, mock_open

# Set env vars for testing before imports
os.environ['DATA_DIR'] = '/tmp/agent_data'
os.environ['LOGS_DIR'] = '/tmp/agent_logs'
os.environ['PLAYBOOKS_DIR'] = '/tmp/agent_playbooks'
os.environ['DOCS_DIR'] = '/tmp/agent_docs'

from agent.service import app, llm_client

class TestPhase5Monitoring(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        
    @patch('requests.get')
    def test_schedule_monitor_success(self, mock_get):
        """Test that schedule monitor correctly fetches and processes schedules."""
        # Mock successful response from ansible-web
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {'id': '1', 'name': 'Daily Backup', 'last_run': '2023-10-27 10:00:00', 'status': 'success'},
            {'id': '2', 'name': 'Weekly Update', 'last_run': None} # Never ran
        ]
        mock_get.return_value = mock_response
        
        response = self.app.post('/agent/schedule-monitor')
        
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['status'], 'monitored')
        self.assertEqual(data['schedules_checked'], 2)

    @patch('requests.get')
    def test_schedule_monitor_failure(self, mock_get):
        """Test handling of upstream API failure."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response
        
        response = self.app.post('/agent/schedule-monitor')
        
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertIn('error', data)

    @patch.object(llm_client, 'analyze_config')
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    def test_analyze_config_success(self, mock_makedirs, mock_file, mock_analyze):
        """Test config analysis endpoint."""
        mock_analyze.return_value = {
            "device_type": "routeros",
            "security_score": 85,
            "critical_risks": []
        }
        
        payload = {'content': 'user=admin password=admin'}
        response = self.app.post('/agent/analyze-config', json=payload)
        
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['status'], 'analyzed')
        self.assertIn('report_id', data)
        self.assertEqual(data['result']['security_score'], 85)
        
        # Verify file write
        mock_file.assert_called()
        
    def test_analyze_config_missing_content(self):
        """Test error when content is missing."""
        response = self.app.post('/agent/analyze-config', json={})
        self.assertEqual(response.status_code, 400)

    def test_analyze_config_too_large(self):
        """Test error when config is too large."""
        large_content = "a" * 100001
        response = self.app.post('/agent/analyze-config', json={'content': large_content})
        self.assertEqual(response.status_code, 400)
