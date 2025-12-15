"""
Unit tests for Worker Job Executor (Feature 8).

Tests the job execution and polling components.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.executor import JobExecutor, JobPoller, JobResult
from worker.api_client import APIResponse


class TestJobExecutor(unittest.TestCase):
    """Test JobExecutor class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.content_dir = os.path.join(self.test_dir, 'content')
        self.logs_dir = os.path.join(self.test_dir, 'logs')

        os.makedirs(self.content_dir)
        os.makedirs(self.logs_dir)
        os.makedirs(os.path.join(self.content_dir, 'playbooks'))
        os.makedirs(os.path.join(self.content_dir, 'inventory'))

        # Create mock API client
        self.api = Mock()
        self.api.start_job.return_value = APIResponse(success=True, status_code=200)
        self.api.complete_job.return_value = APIResponse(success=True, status_code=200)

        self.executor = JobExecutor(
            api_client=self.api,
            worker_id='test-worker-id',
            content_dir=self.content_dir,
            logs_dir=self.logs_dir
        )

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_executor_initialization(self):
        """Test executor initializes correctly."""
        self.assertEqual(self.executor.worker_id, 'test-worker-id')
        self.assertEqual(self.executor.content_dir, self.content_dir)
        self.assertEqual(self.executor.logs_dir, self.logs_dir)
        self.assertEqual(self.executor.active_job_count, 0)

    def test_generate_log_filename(self):
        """Test log filename generation."""
        filename = self.executor._generate_log_filename('job-123', 'test.yml')

        self.assertIn('test', filename)
        self.assertIn('job-123', filename)
        self.assertTrue(filename.endswith('.log'))

    def test_resolve_playbook_path_with_yml_extension(self):
        """Test path resolution when playbook already has .yml extension."""
        # Create test playbook
        playbook_path = os.path.join(self.content_dir, 'playbooks', 'test.yml')
        with open(playbook_path, 'w') as f:
            f.write('---\n')

        resolved = self.executor._resolve_playbook_path('test.yml')
        self.assertEqual(resolved, playbook_path)

    def test_resolve_playbook_path_with_yaml_extension(self):
        """Test path resolution when playbook has .yaml extension."""
        playbook_path = os.path.join(self.content_dir, 'playbooks', 'deploy.yaml')
        with open(playbook_path, 'w') as f:
            f.write('---\n')

        resolved = self.executor._resolve_playbook_path('deploy.yaml')
        self.assertEqual(resolved, playbook_path)

    def test_resolve_playbook_path_without_extension_finds_yml(self):
        """Test path resolution adds .yml when file exists."""
        # This is the key fix - web UI sends 'service-status', not 'service-status.yml'
        playbook_path = os.path.join(self.content_dir, 'playbooks', 'service-status.yml')
        with open(playbook_path, 'w') as f:
            f.write('---\n')

        resolved = self.executor._resolve_playbook_path('service-status')
        self.assertEqual(resolved, playbook_path)

    def test_resolve_playbook_path_without_extension_finds_yaml(self):
        """Test path resolution adds .yaml when .yml doesn't exist."""
        playbook_path = os.path.join(self.content_dir, 'playbooks', 'backup.yaml')
        with open(playbook_path, 'w') as f:
            f.write('---\n')

        resolved = self.executor._resolve_playbook_path('backup')
        self.assertEqual(resolved, playbook_path)

    def test_resolve_playbook_path_prefers_yml_over_yaml(self):
        """Test that .yml is preferred when both extensions exist."""
        yml_path = os.path.join(self.content_dir, 'playbooks', 'common.yml')
        yaml_path = os.path.join(self.content_dir, 'playbooks', 'common.yaml')
        with open(yml_path, 'w') as f:
            f.write('---\n# yml version\n')
        with open(yaml_path, 'w') as f:
            f.write('---\n# yaml version\n')

        resolved = self.executor._resolve_playbook_path('common')
        self.assertEqual(resolved, yml_path)

    def test_resolve_playbook_path_fallback_when_not_found(self):
        """Test path resolution falls back to original name when file not found."""
        # This allows ansible-playbook to provide its own error message
        resolved = self.executor._resolve_playbook_path('nonexistent')
        expected = os.path.join(self.content_dir, 'playbooks', 'nonexistent')
        self.assertEqual(resolved, expected)

    def test_build_ansible_command_basic(self):
        """Test building basic ansible command."""
        # Create playbook file so path resolution works
        playbook_path = os.path.join(self.content_dir, 'playbooks', 'test.yml')
        with open(playbook_path, 'w') as f:
            f.write('---\n')

        job = {
            'playbook': 'test.yml',
            'target': 'webservers'
        }

        cmd = self.executor._build_ansible_command(job)

        self.assertIn('ansible-playbook', cmd)
        self.assertIn(os.path.join(self.content_dir, 'playbooks', 'test.yml'), cmd)
        self.assertIn('-l', cmd)
        self.assertIn('webservers', cmd)

    def test_build_ansible_command_resolves_extension(self):
        """Test that command building resolves playbook extension."""
        # Create playbook with .yml extension
        playbook_path = os.path.join(self.content_dir, 'playbooks', 'hardware-inventory.yml')
        with open(playbook_path, 'w') as f:
            f.write('---\n')

        # Job has playbook name WITHOUT extension (as sent by web UI)
        job = {
            'playbook': 'hardware-inventory',
            'target': 'all'
        }

        cmd = self.executor._build_ansible_command(job)

        # Should resolve to the full path with .yml
        self.assertIn(playbook_path, cmd)

    def test_build_ansible_command_with_extra_vars(self):
        """Test building command with extra vars."""
        # Create playbook file so path resolution works
        playbook_path = os.path.join(self.content_dir, 'playbooks', 'deploy.yml')
        with open(playbook_path, 'w') as f:
            f.write('---\n')

        job = {
            'playbook': 'deploy.yml',
            'target': 'all',
            'extra_vars': {'version': '2.0', 'env': 'prod'}
        }

        cmd = self.executor._build_ansible_command(job)

        self.assertIn('-e', cmd)
        # Extra vars should be JSON
        import json
        extra_vars_idx = cmd.index('-e') + 1
        extra_vars_json = cmd[extra_vars_idx]
        parsed = json.loads(extra_vars_json)
        self.assertEqual(parsed['version'], '2.0')

    def test_active_jobs_tracking(self):
        """Test active jobs are tracked correctly."""
        self.assertEqual(self.executor.active_job_count, 0)
        self.assertEqual(self.executor.active_jobs, [])

        # Simulate adding active job
        self.executor._active_jobs['job-1'] = {
            'status': 'running',
            'started_at': datetime.now().isoformat()
        }

        self.assertEqual(self.executor.active_job_count, 1)
        self.assertEqual(len(self.executor.active_jobs), 1)

    def test_on_complete_callback(self):
        """Test completion callback registration."""
        callback_called = []

        def my_callback(result):
            callback_called.append(result)

        self.executor.on_complete(my_callback)
        self.assertEqual(len(self.executor._on_complete_callbacks), 1)


class TestJobExecutorExecution(unittest.TestCase):
    """Test job execution scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.content_dir = os.path.join(self.test_dir, 'content')
        self.logs_dir = os.path.join(self.test_dir, 'logs')

        os.makedirs(self.content_dir)
        os.makedirs(self.logs_dir)
        os.makedirs(os.path.join(self.content_dir, 'playbooks'))
        os.makedirs(os.path.join(self.content_dir, 'inventory'))

        self.api = Mock()
        self.api.start_job.return_value = APIResponse(success=True, status_code=200)
        self.api.complete_job.return_value = APIResponse(success=True, status_code=200)

        self.executor = JobExecutor(
            api_client=self.api,
            worker_id='test-worker',
            content_dir=self.content_dir,
            logs_dir=self.logs_dir
        )

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch('subprocess.Popen')
    def test_execute_playbook_success(self, mock_popen):
        """Test successful playbook execution."""
        # Mock successful process
        mock_process = Mock()
        mock_process.stdout = iter([b'PLAY [test]\n', b'ok: [host1]\n'])
        mock_process.returncode = 0
        mock_process.wait.return_value = None
        mock_popen.return_value = mock_process

        # Create test playbook
        playbook_path = os.path.join(self.content_dir, 'playbooks', 'test.yml')
        with open(playbook_path, 'w') as f:
            f.write('---\n- name: Test\n  hosts: all\n')

        job = {'id': 'job-1', 'playbook': 'test.yml', 'target': 'all'}
        log_path = os.path.join(self.logs_dir, 'test.log')

        exit_code, error = self.executor._execute_playbook(job, log_path)

        self.assertEqual(exit_code, 0)
        self.assertIsNone(error)
        self.assertTrue(os.path.exists(log_path))

    @patch('subprocess.Popen')
    def test_execute_playbook_failure(self, mock_popen):
        """Test failed playbook execution."""
        mock_process = Mock()
        mock_process.stdout = iter([b'PLAY [test]\n', b'fatal: [host1]\n'])
        mock_process.returncode = 2
        mock_process.wait.return_value = None
        mock_popen.return_value = mock_process

        job = {'id': 'job-1', 'playbook': 'test.yml', 'target': 'all'}
        log_path = os.path.join(self.logs_dir, 'test.log')

        exit_code, error = self.executor._execute_playbook(job, log_path)

        self.assertEqual(exit_code, 2)

    def test_execute_playbook_command_not_found(self):
        """Test handling of missing ansible-playbook."""
        with patch('subprocess.Popen', side_effect=FileNotFoundError()):
            job = {'id': 'job-1', 'playbook': 'test.yml', 'target': 'all'}
            log_path = os.path.join(self.logs_dir, 'test.log')

            exit_code, error = self.executor._execute_playbook(job, log_path)

            self.assertEqual(exit_code, 127)
            self.assertIn('not found', error)


class TestJobPoller(unittest.TestCase):
    """Test JobPoller class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()

        self.api = Mock()
        self.executor = Mock()
        self.executor.active_job_count = 0
        self.executor.execute_job = Mock()

        self.poller = JobPoller(
            api_client=self.api,
            worker_id='test-worker',
            executor=self.executor,
            max_concurrent=2
        )

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_poller_initialization(self):
        """Test poller initializes correctly."""
        self.assertEqual(self.poller.worker_id, 'test-worker')
        self.assertEqual(self.poller.max_concurrent, 2)

    def test_poll_once_no_jobs(self):
        """Test polling when no jobs assigned."""
        self.api.get_assigned_jobs.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'jobs': []}
        )

        started = self.poller.poll_once()

        self.assertEqual(len(started), 0)
        self.executor.execute_job.assert_not_called()

    def test_poll_once_with_jobs(self):
        """Test polling with assigned jobs."""
        self.api.get_assigned_jobs.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'jobs': [
                {'id': 'job-1', 'playbook': 'test.yml'},
                {'id': 'job-2', 'playbook': 'deploy.yml'}
            ]}
        )

        started = self.poller.poll_once()

        self.assertEqual(len(started), 2)
        self.assertEqual(self.executor.execute_job.call_count, 2)

    def test_poll_once_respects_capacity(self):
        """Test that polling respects max concurrent jobs."""
        self.executor.active_job_count = 1  # Already running 1

        self.api.get_assigned_jobs.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'jobs': [
                {'id': 'job-1', 'playbook': 'test.yml'},
                {'id': 'job-2', 'playbook': 'deploy.yml'},
                {'id': 'job-3', 'playbook': 'backup.yml'}
            ]}
        )

        started = self.poller.poll_once()

        # Should only start 1 more (max_concurrent=2, already running 1)
        self.assertEqual(len(started), 1)

    def test_poll_once_at_capacity(self):
        """Test that polling does nothing when at capacity."""
        self.executor.active_job_count = 2  # At capacity

        started = self.poller.poll_once()

        self.assertEqual(len(started), 0)
        self.api.get_assigned_jobs.assert_not_called()

    def test_poll_once_skips_processed_jobs(self):
        """Test that already processed jobs are skipped."""
        self.api.get_assigned_jobs.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'jobs': [{'id': 'job-1', 'playbook': 'test.yml'}]}
        )

        # First poll
        self.poller.poll_once()
        self.assertEqual(self.executor.execute_job.call_count, 1)

        # Second poll with same job
        self.poller.poll_once()
        # Should still be 1 (not called again)
        self.assertEqual(self.executor.execute_job.call_count, 1)

    def test_poll_once_api_failure(self):
        """Test handling of API failure during poll."""
        self.api.get_assigned_jobs.return_value = APIResponse(
            success=False,
            status_code=500,
            error='Server error'
        )

        started = self.poller.poll_once()

        self.assertEqual(len(started), 0)


class TestJobResult(unittest.TestCase):
    """Test JobResult dataclass."""

    def test_success_result(self):
        """Test successful job result."""
        result = JobResult(
            job_id='job-1',
            success=True,
            exit_code=0,
            log_file='test.log',
            started_at='2024-01-01T10:00:00',
            completed_at='2024-01-01T10:05:00'
        )

        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertIsNone(result.error_message)

    def test_failure_result(self):
        """Test failed job result."""
        result = JobResult(
            job_id='job-1',
            success=False,
            exit_code=2,
            log_file='test.log',
            error_message='Task failed'
        )

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.error_message, 'Task failed')


class TestAPIClientJobMethods(unittest.TestCase):
    """Test API client job-related methods."""

    def setUp(self):
        """Set up test fixtures."""
        from worker.api_client import PrimaryAPIClient
        self.client = PrimaryAPIClient('http://localhost:3001')

    @patch('worker.api_client.requests.request')
    def test_start_job(self, mock_request):
        """Test start_job API call."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'running'}
        mock_request.return_value = mock_response

        result = self.client.start_job('job-1', 'worker-1', 'test.log')

        self.assertTrue(result.success)
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        self.assertEqual(call_args[0][0], 'POST')
        self.assertIn('job-1', call_args[0][1])

    @patch('worker.api_client.requests.request')
    def test_complete_job(self, mock_request):
        """Test complete_job API call."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'completed'}
        mock_request.return_value = mock_response

        result = self.client.complete_job(
            'job-1', 'worker-1', exit_code=0, log_file='test.log'
        )

        self.assertTrue(result.success)
        call_args = mock_request.call_args
        json_data = call_args[1]['json']
        self.assertEqual(json_data['worker_id'], 'worker-1')
        self.assertEqual(json_data['exit_code'], 0)

    @patch('worker.api_client.requests.request')
    def test_get_assigned_jobs(self, mock_request):
        """Test get_assigned_jobs API call."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'jobs': [{'id': 'job-1', 'playbook': 'test.yml'}]
        }
        mock_request.return_value = mock_response

        result = self.client.get_assigned_jobs('worker-1')

        self.assertTrue(result.success)
        self.assertIn('jobs', result.data)


if __name__ == '__main__':
    unittest.main()
