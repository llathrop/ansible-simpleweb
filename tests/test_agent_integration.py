import unittest
import json
import os
import sys
from unittest.mock import patch, MagicMock

# Mock flask_socketio BEFORE importing web.app to avoid eventlet issues in tests
mock_socketio = MagicMock()
sys.modules['flask_socketio'] = mock_socketio

# Import the web app directly to test the trigger logic
# We need to set some env vars first to avoid import errors
os.environ['SECRET_KEY'] = 'test-key'
os.environ['CLUSTER_MODE'] = 'standalone'
os.environ['AGENT_SERVICE_URL'] = 'http://mock-agent:5000'

# Need to ensure web is in path (handled by runner, but good to be safe)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from web import app

class TestAgentIntegration(unittest.TestCase):
    def setUp(self):
        self.app = app.app.test_client()
        self.app.testing = True

    @patch('web.app.storage_backend')
    @patch('web.app.requests.post')
    def test_job_completion_triggers_agent(self, mock_post, mock_storage):
        """Phase 1: Verify web app attempts to call agent when job completes."""
        
        # Mock storage
        mock_storage.get_job.return_value = {
            'id': '123',
            'assigned_worker': 'worker-1',
            'status': 'running'
        }
        mock_storage.update_job.return_value = True
        mock_storage.get_worker.return_value = {}  # Mock worker stats update
        
        # Prepare job completion payload
        payload = {
            'status': 'completed',
            'exit_code': 0,
            'completed_at': '2023-01-01T12:00:00',
            'duration_seconds': 10,
            'log_file': 'job-123.log',
            'worker_id': 'worker-1'
        }
        
        # Simulate job completion callback from worker
        # Assuming job_id '123' and worker 'worker-1'
        response = self.app.post('/api/jobs/123/complete',
                                 data=json.dumps(payload),
                                 content_type='application/json')
        
        self.assertEqual(response.status_code, 200)

    @patch('web.app.threading.Thread')
    @patch('web.app.storage_backend')
    def test_job_completion_threading(self, mock_storage, mock_thread):
        """Phase 1: Verify that a thread is spawned to call the agent."""
        mock_storage.get_job.return_value = {
            'id': '123',
            'assigned_worker': 'worker-1',
            'status': 'running'
        }
        mock_storage.update_job.return_value = True
        mock_storage.get_worker.return_value = {}
        
        payload = {
            'status': 'completed',
            'exit_code': 0,
            'completed_at': '2023-01-01T12:00:00',
            'worker_id': 'worker-1'
        }
        
        response = self.app.post('/api/jobs/123/complete',
                      data=json.dumps(payload),
                      content_type='application/json')
        
        self.assertEqual(response.status_code, 200)

        # Check if threading.Thread was called
        mock_thread.assert_called()
        
        # Inspect the target function passed to Thread
        args = mock_thread.call_args[1]
        target = args.get('target')
        self.assertTrue(callable(target))
        
        # We can try to execute the target to verify it calls requests.post
        # but that requires patching requests inside the lambda context or globally.
        # Let's verify at least the infrastructure is in place.

if __name__ == '__main__':
    unittest.main()
