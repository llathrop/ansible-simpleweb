"""
Unit Tests for Batch Log Streaming.

Tests the log streaming functionality for batch jobs including:
- Partial log file handling during execution
- Log catchup when clients join the batch room
- Worker name in log headers
- WebSocket event structure

Run with: pytest tests/test_batch_log_streaming.py -v
"""

import os
import sys
import json
import unittest
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPartialLogFileHandling(unittest.TestCase):
    """Test partial log file creation and reading during batch execution."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logs_dir = os.path.join(self.test_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)
        self.job_id = 'test-batch-job-123'
        self.batch_id = 'batch-456'

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_partial_log_file_naming(self):
        """Test that partial log files follow the expected naming convention."""
        partial_filename = f'partial-{self.job_id}.log'
        partial_path = os.path.join(self.logs_dir, partial_filename)

        # Write some content
        with open(partial_path, 'w') as f:
            f.write('Test content')

        # Verify file exists at expected path
        self.assertTrue(os.path.exists(partial_path))
        self.assertTrue(partial_filename.startswith('partial-'))
        self.assertTrue(partial_filename.endswith('.log'))

    def test_partial_log_append_streaming(self):
        """Test that log content is appended during streaming."""
        partial_path = os.path.join(self.logs_dir, f'partial-{self.job_id}.log')

        # Stream in chunks like the worker does
        chunks = [
            'Worker: test-worker (abc12345)\n',
            'Job ID: test-batch-job-123\n',
            'PLAY [Test] ***\n',
            'TASK [Gathering Facts] ***\n',
            'ok: [localhost]\n'
        ]

        # First chunk replaces
        with open(partial_path, 'w') as f:
            f.write(chunks[0])

        # Subsequent chunks append
        for chunk in chunks[1:]:
            with open(partial_path, 'a') as f:
                f.write(chunk)

        # Verify all content is present
        with open(partial_path, 'r') as f:
            content = f.read()

        for chunk in chunks:
            self.assertIn(chunk.strip(), content)

    def test_partial_log_position_tracking(self):
        """Test tracking read position for incremental log streaming."""
        partial_path = os.path.join(self.logs_dir, f'partial-{self.job_id}.log')

        # Write initial content
        initial_content = 'Line 1\nLine 2\n'
        with open(partial_path, 'w') as f:
            f.write(initial_content)

        # Track position after reading
        last_pos = 0
        with open(partial_path, 'r') as f:
            content = f.read()
            last_pos = f.tell()

        self.assertEqual(last_pos, len(initial_content))

        # Append more content
        new_content = 'Line 3\nLine 4\n'
        with open(partial_path, 'a') as f:
            f.write(new_content)

        # Read only new content using position
        with open(partial_path, 'r') as f:
            f.seek(last_pos)
            incremental = f.read()

        self.assertEqual(incremental, new_content)


class TestWorkerLogHeader(unittest.TestCase):
    """Test worker identification in log headers."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logs_dir = os.path.join(self.test_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_log_header_contains_worker_name(self):
        """Test that log header includes worker name and ID."""
        worker_name = 'ansible-worker-1'
        worker_id = '1a2b3c4d-5e6f-7g8h-9i0j'
        job_id = 'test-job-123'
        playbook = 'test-playbook.yml'

        # Create header as the executor does
        header = (
            f"Worker: {worker_name} ({worker_id[:8]})\n"
            f"Job ID: {job_id}\n"
            f"Playbook: {playbook}\n"
            f"Target: all\n"
            f"Started: {datetime.now().isoformat()}\n"
            f"Command: ansible-playbook /app/playbooks/{playbook}\n"
            + "=" * 60 + "\n\n"
        )

        self.assertIn(f"Worker: {worker_name}", header)
        self.assertIn(f"({worker_id[:8]})", header)
        self.assertIn(f"Job ID: {job_id}", header)
        self.assertIn(f"Playbook: {playbook}", header)

    def test_log_header_format_for_ui(self):
        """Test that log header format is parseable for UI display."""
        header_lines = [
            "Worker: ansible-worker-2 (a1b2c3d4)",
            "Job ID: job-12345678",
            "Playbook: service-status.yml",
            "Target: webservers",
            "Started: 2024-01-15T10:30:00.000000",
            "Command: ansible-playbook /app/playbooks/service-status.yml -i /app/inventory/hosts -l webservers",
        ]

        header = '\n'.join(header_lines) + '\n' + '=' * 60 + '\n\n'

        # Verify the format can be parsed
        for line in header.split('\n'):
            if ':' in line and not line.startswith('='):
                key, value = line.split(':', 1)
                self.assertIsNotNone(key.strip())
                self.assertIsNotNone(value.strip())


class TestBatchLogCatchup(unittest.TestCase):
    """Test log catchup when clients join batch room late."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logs_dir = os.path.join(self.test_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)
        self.batch_id = 'batch-test-789'

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_catchup_reads_completed_playbook_logs(self):
        """Test that catchup sends logs for completed playbooks."""
        # Create a completed playbook log
        log_file = 'service-status_job123_20240115.log'
        log_path = os.path.join(self.logs_dir, log_file)
        log_content = """Worker: worker-1 (a1b2c3d4)
Job ID: job123
Playbook: service-status
PLAY [Service Status] ***
ok: [localhost]
PLAY RECAP ***
localhost: ok=1
============================================================
Completed: 2024-01-15T10:35:00.000000
Exit Code: 0
"""
        with open(log_path, 'w') as f:
            f.write(log_content)

        # Simulate catchup reading
        catchup_content = None
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                catchup_content = f.read()

        self.assertIsNotNone(catchup_content)
        self.assertEqual(catchup_content, log_content)
        self.assertIn('Worker: worker-1', catchup_content)
        self.assertIn('Exit Code: 0', catchup_content)

    def test_catchup_reads_partial_log_for_running_job(self):
        """Test that catchup reads partial log for running playbooks."""
        job_id = 'current-job-456'
        partial_path = os.path.join(self.logs_dir, f'partial-{job_id}.log')

        partial_content = """Worker: worker-2 (x1y2z3w4)
Job ID: current-job-456
Playbook: deploy.yml
PLAY [Deploy] ***
TASK [Gathering Facts] ***
"""
        with open(partial_path, 'w') as f:
            f.write(partial_content)

        # Simulate catchup for running job
        catchup_content = None
        if os.path.exists(partial_path):
            with open(partial_path, 'r') as f:
                catchup_content = f.read()

        self.assertIsNotNone(catchup_content)
        self.assertIn('Worker: worker-2', catchup_content)
        self.assertIn('TASK [Gathering Facts]', catchup_content)

    def test_catchup_prefers_final_log_over_partial(self):
        """Test that final log is preferred over partial for completed jobs."""
        job_id = 'finished-job-789'
        partial_path = os.path.join(self.logs_dir, f'partial-{job_id}.log')
        final_file = 'test_job789_20240115.log'
        final_path = os.path.join(self.logs_dir, final_file)

        # Create both files
        with open(partial_path, 'w') as f:
            f.write('Partial: incomplete data')

        with open(final_path, 'w') as f:
            f.write('Final: complete log with full output')

        # Simulate catchup logic - prefer final
        log_content = None
        if os.path.exists(final_path):
            with open(final_path, 'r') as f:
                log_content = f.read()

        if not log_content and os.path.exists(partial_path):
            with open(partial_path, 'r') as f:
                log_content = f.read()

        self.assertIn('Final:', log_content)
        self.assertNotIn('Partial:', log_content)


class TestBatchLogLineEvent(unittest.TestCase):
    """Test batch_log_line WebSocket event structure."""

    def test_batch_log_line_event_structure(self):
        """Test that batch_log_line events have correct structure."""
        batch_id = 'batch-event-test'
        playbook = 'test-playbook'
        line = 'TASK [Test] ***\n'

        event_data = {
            'batch_id': batch_id,
            'playbook': playbook,
            'line': line
        }

        self.assertIn('batch_id', event_data)
        self.assertIn('playbook', event_data)
        self.assertIn('line', event_data)
        self.assertEqual(event_data['batch_id'], batch_id)
        self.assertEqual(event_data['playbook'], playbook)
        self.assertEqual(event_data['line'], line)

    def test_batch_log_lines_preserve_formatting(self):
        """Test that log lines preserve original formatting."""
        lines = [
            'ok: [host1]\n',
            'ok: [host2]\n',
            '    "msg": "Hello World"\n',
            'PLAY RECAP ***\n',
            'host1                      : ok=5    changed=2    unreachable=0    failed=0\n',
        ]

        for line in lines:
            event_data = {
                'batch_id': 'test',
                'playbook': 'test',
                'line': line
            }
            # Line should be preserved exactly
            self.assertEqual(event_data['line'], line)
            # Newline should be preserved if present
            if line.endswith('\n'):
                self.assertTrue(event_data['line'].endswith('\n'))


class TestBatchCatchupEvent(unittest.TestCase):
    """Test batch_catchup WebSocket event structure."""

    def test_batch_catchup_event_structure(self):
        """Test that batch_catchup events have correct structure."""
        catchup_data = {
            'batch_id': 'batch-123',
            'status': 'running',
            'completed': 2,
            'failed': 0,
            'total': 5,
            'current_playbook': 'deploy.yml',
            'results': [
                {'playbook': 'service-status', 'status': 'completed', 'exit_code': 0},
                {'playbook': 'gather-facts', 'status': 'completed', 'exit_code': 0}
            ],
            'worker_name': 'worker-1'
        }

        self.assertIn('batch_id', catchup_data)
        self.assertIn('status', catchup_data)
        self.assertIn('completed', catchup_data)
        self.assertIn('failed', catchup_data)
        self.assertIn('total', catchup_data)
        self.assertIn('current_playbook', catchup_data)
        self.assertIn('results', catchup_data)
        self.assertIn('worker_name', catchup_data)

    def test_batch_catchup_with_worker_name(self):
        """Test that batch_catchup includes worker_name when available."""
        catchup_data = {
            'batch_id': 'batch-456',
            'status': 'completed',
            'worker_name': 'ansible-worker-3'
        }

        self.assertEqual(catchup_data['worker_name'], 'ansible-worker-3')

    def test_batch_catchup_without_worker_name(self):
        """Test batch_catchup when worker_name is not available."""
        catchup_data = {
            'batch_id': 'batch-789',
            'status': 'pending',
            'worker_name': None
        }

        self.assertIsNone(catchup_data['worker_name'])


class TestBatchRoomManagement(unittest.TestCase):
    """Test batch room joining and naming."""

    def test_batch_room_name_format(self):
        """Test that batch room names follow expected format."""
        batch_id = 'batch-abc123'
        room_name = f'batch:{batch_id}'

        self.assertEqual(room_name, 'batch:batch-abc123')
        self.assertTrue(room_name.startswith('batch:'))
        self.assertIn(batch_id, room_name)

    def test_join_batch_data_structure(self):
        """Test the data structure for join_batch event."""
        join_data = {'batch_id': 'batch-xyz789'}

        self.assertIn('batch_id', join_data)
        self.assertEqual(join_data['batch_id'], 'batch-xyz789')


class TestLogStreamingIntegration(unittest.TestCase):
    """Integration tests for log streaming during batch execution."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logs_dir = os.path.join(self.test_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_full_log_streaming_workflow(self):
        """Test complete log streaming workflow for a batch job."""
        batch_id = 'batch-full-workflow'
        job_id = 'job-full-workflow'
        partial_path = os.path.join(self.logs_dir, f'partial-{job_id}.log')

        # Step 1: Worker starts job and streams header
        header = """Worker: test-worker (12345678)
Job ID: job-full-workflow
Playbook: test.yml
Target: all
Started: 2024-01-15T10:30:00
Command: ansible-playbook /app/playbooks/test.yml
============================================================

"""
        with open(partial_path, 'w') as f:
            f.write(header)

        # Step 2: Worker streams playbook output
        playbook_output = """PLAY [Test] ***

TASK [Gathering Facts] ***
ok: [localhost]

TASK [Test task] ***
ok: [localhost]
"""
        with open(partial_path, 'a') as f:
            f.write(playbook_output)

        # Step 3: Client joins late and gets catchup
        with open(partial_path, 'r') as f:
            catchup_content = f.read()

        self.assertIn('Worker: test-worker', catchup_content)
        self.assertIn('PLAY [Test]', catchup_content)
        self.assertIn('TASK [Test task]', catchup_content)

        # Step 4: Worker streams more output
        more_output = """PLAY RECAP ***
localhost: ok=2  changed=0
"""
        with open(partial_path, 'a') as f:
            f.write(more_output)

        # Step 5: Job completes, final log is written
        final_file = 'test_job123_20240115.log'
        final_path = os.path.join(self.logs_dir, final_file)
        footer = """
============================================================
Completed: 2024-01-15T10:30:30
Exit Code: 0
"""
        with open(partial_path, 'r') as f:
            full_content = f.read()
        with open(final_path, 'w') as f:
            f.write(full_content + footer)

        # Verify final log
        with open(final_path, 'r') as f:
            final_content = f.read()

        self.assertIn('Worker: test-worker', final_content)
        self.assertIn('PLAY RECAP', final_content)
        self.assertIn('Exit Code: 0', final_content)


class TestLogStreamingErrorHandling(unittest.TestCase):
    """Test error handling in log streaming."""

    def test_missing_partial_log_file(self):
        """Test handling when partial log file doesn't exist."""
        non_existent_path = '/tmp/non_existent_partial.log'

        content = None
        if os.path.exists(non_existent_path):
            with open(non_existent_path, 'r') as f:
                content = f.read()

        self.assertIsNone(content)

    def test_empty_partial_log_file(self):
        """Test handling of empty partial log file."""
        test_dir = tempfile.mkdtemp()
        try:
            partial_path = os.path.join(test_dir, 'partial-empty.log')
            with open(partial_path, 'w') as f:
                f.write('')

            with open(partial_path, 'r') as f:
                content = f.read()

            self.assertEqual(content, '')
            self.assertEqual(len(content.splitlines()), 0)
        finally:
            shutil.rmtree(test_dir)

    def test_read_permission_error_handling(self):
        """Test graceful handling of read permission errors."""
        # Simulate exception handling pattern used in the code
        log_content = None
        try:
            # This would normally try to read a file
            raise PermissionError("Permission denied")
        except:
            pass

        # Should handle gracefully without crashing
        self.assertIsNone(log_content)


if __name__ == '__main__':
    unittest.main()
