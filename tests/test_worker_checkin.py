"""
Unit tests for Worker Check-in System (Feature 9).

Tests the worker check-in storage operations and API client functionality.
Uses mock storage backend to test logic without Flask dependencies.
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


class TestWorkerCheckinStorage(unittest.TestCase):
    """Test worker check-in storage operations."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

        # Create test worker
        self.worker_id = 'checkin-test-worker'
        self.worker = {
            'id': self.worker_id,
            'name': 'Checkin Test Worker',
            'tags': ['test', 'web'],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'is_local': False
        }
        self.storage.save_worker(self.worker)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_update_worker_checkin(self):
        """Test that checkin updates worker properly."""
        checkin_data = {
            'sync_revision': 'abc123def',
            'status': 'busy',
            'stats': {
                'load_1m': 1.5,
                'memory_percent': 65,
                'cpu_percent': 45
            }
        }

        result = self.storage.update_worker_checkin(self.worker_id, checkin_data)
        self.assertTrue(result)

        # Verify worker was updated
        worker = self.storage.get_worker(self.worker_id)
        self.assertEqual(worker['sync_revision'], 'abc123def')
        self.assertEqual(worker['status'], 'busy')
        self.assertIn('stats', worker)
        self.assertEqual(worker['stats']['load_1m'], 1.5)
        self.assertIsNotNone(worker.get('last_checkin'))

    def test_checkin_updates_timestamp(self):
        """Test that checkin updates last_checkin timestamp."""
        # Initial checkin
        self.storage.update_worker_checkin(self.worker_id, {'status': 'online'})
        worker = self.storage.get_worker(self.worker_id)
        first_checkin = worker.get('last_checkin')

        self.assertIsNotNone(first_checkin)

        # Wait a tiny bit and checkin again
        import time
        time.sleep(0.01)
        self.storage.update_worker_checkin(self.worker_id, {'status': 'online'})
        worker = self.storage.get_worker(self.worker_id)
        second_checkin = worker.get('last_checkin')

        # Timestamp should be different (later)
        self.assertIsNotNone(second_checkin)
        self.assertNotEqual(first_checkin, second_checkin)

    def test_checkin_partial_data(self):
        """Test checkin with partial data only updates provided fields."""
        # Set initial values
        self.storage.update_worker_checkin(self.worker_id, {
            'sync_revision': 'rev1',
            'status': 'online'
        })

        # Checkin with only status
        self.storage.update_worker_checkin(self.worker_id, {
            'status': 'busy'
        })

        worker = self.storage.get_worker(self.worker_id)
        self.assertEqual(worker['status'], 'busy')
        self.assertEqual(worker['sync_revision'], 'rev1')  # Unchanged

    def test_checkin_nonexistent_worker(self):
        """Test checkin for non-existent worker returns False."""
        result = self.storage.update_worker_checkin('nonexistent-id', {'status': 'online'})
        self.assertFalse(result)


class TestStaleWorkerDetection(unittest.TestCase):
    """Test stale worker detection logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)
        self.checkin_interval = 60  # 60 seconds for testing

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _is_worker_stale(self, worker, checkin_interval):
        """Helper to check if worker is stale (2x interval threshold)."""
        if worker.get('is_local'):
            return False

        stale_threshold = datetime.now().timestamp() - (checkin_interval * 2)
        last_checkin = worker.get('last_checkin', '')

        if last_checkin:
            try:
                checkin_time = datetime.fromisoformat(last_checkin).timestamp()
                return checkin_time < stale_threshold
            except (ValueError, TypeError):
                return True

        # No checkin - check registration time
        registered_at = worker.get('registered_at', '')
        if registered_at:
            try:
                reg_time = datetime.fromisoformat(registered_at).timestamp()
                return reg_time < stale_threshold
            except (ValueError, TypeError):
                return False

        return False

    def test_fresh_worker_not_stale(self):
        """Test that recently checked-in worker is not stale."""
        worker = {
            'id': 'fresh-worker',
            'name': 'Fresh Worker',
            'tags': [],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat(),
            'is_local': False
        }
        self.storage.save_worker(worker)

        self.assertFalse(self._is_worker_stale(worker, self.checkin_interval))

    def test_old_worker_is_stale(self):
        """Test that worker with old checkin is stale."""
        old_time = (datetime.now() - timedelta(hours=1)).isoformat()
        worker = {
            'id': 'stale-worker',
            'name': 'Stale Worker',
            'tags': [],
            'status': 'online',
            'registered_at': old_time,
            'last_checkin': old_time,
            'is_local': False
        }
        self.storage.save_worker(worker)

        self.assertTrue(self._is_worker_stale(worker, self.checkin_interval))

    def test_local_worker_never_stale(self):
        """Test that local worker is never marked stale."""
        old_time = (datetime.now() - timedelta(hours=1)).isoformat()
        worker = {
            'id': '__local__',
            'name': 'Local Worker',
            'tags': ['local'],
            'status': 'online',
            'registered_at': old_time,
            'last_checkin': old_time,
            'is_local': True
        }
        self.storage.save_worker(worker)

        self.assertFalse(self._is_worker_stale(worker, self.checkin_interval))

    def test_worker_at_threshold_boundary(self):
        """Test worker exactly at threshold boundary."""
        # Worker that checked in exactly at the threshold
        threshold_time = (datetime.now() - timedelta(seconds=self.checkin_interval * 2 - 1)).isoformat()
        worker = {
            'id': 'boundary-worker',
            'name': 'Boundary Worker',
            'tags': [],
            'status': 'online',
            'registered_at': threshold_time,
            'last_checkin': threshold_time,
            'is_local': False
        }

        # Should not be stale (just inside threshold)
        self.assertFalse(self._is_worker_stale(worker, self.checkin_interval))

    def test_newly_registered_no_checkin(self):
        """Test newly registered worker with no checkin."""
        worker = {
            'id': 'new-worker',
            'name': 'New Worker',
            'tags': [],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'is_local': False
        }
        self.storage.save_worker(worker)

        # New worker with no checkin shouldn't be stale
        self.assertFalse(self._is_worker_stale(worker, self.checkin_interval))


class TestWorkerJobRequeue(unittest.TestCase):
    """Test job requeuing when workers become stale."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

        # Create stale worker
        old_time = (datetime.now() - timedelta(hours=1)).isoformat()
        self.stale_worker = {
            'id': 'stale-worker-1',
            'name': 'Stale Worker',
            'tags': [],
            'status': 'busy',
            'registered_at': old_time,
            'last_checkin': old_time,
            'is_local': False
        }
        self.storage.save_worker(self.stale_worker)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_requeue_assigned_jobs(self):
        """Test that jobs assigned to stale workers can be requeued."""
        # Create job assigned to stale worker
        job = {
            'id': 'job-to-requeue',
            'playbook': 'test.yml',
            'target': 'all',
            'status': 'assigned',
            'assigned_worker': 'stale-worker-1',
            'assigned_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        # Requeue the job
        requeue_updates = {
            'status': 'queued',
            'assigned_worker': None,
            'assigned_at': None,
            'error_message': 'Requeued: Worker became stale'
        }
        self.storage.update_job('job-to-requeue', requeue_updates)

        # Verify job was requeued
        updated_job = self.storage.get_job('job-to-requeue')
        self.assertEqual(updated_job['status'], 'queued')
        self.assertIsNone(updated_job['assigned_worker'])
        self.assertIn('Requeued', updated_job['error_message'])

    def test_requeue_running_jobs(self):
        """Test that running jobs on stale workers can be requeued."""
        job = {
            'id': 'running-job',
            'playbook': 'deploy.yml',
            'target': 'web',
            'status': 'running',
            'assigned_worker': 'stale-worker-1',
            'assigned_at': datetime.now().isoformat(),
            'started_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        # Requeue
        self.storage.update_job('running-job', {
            'status': 'queued',
            'assigned_worker': None,
            'assigned_at': None,
            'started_at': None
        })

        updated_job = self.storage.get_job('running-job')
        self.assertEqual(updated_job['status'], 'queued')

    def test_get_worker_jobs_for_requeue(self):
        """Test getting jobs assigned to a worker."""
        # Create multiple jobs
        for i in range(3):
            self.storage.save_job({
                'id': f'worker-job-{i}',
                'playbook': f'test{i}.yml',
                'target': 'all',
                'status': 'running' if i < 2 else 'completed',
                'assigned_worker': 'stale-worker-1'
            })

        # Get active jobs for worker
        all_jobs = self.storage.get_all_jobs({
            'assigned_worker': 'stale-worker-1',
            'status': ['assigned', 'running']
        })

        # Should find 2 active jobs (not the completed one)
        self.assertEqual(len(all_jobs), 2)


class TestWorkerClientCheckin(unittest.TestCase):
    """Test worker client check-in functionality."""

    def test_checkin_method_exists(self):
        """Test that API client has checkin method."""
        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')
        self.assertTrue(hasattr(client, 'checkin'))

    @patch('worker.api_client.requests.request')
    def test_checkin_sends_correct_data(self, mock_request):
        """Test that checkin sends correct data format."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'message': 'Checkin successful',
            'next_checkin_seconds': 600,
            'sync_needed': False
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')

        checkin_data = {
            'sync_revision': 'abc123',
            'active_jobs': [],
            'system_stats': {'load_1m': 0.5}
        }

        result = client.checkin('worker-123', checkin_data)

        self.assertTrue(result.success)
        mock_request.assert_called_once()

        call_args = mock_request.call_args
        self.assertEqual(call_args[0][0], 'POST')
        self.assertIn('worker-123', call_args[0][1])
        self.assertIn('checkin', call_args[0][1])

    @patch('worker.api_client.requests.request')
    def test_checkin_handles_sync_needed(self, mock_request):
        """Test that checkin response includes sync_needed flag."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'message': 'Checkin successful',
            'next_checkin_seconds': 600,
            'sync_needed': True,
            'current_revision': 'abc1234'
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')

        result = client.checkin('worker-123', {})

        self.assertTrue(result.success)
        self.assertTrue(result.data.get('sync_needed'))
        self.assertEqual(result.data.get('current_revision'), 'abc1234')

    @patch('worker.api_client.requests.request')
    def test_checkin_with_active_jobs(self, mock_request):
        """Test checkin with active job status."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {'message': 'Checkin successful'}
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')

        checkin_data = {
            'active_jobs': [
                {'job_id': 'job-1', 'status': 'running', 'progress': 50},
                {'job_id': 'job-2', 'status': 'running', 'progress': 25}
            ],
            'status': 'busy'
        }

        result = client.checkin('worker-123', checkin_data)
        self.assertTrue(result.success)

        # Verify data was sent
        call_args = mock_request.call_args
        sent_data = call_args[1]['json']
        self.assertEqual(len(sent_data['active_jobs']), 2)

    @patch('worker.api_client.requests.request')
    def test_checkin_failure_handling(self, mock_request):
        """Test handling of checkin failure."""
        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.json.return_value = {'error': 'Server error'}
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')

        result = client.checkin('worker-123', {})

        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 500)


class TestWorkerServiceCheckin(unittest.TestCase):
    """Test worker service check-in integration."""

    def test_worker_service_has_checkin(self):
        """Test that worker service has checkin functionality."""
        from worker.service import WorkerService

        # Check that the _checkin method exists
        self.assertTrue(hasattr(WorkerService, '_checkin'))

    def test_worker_service_get_system_stats(self):
        """Test that worker service can get system stats."""
        from worker.service import WorkerService
        from worker.config import WorkerConfig

        # Create mock config
        config = Mock(spec=WorkerConfig)
        config.server_url = 'http://localhost:3001'
        config.worker_name = 'test-worker'
        config.content_dir = '/tmp/test-content'
        config.logs_dir = '/tmp/test-logs'
        config.tags = []
        config.registration_token = ''
        config.checkin_interval = 60
        config.sync_interval = 300
        config.poll_interval = 5
        config.max_concurrent_jobs = 2
        config.worker_id = None
        config.validate.return_value = []

        # Create service with mocked API client
        with patch('worker.service.PrimaryAPIClient'):
            with patch('worker.service.ContentSync'):
                service = WorkerService(config)

                # Test _get_system_stats method exists and returns dict
                stats = service._get_system_stats()
                self.assertIsInstance(stats, dict)
                # May or may not have keys depending on system


if __name__ == '__main__':
    unittest.main()
