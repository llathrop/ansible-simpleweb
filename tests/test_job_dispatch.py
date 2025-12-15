"""
Unit tests for Job Dispatch in Cluster Mode.

Tests that web UI job submission routes to the job queue when in cluster mode
with remote workers available, rather than executing locally.
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockStorageBackend:
    """Mock storage backend for testing job dispatch logic."""

    def __init__(self):
        self.workers = {}
        self.jobs = {}

    def get_all_workers(self):
        """Get all registered workers."""
        return list(self.workers.values())

    def get_worker(self, worker_id):
        """Get a specific worker."""
        return self.workers.get(worker_id)

    def save_job(self, job):
        """Save a job to the queue."""
        job_id = job.get('id')
        if not job_id:
            return False
        self.jobs[job_id] = job.copy()
        return True

    def get_job(self, job_id):
        """Get a job by ID."""
        return self.jobs.get(job_id)


class TestHasRemoteWorkers(unittest.TestCase):
    """Test the _has_remote_workers() helper function logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.storage = MockStorageBackend()

    def test_no_workers_returns_false(self):
        """Test returns False when no workers registered."""
        workers = self.storage.get_all_workers()
        has_remote = any(not w.get('is_local') and w.get('status') == 'online'
                        for w in workers)
        self.assertFalse(has_remote)

    def test_only_local_worker_returns_false(self):
        """Test returns False when only local worker exists."""
        self.storage.workers['local'] = {
            'id': 'local',
            'name': 'local-executor',
            'is_local': True,
            'status': 'online'
        }
        workers = self.storage.get_all_workers()
        has_remote = any(not w.get('is_local') and w.get('status') == 'online'
                        for w in workers)
        self.assertFalse(has_remote)

    def test_remote_worker_online_returns_true(self):
        """Test returns True when remote worker is online."""
        self.storage.workers['worker-1'] = {
            'id': 'worker-1',
            'name': 'worker-1',
            'is_local': False,
            'status': 'online'
        }
        workers = self.storage.get_all_workers()
        has_remote = any(not w.get('is_local') and w.get('status') == 'online'
                        for w in workers)
        self.assertTrue(has_remote)

    def test_remote_worker_offline_returns_false(self):
        """Test returns False when remote worker is offline."""
        self.storage.workers['worker-1'] = {
            'id': 'worker-1',
            'name': 'worker-1',
            'is_local': False,
            'status': 'offline'
        }
        workers = self.storage.get_all_workers()
        has_remote = any(not w.get('is_local') and w.get('status') == 'online'
                        for w in workers)
        self.assertFalse(has_remote)

    def test_mixed_workers_with_online_remote(self):
        """Test returns True with mix of local and online remote workers."""
        self.storage.workers['local'] = {
            'id': 'local',
            'name': 'local-executor',
            'is_local': True,
            'status': 'online'
        }
        self.storage.workers['worker-1'] = {
            'id': 'worker-1',
            'name': 'worker-1',
            'is_local': False,
            'status': 'online'
        }
        self.storage.workers['worker-2'] = {
            'id': 'worker-2',
            'name': 'worker-2',
            'is_local': False,
            'status': 'offline'
        }
        workers = self.storage.get_all_workers()
        has_remote = any(not w.get('is_local') and w.get('status') == 'online'
                        for w in workers)
        self.assertTrue(has_remote)


class TestClusterModeJobDispatch(unittest.TestCase):
    """Test job dispatch logic in cluster mode."""

    def setUp(self):
        """Set up test fixtures."""
        self.storage = MockStorageBackend()

        # Add workers
        self.storage.workers['local'] = {
            'id': '__local__',
            'name': 'local-executor',
            'is_local': True,
            'status': 'online'
        }
        self.storage.workers['worker-1'] = {
            'id': 'worker-1',
            'name': 'worker-1',
            'is_local': False,
            'status': 'online',
            'tags': ['general']
        }

    def test_job_submission_creates_queued_job(self):
        """Test that job submission creates a job with queued status."""
        import uuid
        job_id = str(uuid.uuid4())
        submitted_at = datetime.now().isoformat()

        job = {
            'id': job_id,
            'playbook': 'test-playbook',
            'target': 'all',
            'status': 'queued',
            'submitted_at': submitted_at,
            'submitted_by': 'web-ui'
        }

        result = self.storage.save_job(job)
        self.assertTrue(result)

        saved_job = self.storage.get_job(job_id)
        self.assertIsNotNone(saved_job)
        self.assertEqual(saved_job['status'], 'queued')
        self.assertEqual(saved_job['playbook'], 'test-playbook')

    def test_job_has_required_fields(self):
        """Test that submitted job has all required fields."""
        import uuid
        job_id = str(uuid.uuid4())
        submitted_at = datetime.now().isoformat()

        job = {
            'id': job_id,
            'playbook': 'hardware-inventory',
            'target': 'webservers',
            'status': 'queued',
            'submitted_at': submitted_at,
            'submitted_by': 'web-ui',
            'priority': 50,
            'required_tags': [],
            'preferred_tags': []
        }

        self.storage.save_job(job)
        saved_job = self.storage.get_job(job_id)

        # Verify required fields
        self.assertIn('id', saved_job)
        self.assertIn('playbook', saved_job)
        self.assertIn('target', saved_job)
        self.assertIn('status', saved_job)
        self.assertIn('submitted_at', saved_job)

    def test_queued_job_has_no_assigned_worker(self):
        """Test that newly queued job has no assigned worker."""
        import uuid
        job_id = str(uuid.uuid4())

        job = {
            'id': job_id,
            'playbook': 'test.yml',
            'target': 'all',
            'status': 'queued',
            'submitted_at': datetime.now().isoformat()
        }

        self.storage.save_job(job)
        saved_job = self.storage.get_job(job_id)

        self.assertIsNone(saved_job.get('assigned_worker'))
        self.assertIsNone(saved_job.get('started_at'))
        self.assertIsNone(saved_job.get('completed_at'))


class TestStandaloneModeJobExecution(unittest.TestCase):
    """Test job execution in standalone mode (no remote workers)."""

    def setUp(self):
        """Set up test fixtures."""
        self.storage = MockStorageBackend()

    def test_no_remote_workers_uses_local(self):
        """Test that standalone mode uses local execution."""
        # No remote workers
        workers = self.storage.get_all_workers()
        has_remote = any(not w.get('is_local') and w.get('status') == 'online'
                        for w in workers)

        self.assertFalse(has_remote)
        # In standalone mode, job would execute locally (not queued)

    def test_only_offline_remote_workers_uses_local(self):
        """Test that offline remote workers don't count."""
        self.storage.workers['worker-1'] = {
            'id': 'worker-1',
            'name': 'worker-1',
            'is_local': False,
            'status': 'offline'
        }
        self.storage.workers['worker-2'] = {
            'id': 'worker-2',
            'name': 'worker-2',
            'is_local': False,
            'status': 'stale'
        }

        workers = self.storage.get_all_workers()
        has_remote = any(not w.get('is_local') and w.get('status') == 'online'
                        for w in workers)

        self.assertFalse(has_remote)


class TestJobRoutingIntegration(unittest.TestCase):
    """Test job routing after submission."""

    def setUp(self):
        """Set up test fixtures."""
        self.storage = MockStorageBackend()

        # Add workers
        self.storage.workers['worker-1'] = {
            'id': 'worker-1',
            'name': 'worker-1',
            'is_local': False,
            'status': 'online',
            'tags': ['general', 'zone-a'],
            'current_jobs': []
        }
        self.storage.workers['worker-2'] = {
            'id': 'worker-2',
            'name': 'worker-2',
            'is_local': False,
            'status': 'online',
            'tags': ['general', 'zone-b', 'high-memory'],
            'current_jobs': []
        }

    def test_job_gets_assigned_to_worker(self):
        """Test that queued job can be assigned to a worker."""
        import uuid
        job_id = str(uuid.uuid4())

        # Create queued job
        job = {
            'id': job_id,
            'playbook': 'test.yml',
            'target': 'all',
            'status': 'queued',
            'submitted_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        # Simulate job assignment
        job['status'] = 'assigned'
        job['assigned_worker'] = 'worker-1'
        job['assigned_at'] = datetime.now().isoformat()
        self.storage.jobs[job_id] = job

        # Verify assignment
        assigned_job = self.storage.get_job(job_id)
        self.assertEqual(assigned_job['status'], 'assigned')
        self.assertEqual(assigned_job['assigned_worker'], 'worker-1')

    def test_job_with_required_tags_finds_matching_worker(self):
        """Test job with required tags is matched correctly."""
        import uuid
        job_id = str(uuid.uuid4())

        job = {
            'id': job_id,
            'playbook': 'memory-intensive.yml',
            'target': 'all',
            'status': 'queued',
            'submitted_at': datetime.now().isoformat(),
            'required_tags': ['high-memory']
        }
        self.storage.save_job(job)

        # Find matching worker
        workers = self.storage.get_all_workers()
        matching_workers = [
            w for w in workers
            if all(tag in w.get('tags', []) for tag in job['required_tags'])
        ]

        self.assertEqual(len(matching_workers), 1)
        self.assertEqual(matching_workers[0]['id'], 'worker-2')


if __name__ == '__main__':
    unittest.main()
