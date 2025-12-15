"""
Unit tests for Job Completion & Results (Feature 10).

Tests the enhanced job completion functionality including:
- Status and exit code handling
- Log storage
- Worker statistics updates
- CMDB facts extraction
- Piggyback checkin processing
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.storage.flatfile import FlatFileStorage


class TestJobCompletionStorage(unittest.TestCase):
    """Test job completion storage operations."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

        # Create test worker
        self.worker = {
            'id': 'completion-worker',
            'name': 'Completion Test Worker',
            'tags': ['test'],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'stats': {
                'jobs_completed': 5,
                'jobs_failed': 1,
                'avg_job_duration': 60.0
            }
        }
        self.storage.save_worker(self.worker)

        # Create test job
        self.job = {
            'id': 'completion-job-1',
            'playbook': 'test.yml',
            'target': 'all',
            'status': 'running',
            'assigned_worker': 'completion-worker',
            'started_at': (datetime.now() - timedelta(minutes=5)).isoformat()
        }
        self.storage.save_job(self.job)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_job_completion_success(self):
        """Test marking job as completed successfully."""
        updates = {
            'status': 'completed',
            'exit_code': 0,
            'completed_at': datetime.now().isoformat(),
            'duration_seconds': 300
        }
        self.storage.update_job('completion-job-1', updates)

        job = self.storage.get_job('completion-job-1')
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['exit_code'], 0)
        self.assertIsNotNone(job['completed_at'])
        self.assertEqual(job['duration_seconds'], 300)

    def test_job_completion_failure(self):
        """Test marking job as failed."""
        updates = {
            'status': 'failed',
            'exit_code': 2,
            'completed_at': datetime.now().isoformat(),
            'error_message': 'Task failed: host unreachable'
        }
        self.storage.update_job('completion-job-1', updates)

        job = self.storage.get_job('completion-job-1')
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['exit_code'], 2)
        self.assertEqual(job['error_message'], 'Task failed: host unreachable')

    def test_job_log_file_stored(self):
        """Test that log file reference is stored."""
        updates = {
            'status': 'completed',
            'exit_code': 0,
            'completed_at': datetime.now().isoformat(),
            'log_file': 'completion-job-1-2024-01-01.log'
        }
        self.storage.update_job('completion-job-1', updates)

        job = self.storage.get_job('completion-job-1')
        self.assertEqual(job['log_file'], 'completion-job-1-2024-01-01.log')


class TestWorkerStatisticsUpdate(unittest.TestCase):
    """Test worker statistics updates on job completion."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

        # Create test worker with initial stats
        self.worker = {
            'id': 'stats-worker',
            'name': 'Stats Test Worker',
            'tags': [],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'stats': {
                'jobs_completed': 10,
                'jobs_failed': 2,
                'avg_job_duration': 120.0,
                'load_1m': 0.5  # Other stats to preserve
            }
        }
        self.storage.save_worker(self.worker)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_increment_jobs_completed(self):
        """Test incrementing jobs_completed count."""
        worker = self.storage.get_worker('stats-worker')
        current_stats = worker.get('stats', {})

        # Increment completion count
        updated_stats = {
            **current_stats,
            'jobs_completed': current_stats.get('jobs_completed', 0) + 1
        }
        self.storage.update_worker_checkin('stats-worker', {'stats': updated_stats})

        worker = self.storage.get_worker('stats-worker')
        self.assertEqual(worker['stats']['jobs_completed'], 11)

    def test_increment_jobs_failed(self):
        """Test incrementing jobs_failed count."""
        worker = self.storage.get_worker('stats-worker')
        current_stats = worker.get('stats', {})

        updated_stats = {
            **current_stats,
            'jobs_failed': current_stats.get('jobs_failed', 0) + 1
        }
        self.storage.update_worker_checkin('stats-worker', {'stats': updated_stats})

        worker = self.storage.get_worker('stats-worker')
        self.assertEqual(worker['stats']['jobs_failed'], 3)

    def test_update_average_duration(self):
        """Test updating average job duration."""
        worker = self.storage.get_worker('stats-worker')
        current_stats = worker.get('stats', {})

        # New job took 180 seconds
        new_duration = 180.0
        total_jobs = current_stats.get('jobs_completed', 0) + current_stats.get('jobs_failed', 0) + 1
        old_avg = current_stats.get('avg_job_duration', 0)

        # Calculate running average
        new_avg = ((old_avg * (total_jobs - 1)) + new_duration) / total_jobs

        updated_stats = {
            **current_stats,
            'avg_job_duration': round(new_avg, 2)
        }
        self.storage.update_worker_checkin('stats-worker', {'stats': updated_stats})

        worker = self.storage.get_worker('stats-worker')
        self.assertIsNotNone(worker['stats']['avg_job_duration'])

    def test_preserves_other_stats(self):
        """Test that updating stats preserves other fields."""
        worker = self.storage.get_worker('stats-worker')
        current_stats = worker.get('stats', {})

        # Update only job counts
        updated_stats = {
            **current_stats,
            'jobs_completed': current_stats.get('jobs_completed', 0) + 1
        }
        self.storage.update_worker_checkin('stats-worker', {'stats': updated_stats})

        worker = self.storage.get_worker('stats-worker')
        # Original load_1m should be preserved
        self.assertEqual(worker['stats'].get('load_1m'), 0.5)


class TestCMDBFactsExtraction(unittest.TestCase):
    """Test CMDB facts extraction from job completion."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_host_facts(self):
        """Test saving CMDB facts from job completion."""
        facts = {
            'ansible_facts': {
                'hostname': 'webserver1',
                'os_family': 'RedHat',
                'memory_mb': 8192
            },
            '_meta': {
                'job_id': 'job-123',
                'playbook': 'hardware-inventory.yml',
                'collected_at': datetime.now().isoformat()
            }
        }

        result = self.storage.save_host_facts(
            host='webserver1',
            collection='hardware-inventory',
            data=facts,
            groups=[],
            source='job'
        )

        self.assertIn('status', result)

    def test_facts_from_multiple_hosts(self):
        """Test saving facts for multiple hosts."""
        hosts_facts = {
            'web1': {'cpu_count': 4, 'memory_gb': 8},
            'web2': {'cpu_count': 8, 'memory_gb': 16},
            'db1': {'cpu_count': 16, 'memory_gb': 64}
        }

        for host, facts in hosts_facts.items():
            self.storage.save_host_facts(
                host=host,
                collection='system-info',
                data={'system': facts},
                groups=[],
                source='job'
            )

        # Should be able to retrieve all hosts individually
        for host in hosts_facts.keys():
            facts = self.storage.get_host_facts(host)
            self.assertIsNotNone(facts)
            self.assertIn('system-info', facts.get('collections', {}))


class TestPiggybackCheckin(unittest.TestCase):
    """Test piggyback checkin processing on job completion."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

        # Create worker
        self.worker = {
            'id': 'piggyback-worker',
            'name': 'Piggyback Test Worker',
            'tags': [],
            'status': 'busy',
            'registered_at': datetime.now().isoformat(),
            'sync_revision': 'old-rev'
        }
        self.storage.save_worker(self.worker)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_piggyback_updates_sync_revision(self):
        """Test that piggyback checkin updates sync revision."""
        checkin_data = {
            'sync_revision': 'new-rev-123',
            'status': 'online'
        }
        self.storage.update_worker_checkin('piggyback-worker', checkin_data)

        worker = self.storage.get_worker('piggyback-worker')
        self.assertEqual(worker['sync_revision'], 'new-rev-123')

    def test_piggyback_updates_status(self):
        """Test that piggyback checkin updates status."""
        checkin_data = {
            'status': 'online'
        }
        self.storage.update_worker_checkin('piggyback-worker', checkin_data)

        worker = self.storage.get_worker('piggyback-worker')
        self.assertEqual(worker['status'], 'online')

    def test_piggyback_updates_system_stats(self):
        """Test that piggyback checkin updates system stats."""
        checkin_data = {
            'stats': {
                'load_1m': 0.8,
                'memory_percent': 65
            }
        }
        self.storage.update_worker_checkin('piggyback-worker', checkin_data)

        worker = self.storage.get_worker('piggyback-worker')
        self.assertEqual(worker['stats']['load_1m'], 0.8)
        self.assertEqual(worker['stats']['memory_percent'], 65)


class TestAPIClientComplete(unittest.TestCase):
    """Test API client complete_job method."""

    @patch('worker.api_client.requests.request')
    def test_complete_job_basic(self, mock_request):
        """Test basic job completion."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'job_id': 'job-1',
            'status': 'completed',
            'exit_code': 0
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')

        result = client.complete_job('job-1', 'worker-1', exit_code=0)

        self.assertTrue(result.success)
        mock_request.assert_called_once()

    @patch('worker.api_client.requests.request')
    def test_complete_job_with_log_content(self, mock_request):
        """Test job completion with log content upload."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'job_id': 'job-1',
            'status': 'completed',
            'log_stored': True
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')

        log_content = "PLAY [test] ***\nok: [host1]\nPLAY RECAP ***"
        result = client.complete_job(
            'job-1', 'worker-1', exit_code=0,
            log_content=log_content
        )

        self.assertTrue(result.success)
        call_args = mock_request.call_args
        sent_data = call_args[1]['json']
        self.assertEqual(sent_data['log_content'], log_content)

    @patch('worker.api_client.requests.request')
    def test_complete_job_with_duration(self, mock_request):
        """Test job completion with duration."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {'job_id': 'job-1', 'status': 'completed'}
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')

        result = client.complete_job(
            'job-1', 'worker-1', exit_code=0,
            duration_seconds=120.5
        )

        self.assertTrue(result.success)
        call_args = mock_request.call_args
        sent_data = call_args[1]['json']
        self.assertEqual(sent_data['duration_seconds'], 120.5)

    @patch('worker.api_client.requests.request')
    def test_complete_job_with_cmdb_facts(self, mock_request):
        """Test job completion with CMDB facts."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'job_id': 'job-1',
            'status': 'completed',
            'cmdb_facts_stored': 2
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')

        cmdb_facts = {
            'host1': {'memory': 8192},
            'host2': {'memory': 16384}
        }
        result = client.complete_job(
            'job-1', 'worker-1', exit_code=0,
            cmdb_facts=cmdb_facts
        )

        self.assertTrue(result.success)
        call_args = mock_request.call_args
        sent_data = call_args[1]['json']
        self.assertEqual(sent_data['cmdb_facts'], cmdb_facts)

    @patch('worker.api_client.requests.request')
    def test_complete_job_with_piggyback_checkin(self, mock_request):
        """Test job completion with piggyback checkin."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'job_id': 'job-1',
            'status': 'completed',
            'checkin_processed': True
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')

        checkin = {
            'sync_revision': 'abc123',
            'system_stats': {'load_1m': 0.5}
        }
        result = client.complete_job(
            'job-1', 'worker-1', exit_code=0,
            checkin=checkin
        )

        self.assertTrue(result.success)
        call_args = mock_request.call_args
        sent_data = call_args[1]['json']
        self.assertEqual(sent_data['checkin'], checkin)

    @patch('worker.api_client.requests.request')
    def test_complete_job_failure(self, mock_request):
        """Test job completion with failure."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'job_id': 'job-1',
            'status': 'failed',
            'exit_code': 2
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')

        result = client.complete_job(
            'job-1', 'worker-1', exit_code=2,
            error_message='Host unreachable'
        )

        self.assertTrue(result.success)
        call_args = mock_request.call_args
        sent_data = call_args[1]['json']
        self.assertEqual(sent_data['exit_code'], 2)
        self.assertEqual(sent_data['error_message'], 'Host unreachable')


class TestJobResultDataclass(unittest.TestCase):
    """Test JobResult dataclass."""

    def test_success_result(self):
        """Test successful job result."""
        from worker.executor import JobResult

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
        from worker.executor import JobResult

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


if __name__ == '__main__':
    unittest.main()
