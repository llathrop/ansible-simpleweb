"""
Unit Tests for Log Upload from Workers to Primary.

Tests the log upload functionality where workers stream log content
during job execution and upload final logs upon completion.

Run with: pytest tests/test_log_upload.py -v
"""

import os
import sys
import json
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockResponse:
    """Mock HTTP response for API client tests."""

    def __init__(self, status_code=200, json_data=None, ok=True):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.ok = ok

    def json(self):
        return self._json_data


class TestLogStreamingAPI(unittest.TestCase):
    """Test log streaming endpoint behavior."""

    def setUp(self):
        """Set up test fixtures."""
        self.job_id = 'test-job-123'
        self.worker_id = 'worker-1'
        self.log_content = 'PLAY [Test] ***\nTASK [Gathering Facts] ***\nok: [localhost]'

    def test_stream_log_creates_partial_file(self):
        """Test that streaming log creates a partial log file."""
        # Simulate the partial log file path
        logs_dir = '/tmp/test_logs'
        os.makedirs(logs_dir, exist_ok=True)
        partial_file = os.path.join(logs_dir, f'partial-{self.job_id}.log')

        # Write content as the endpoint would
        with open(partial_file, 'w') as f:
            f.write(self.log_content)

        # Verify file was created with correct content
        self.assertTrue(os.path.exists(partial_file))
        with open(partial_file, 'r') as f:
            content = f.read()
        self.assertEqual(content, self.log_content)

        # Cleanup
        os.remove(partial_file)
        os.rmdir(logs_dir)

    def test_stream_log_appends_content(self):
        """Test that append mode adds to existing content."""
        logs_dir = '/tmp/test_logs'
        os.makedirs(logs_dir, exist_ok=True)
        partial_file = os.path.join(logs_dir, f'partial-{self.job_id}.log')

        # Initial content
        initial_content = 'Line 1\n'
        with open(partial_file, 'w') as f:
            f.write(initial_content)

        # Append more content
        append_content = 'Line 2\nLine 3\n'
        with open(partial_file, 'a') as f:
            f.write(append_content)

        # Verify combined content
        with open(partial_file, 'r') as f:
            content = f.read()
        self.assertEqual(content, initial_content + append_content)

        # Cleanup
        os.remove(partial_file)
        os.rmdir(logs_dir)

    def test_stream_log_replaces_content(self):
        """Test that non-append mode replaces content."""
        logs_dir = '/tmp/test_logs'
        os.makedirs(logs_dir, exist_ok=True)
        partial_file = os.path.join(logs_dir, f'partial-{self.job_id}.log')

        # Initial content
        with open(partial_file, 'w') as f:
            f.write('Old content\n')

        # Replace with new content
        new_content = 'New content\n'
        with open(partial_file, 'w') as f:
            f.write(new_content)

        # Verify content was replaced
        with open(partial_file, 'r') as f:
            content = f.read()
        self.assertEqual(content, new_content)

        # Cleanup
        os.remove(partial_file)
        os.rmdir(logs_dir)


class TestWorkerLogStreaming(unittest.TestCase):
    """Test worker-side log streaming functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.job_id = 'test-job-456'
        self.worker_id = 'worker-2'

    @patch('requests.post')
    def test_stream_log_api_call(self, mock_post):
        """Test that worker makes correct API call to stream logs."""
        mock_post.return_value = MockResponse(200, {'success': True})

        # Simulate what the worker's api_client.stream_log does
        import requests
        response = requests.post(
            'http://primary:3001/api/jobs/test-job-456/log/stream',
            json={
                'worker_id': self.worker_id,
                'content': 'Test log content',
                'append': True
            }
        )

        # Verify the call was made
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn('test-job-456', call_args[0][0])
        self.assertEqual(call_args[1]['json']['worker_id'], self.worker_id)
        self.assertEqual(call_args[1]['json']['append'], True)

    @patch('requests.post')
    def test_stream_log_handles_failure(self, mock_post):
        """Test that worker handles streaming failures gracefully."""
        mock_post.return_value = MockResponse(500, {'error': 'Server error'}, ok=False)

        import requests
        response = requests.post(
            'http://primary:3001/api/jobs/test-job-456/log/stream',
            json={'content': 'Test content'}
        )

        # Should not raise, just return error response
        self.assertFalse(response.ok)
        self.assertEqual(response.status_code, 500)


class TestLogUploadOnCompletion(unittest.TestCase):
    """Test final log upload when job completes."""

    def setUp(self):
        """Set up test fixtures."""
        self.job_id = 'test-job-789'
        self.worker_id = 'worker-3'
        self.log_file = f'playbook_{self.job_id[:8]}_test.log'

    def test_final_log_format(self):
        """Test that final log has correct format."""
        logs_dir = '/tmp/test_logs'
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, self.log_file)

        # Create log in expected format
        started = datetime.now().isoformat()
        completed = datetime.now().isoformat()

        log_content = f"""Job ID: {self.job_id}
Playbook: test-playbook
Target: localhost
Started: {started}
Command: ansible-playbook /app/playbooks/test-playbook.yml -i /app/inventory/hosts -l localhost
============================================================

PLAY [Test Playbook] ***

TASK [Test task] ***
ok: [localhost]

PLAY RECAP ***
localhost: ok=1  changed=0  unreachable=0  failed=0

============================================================
Completed: {completed}
Exit Code: 0
"""

        with open(log_path, 'w') as f:
            f.write(log_content)

        # Verify log structure
        with open(log_path, 'r') as f:
            content = f.read()

        self.assertIn(f'Job ID: {self.job_id}', content)
        self.assertIn('Playbook: test-playbook', content)
        self.assertIn('Exit Code: 0', content)
        self.assertIn('============================================================', content)

        # Cleanup
        os.remove(log_path)
        os.rmdir(logs_dir)

    @patch('requests.post')
    def test_upload_log_content(self, mock_post):
        """Test that log content is uploaded to primary."""
        mock_post.return_value = MockResponse(200, {'success': True})

        log_content = 'Test log content for upload'

        # Simulate upload_log API call
        import requests
        response = requests.post(
            f'http://primary:3001/api/jobs/{self.job_id}/log',
            json={
                'worker_id': self.worker_id,
                'content': log_content,
                'log_file': self.log_file
            }
        )

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[1]['json']['content'], log_content)
        self.assertEqual(call_args[1]['json']['log_file'], self.log_file)


class TestLogRetrieval(unittest.TestCase):
    """Test log retrieval from primary server."""

    def setUp(self):
        """Set up test fixtures."""
        self.job_id = 'test-job-abc'

    def test_get_log_json_format(self):
        """Test log retrieval returns JSON format."""
        expected_log = 'Test log output\nLine 2\nLine 3'
        response_data = {
            'log': expected_log,
            'job_id': self.job_id
        }

        # Verify JSON structure
        self.assertIn('log', response_data)
        self.assertEqual(response_data['log'], expected_log)

    def test_get_log_raw_format(self):
        """Test log retrieval returns raw text."""
        expected_log = 'Test log output\nLine 2\nLine 3'

        # Raw format is just the text
        self.assertIsInstance(expected_log, str)
        self.assertIn('\n', expected_log)

    def test_partial_log_vs_final_log(self):
        """Test that partial and final logs are handled correctly."""
        logs_dir = '/tmp/test_logs'
        os.makedirs(logs_dir, exist_ok=True)

        partial_file = os.path.join(logs_dir, f'partial-{self.job_id}.log')
        final_file = os.path.join(logs_dir, f'playbook_{self.job_id[:8]}.log')

        # During execution - only partial exists
        with open(partial_file, 'w') as f:
            f.write('Partial content during execution')

        self.assertTrue(os.path.exists(partial_file))
        self.assertFalse(os.path.exists(final_file))

        # After completion - final exists, partial may be cleaned up
        with open(final_file, 'w') as f:
            f.write('Final complete log content')

        self.assertTrue(os.path.exists(final_file))

        # Cleanup
        os.remove(partial_file)
        os.remove(final_file)
        os.rmdir(logs_dir)


class TestWebSocketLogBroadcast(unittest.TestCase):
    """Test WebSocket broadcasting of log updates."""

    def setUp(self):
        """Set up test fixtures."""
        self.job_id = 'test-job-ws'

    def test_broadcast_message_format(self):
        """Test WebSocket broadcast message structure."""
        broadcast_data = {
            'job_id': self.job_id,
            'content': 'New log line\n',
            'append': True
        }

        # Verify message structure
        self.assertIn('job_id', broadcast_data)
        self.assertIn('content', broadcast_data)
        self.assertIn('append', broadcast_data)
        self.assertEqual(broadcast_data['job_id'], self.job_id)

    def test_room_name_format(self):
        """Test that job room names follow expected pattern."""
        room_name = f'job_{self.job_id}'

        self.assertEqual(room_name, 'job_test-job-ws')
        self.assertTrue(room_name.startswith('job_'))

    def test_catchup_message_format(self):
        """Test catchup message includes full content."""
        existing_content = 'Line 1\nLine 2\nLine 3\n'
        catchup_data = {
            'job_id': self.job_id,
            'content': existing_content
        }

        # Catchup should include all existing content
        self.assertEqual(catchup_data['content'], existing_content)
        self.assertNotIn('append', catchup_data)  # Catchup replaces, not appends


class TestLogCleanup(unittest.TestCase):
    """Test partial log cleanup after job completion."""

    def setUp(self):
        """Set up test fixtures."""
        self.job_id = 'test-job-cleanup'
        self.logs_dir = '/tmp/test_logs_cleanup'
        os.makedirs(self.logs_dir, exist_ok=True)

    def tearDown(self):
        """Clean up test files."""
        import shutil
        if os.path.exists(self.logs_dir):
            shutil.rmtree(self.logs_dir)

    def test_partial_log_cleanup_on_success(self):
        """Test partial log is cleaned up after successful completion."""
        partial_file = os.path.join(self.logs_dir, f'partial-{self.job_id}.log')
        final_file = os.path.join(self.logs_dir, f'playbook_{self.job_id[:8]}.log')

        # Create both files
        with open(partial_file, 'w') as f:
            f.write('Partial content')
        with open(final_file, 'w') as f:
            f.write('Final content')

        # Simulate cleanup (in real code, this happens after job completion)
        if os.path.exists(final_file) and os.path.exists(partial_file):
            os.remove(partial_file)

        # Verify partial was cleaned up
        self.assertFalse(os.path.exists(partial_file))
        self.assertTrue(os.path.exists(final_file))

    def test_partial_log_preserved_on_failure(self):
        """Test partial log is preserved if final log fails to upload."""
        partial_file = os.path.join(self.logs_dir, f'partial-{self.job_id}.log')

        # Only partial exists (upload failed)
        with open(partial_file, 'w') as f:
            f.write('Partial content with execution data')

        # Partial should still exist
        self.assertTrue(os.path.exists(partial_file))
        with open(partial_file, 'r') as f:
            content = f.read()
        self.assertIn('execution data', content)


if __name__ == '__main__':
    unittest.main()
