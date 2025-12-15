"""
Unit tests for Worker and Job Queue storage operations.

Tests both flatfile and MongoDB backends for cluster support functionality.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from typing import Dict, List
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.storage.flatfile import FlatFileStorage


class TestWorkerStorageFlatFile(unittest.TestCase):
    """Test worker operations for flat file storage."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(config_dir=self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_test_worker(self, worker_id: str = 'worker-1', **kwargs) -> Dict:
        """Create a test worker dict."""
        worker = {
            'id': worker_id,
            'name': kwargs.get('name', f'test-worker-{worker_id}'),
            'tags': kwargs.get('tags', ['tag-a', 'tag-b']),
            'priority_boost': kwargs.get('priority_boost', 0),
            'status': kwargs.get('status', 'online'),
            'is_local': kwargs.get('is_local', False),
            'registered_at': kwargs.get('registered_at', datetime.now().isoformat()),
            'last_checkin': kwargs.get('last_checkin', datetime.now().isoformat()),
            'sync_revision': kwargs.get('sync_revision', 'abc123'),
            'current_jobs': kwargs.get('current_jobs', []),
            'stats': kwargs.get('stats', {
                'load_1m': 0.5,
                'memory_percent': 45,
                'jobs_completed': 10,
                'jobs_failed': 1,
                'avg_job_duration': 120
            })
        }
        return worker

    # =========================================================================
    # Basic CRUD Tests
    # =========================================================================

    def test_save_worker_creates_new(self):
        """Test saving a new worker."""
        worker = self._create_test_worker('worker-new')
        result = self.storage.save_worker(worker)

        self.assertTrue(result)

        # Verify it was saved
        saved = self.storage.get_worker('worker-new')
        self.assertIsNotNone(saved)
        self.assertEqual(saved['name'], worker['name'])
        self.assertEqual(saved['tags'], worker['tags'])

    def test_save_worker_updates_existing(self):
        """Test updating an existing worker."""
        worker = self._create_test_worker('worker-update')
        self.storage.save_worker(worker)

        # Update worker
        worker['status'] = 'busy'
        worker['tags'] = ['new-tag']
        result = self.storage.save_worker(worker)

        self.assertTrue(result)

        saved = self.storage.get_worker('worker-update')
        self.assertEqual(saved['status'], 'busy')
        self.assertEqual(saved['tags'], ['new-tag'])

    def test_save_worker_requires_id(self):
        """Test that save_worker fails without an id."""
        worker = {'name': 'no-id-worker'}
        result = self.storage.save_worker(worker)
        self.assertFalse(result)

    def test_get_worker_not_found(self):
        """Test getting a non-existent worker returns None."""
        result = self.storage.get_worker('non-existent')
        self.assertIsNone(result)

    def test_get_all_workers_empty(self):
        """Test getting workers when none exist."""
        workers = self.storage.get_all_workers()
        self.assertEqual(workers, [])

    def test_get_all_workers_sorted_by_registered_at(self):
        """Test that workers are sorted by registered_at descending."""
        # Create workers with different registration times
        old_time = (datetime.now() - timedelta(hours=2)).isoformat()
        new_time = datetime.now().isoformat()

        worker1 = self._create_test_worker('worker-1', registered_at=old_time)
        worker2 = self._create_test_worker('worker-2', registered_at=new_time)

        self.storage.save_worker(worker1)
        self.storage.save_worker(worker2)

        workers = self.storage.get_all_workers()

        self.assertEqual(len(workers), 2)
        # Newest first
        self.assertEqual(workers[0]['id'], 'worker-2')
        self.assertEqual(workers[1]['id'], 'worker-1')

    def test_delete_worker_success(self):
        """Test deleting an existing worker."""
        worker = self._create_test_worker('worker-delete')
        self.storage.save_worker(worker)

        result = self.storage.delete_worker('worker-delete')
        self.assertTrue(result)

        # Verify deletion
        saved = self.storage.get_worker('worker-delete')
        self.assertIsNone(saved)

    def test_delete_worker_not_found(self):
        """Test deleting a non-existent worker returns False."""
        result = self.storage.delete_worker('non-existent')
        self.assertFalse(result)

    # =========================================================================
    # Status Filter Tests
    # =========================================================================

    def test_get_workers_by_status_single(self):
        """Test filtering workers by a single status."""
        worker1 = self._create_test_worker('worker-1', status='online')
        worker2 = self._create_test_worker('worker-2', status='offline')
        worker3 = self._create_test_worker('worker-3', status='online')

        self.storage.save_worker(worker1)
        self.storage.save_worker(worker2)
        self.storage.save_worker(worker3)

        online_workers = self.storage.get_workers_by_status(['online'])

        self.assertEqual(len(online_workers), 2)
        for w in online_workers:
            self.assertEqual(w['status'], 'online')

    def test_get_workers_by_status_multiple(self):
        """Test filtering workers by multiple statuses."""
        worker1 = self._create_test_worker('worker-1', status='online')
        worker2 = self._create_test_worker('worker-2', status='busy')
        worker3 = self._create_test_worker('worker-3', status='stale')

        self.storage.save_worker(worker1)
        self.storage.save_worker(worker2)
        self.storage.save_worker(worker3)

        workers = self.storage.get_workers_by_status(['online', 'busy'])

        self.assertEqual(len(workers), 2)
        statuses = {w['status'] for w in workers}
        self.assertEqual(statuses, {'online', 'busy'})

    def test_get_workers_by_status_empty_result(self):
        """Test filtering returns empty when no matches."""
        worker = self._create_test_worker('worker-1', status='online')
        self.storage.save_worker(worker)

        workers = self.storage.get_workers_by_status(['stale'])
        self.assertEqual(workers, [])

    # =========================================================================
    # Checkin Tests
    # =========================================================================

    def test_update_worker_checkin_updates_timestamp(self):
        """Test that checkin updates last_checkin timestamp."""
        worker = self._create_test_worker('worker-checkin')
        old_checkin = (datetime.now() - timedelta(hours=1)).isoformat()
        worker['last_checkin'] = old_checkin
        self.storage.save_worker(worker)

        result = self.storage.update_worker_checkin('worker-checkin', {})

        self.assertTrue(result)

        updated = self.storage.get_worker('worker-checkin')
        self.assertIsNotNone(updated)
        # last_checkin should be updated to a newer time
        self.assertGreater(updated['last_checkin'], old_checkin)

    def test_update_worker_checkin_updates_stats(self):
        """Test that checkin updates stats."""
        worker = self._create_test_worker('worker-stats')
        self.storage.save_worker(worker)

        new_stats = {
            'load_1m': 0.9,
            'memory_percent': 80
        }
        result = self.storage.update_worker_checkin('worker-stats', {'stats': new_stats})

        self.assertTrue(result)

        updated = self.storage.get_worker('worker-stats')
        self.assertEqual(updated['stats']['load_1m'], 0.9)
        self.assertEqual(updated['stats']['memory_percent'], 80)
        # Original stats should still be present
        self.assertIn('jobs_completed', updated['stats'])

    def test_update_worker_checkin_updates_sync_revision(self):
        """Test that checkin updates sync_revision."""
        worker = self._create_test_worker('worker-sync')
        self.storage.save_worker(worker)

        result = self.storage.update_worker_checkin('worker-sync', {
            'sync_revision': 'new-rev-456'
        })

        self.assertTrue(result)

        updated = self.storage.get_worker('worker-sync')
        self.assertEqual(updated['sync_revision'], 'new-rev-456')

    def test_update_worker_checkin_not_found(self):
        """Test checkin on non-existent worker returns False."""
        result = self.storage.update_worker_checkin('non-existent', {})
        self.assertFalse(result)


class TestJobQueueStorageFlatFile(unittest.TestCase):
    """Test job queue operations for flat file storage."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(config_dir=self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_test_job(self, job_id: str = 'job-1', **kwargs) -> Dict:
        """Create a test job dict."""
        job = {
            'id': job_id,
            'playbook': kwargs.get('playbook', 'test-playbook.yml'),
            'target': kwargs.get('target', 'webservers'),
            'required_tags': kwargs.get('required_tags', []),
            'preferred_tags': kwargs.get('preferred_tags', []),
            'priority': kwargs.get('priority', 50),
            'job_type': kwargs.get('job_type', 'normal'),
            'status': kwargs.get('status', 'queued'),
            'assigned_worker': kwargs.get('assigned_worker', None),
            'submitted_by': kwargs.get('submitted_by', 'user'),
            'submitted_at': kwargs.get('submitted_at', datetime.now().isoformat()),
            'assigned_at': kwargs.get('assigned_at', None),
            'started_at': kwargs.get('started_at', None),
            'completed_at': kwargs.get('completed_at', None),
            'log_file': kwargs.get('log_file', None),
            'exit_code': kwargs.get('exit_code', None),
            'error_message': kwargs.get('error_message', None)
        }
        return job

    # =========================================================================
    # Basic CRUD Tests
    # =========================================================================

    def test_save_job_creates_new(self):
        """Test saving a new job."""
        job = self._create_test_job('job-new')
        result = self.storage.save_job(job)

        self.assertTrue(result)

        saved = self.storage.get_job('job-new')
        self.assertIsNotNone(saved)
        self.assertEqual(saved['playbook'], job['playbook'])
        self.assertEqual(saved['status'], 'queued')

    def test_save_job_updates_existing(self):
        """Test updating an existing job."""
        job = self._create_test_job('job-update')
        self.storage.save_job(job)

        job['status'] = 'running'
        job['started_at'] = datetime.now().isoformat()
        result = self.storage.save_job(job)

        self.assertTrue(result)

        saved = self.storage.get_job('job-update')
        self.assertEqual(saved['status'], 'running')
        self.assertIsNotNone(saved['started_at'])

    def test_save_job_requires_id(self):
        """Test that save_job fails without an id."""
        job = {'playbook': 'test.yml'}
        result = self.storage.save_job(job)
        self.assertFalse(result)

    def test_get_job_not_found(self):
        """Test getting a non-existent job returns None."""
        result = self.storage.get_job('non-existent')
        self.assertIsNone(result)

    def test_get_all_jobs_empty(self):
        """Test getting jobs when none exist."""
        jobs = self.storage.get_all_jobs()
        self.assertEqual(jobs, [])

    def test_get_all_jobs_sorted_by_submitted_at(self):
        """Test that jobs are sorted by submitted_at descending."""
        old_time = (datetime.now() - timedelta(hours=2)).isoformat()
        new_time = datetime.now().isoformat()

        job1 = self._create_test_job('job-1', submitted_at=old_time)
        job2 = self._create_test_job('job-2', submitted_at=new_time)

        self.storage.save_job(job1)
        self.storage.save_job(job2)

        jobs = self.storage.get_all_jobs()

        self.assertEqual(len(jobs), 2)
        # Newest first
        self.assertEqual(jobs[0]['id'], 'job-2')
        self.assertEqual(jobs[1]['id'], 'job-1')

    def test_delete_job_success(self):
        """Test deleting an existing job."""
        job = self._create_test_job('job-delete')
        self.storage.save_job(job)

        result = self.storage.delete_job('job-delete')
        self.assertTrue(result)

        saved = self.storage.get_job('job-delete')
        self.assertIsNone(saved)

    def test_delete_job_not_found(self):
        """Test deleting a non-existent job returns False."""
        result = self.storage.delete_job('non-existent')
        self.assertFalse(result)

    # =========================================================================
    # Update Job Tests
    # =========================================================================

    def test_update_job_partial(self):
        """Test partial job update."""
        job = self._create_test_job('job-partial')
        self.storage.save_job(job)

        result = self.storage.update_job('job-partial', {
            'status': 'assigned',
            'assigned_worker': 'worker-1',
            'assigned_at': datetime.now().isoformat()
        })

        self.assertTrue(result)

        updated = self.storage.get_job('job-partial')
        self.assertEqual(updated['status'], 'assigned')
        self.assertEqual(updated['assigned_worker'], 'worker-1')
        # Original fields should still be present
        self.assertEqual(updated['playbook'], 'test-playbook.yml')

    def test_update_job_not_found(self):
        """Test update on non-existent job returns False."""
        result = self.storage.update_job('non-existent', {'status': 'running'})
        self.assertFalse(result)

    # =========================================================================
    # Filter Tests
    # =========================================================================

    def test_get_all_jobs_with_filters(self):
        """Test filtering jobs by criteria."""
        job1 = self._create_test_job('job-1', status='queued', playbook='play-a.yml')
        job2 = self._create_test_job('job-2', status='running', playbook='play-b.yml')
        job3 = self._create_test_job('job-3', status='queued', playbook='play-a.yml')

        self.storage.save_job(job1)
        self.storage.save_job(job2)
        self.storage.save_job(job3)

        # Filter by status
        queued = self.storage.get_all_jobs({'status': 'queued'})
        self.assertEqual(len(queued), 2)

        # Filter by playbook
        play_a = self.storage.get_all_jobs({'playbook': 'play-a.yml'})
        self.assertEqual(len(play_a), 2)

        # Filter by multiple criteria
        filtered = self.storage.get_all_jobs({'status': 'queued', 'playbook': 'play-a.yml'})
        self.assertEqual(len(filtered), 2)

    def test_get_pending_jobs(self):
        """Test getting pending (queued) jobs."""
        job1 = self._create_test_job('job-1', status='queued')
        job2 = self._create_test_job('job-2', status='running')
        job3 = self._create_test_job('job-3', status='queued')

        self.storage.save_job(job1)
        self.storage.save_job(job2)
        self.storage.save_job(job3)

        pending = self.storage.get_pending_jobs()

        self.assertEqual(len(pending), 2)
        for job in pending:
            self.assertEqual(job['status'], 'queued')

    def test_get_pending_jobs_sorted_by_priority(self):
        """Test pending jobs are sorted by priority (highest first)."""
        old_time = (datetime.now() - timedelta(hours=1)).isoformat()
        new_time = datetime.now().isoformat()

        job1 = self._create_test_job('job-low', priority=10, submitted_at=old_time)
        job2 = self._create_test_job('job-high', priority=90, submitted_at=new_time)
        job3 = self._create_test_job('job-med', priority=50, submitted_at=old_time)

        self.storage.save_job(job1)
        self.storage.save_job(job2)
        self.storage.save_job(job3)

        pending = self.storage.get_pending_jobs()

        self.assertEqual(len(pending), 3)
        # Highest priority first
        self.assertEqual(pending[0]['id'], 'job-high')
        self.assertEqual(pending[1]['id'], 'job-med')
        self.assertEqual(pending[2]['id'], 'job-low')

    def test_get_pending_jobs_same_priority_sorted_by_time(self):
        """Test same priority jobs are sorted by submitted_at (oldest first)."""
        old_time = (datetime.now() - timedelta(hours=2)).isoformat()
        new_time = datetime.now().isoformat()

        job1 = self._create_test_job('job-new', priority=50, submitted_at=new_time)
        job2 = self._create_test_job('job-old', priority=50, submitted_at=old_time)

        self.storage.save_job(job1)
        self.storage.save_job(job2)

        pending = self.storage.get_pending_jobs()

        self.assertEqual(len(pending), 2)
        # Oldest first when same priority
        self.assertEqual(pending[0]['id'], 'job-old')
        self.assertEqual(pending[1]['id'], 'job-new')

    # =========================================================================
    # Worker Jobs Tests
    # =========================================================================

    def test_get_worker_jobs(self):
        """Test getting jobs for a specific worker."""
        job1 = self._create_test_job('job-1', assigned_worker='worker-a')
        job2 = self._create_test_job('job-2', assigned_worker='worker-b')
        job3 = self._create_test_job('job-3', assigned_worker='worker-a')

        self.storage.save_job(job1)
        self.storage.save_job(job2)
        self.storage.save_job(job3)

        worker_a_jobs = self.storage.get_worker_jobs('worker-a')

        self.assertEqual(len(worker_a_jobs), 2)
        for job in worker_a_jobs:
            self.assertEqual(job['assigned_worker'], 'worker-a')

    def test_get_worker_jobs_with_status_filter(self):
        """Test getting worker jobs filtered by status."""
        job1 = self._create_test_job('job-1', assigned_worker='worker-a', status='assigned')
        job2 = self._create_test_job('job-2', assigned_worker='worker-a', status='running')
        job3 = self._create_test_job('job-3', assigned_worker='worker-a', status='completed')

        self.storage.save_job(job1)
        self.storage.save_job(job2)
        self.storage.save_job(job3)

        active_jobs = self.storage.get_worker_jobs('worker-a', statuses=['assigned', 'running'])

        self.assertEqual(len(active_jobs), 2)

    def test_get_worker_jobs_empty(self):
        """Test getting jobs for worker with no jobs."""
        jobs = self.storage.get_worker_jobs('worker-no-jobs')
        self.assertEqual(jobs, [])

    # =========================================================================
    # Cleanup Tests
    # =========================================================================

    def test_cleanup_jobs_no_cleanup_needed(self):
        """Test cleanup when under keep_count."""
        for i in range(5):
            job = self._create_test_job(f'job-{i}', status='completed')
            self.storage.save_job(job)

        removed = self.storage.cleanup_jobs(max_age_days=30, keep_count=500)

        self.assertEqual(removed, 0)
        self.assertEqual(len(self.storage.get_all_jobs()), 5)

    def test_cleanup_jobs_removes_old_terminal_jobs(self):
        """Test cleanup removes old completed/failed jobs."""
        old_time = (datetime.now() - timedelta(days=60)).isoformat()
        new_time = datetime.now().isoformat()

        # Create many jobs to exceed keep_count
        for i in range(10):
            job = self._create_test_job(
                f'job-old-{i}',
                status='completed',
                submitted_at=old_time
            )
            self.storage.save_job(job)

        for i in range(5):
            job = self._create_test_job(
                f'job-new-{i}',
                status='completed',
                submitted_at=new_time
            )
            self.storage.save_job(job)

        removed = self.storage.cleanup_jobs(max_age_days=30, keep_count=5)

        # Should remove old jobs
        self.assertGreater(removed, 0)

    def test_cleanup_jobs_keeps_running_jobs(self):
        """Test cleanup never removes running jobs."""
        old_time = (datetime.now() - timedelta(days=60)).isoformat()

        # Create many jobs
        for i in range(20):
            job = self._create_test_job(
                f'job-completed-{i}',
                status='completed',
                submitted_at=old_time
            )
            self.storage.save_job(job)

        # Create a running job with old timestamp
        running_job = self._create_test_job(
            'job-running',
            status='running',
            submitted_at=old_time
        )
        self.storage.save_job(running_job)

        self.storage.cleanup_jobs(max_age_days=30, keep_count=5)

        # Running job should still exist
        remaining = self.storage.get_job('job-running')
        self.assertIsNotNone(remaining)
        self.assertEqual(remaining['status'], 'running')


class TestStorageDataPersistence(unittest.TestCase):
    """Test data persistence across storage instances."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_worker_data_persists(self):
        """Test worker data persists across storage instances."""
        # Create and save with first instance
        storage1 = FlatFileStorage(config_dir=self.test_dir)
        worker = {
            'id': 'persistent-worker',
            'name': 'test',
            'tags': ['test'],
            'status': 'online',
            'registered_at': datetime.now().isoformat()
        }
        storage1.save_worker(worker)

        # Read with new instance
        storage2 = FlatFileStorage(config_dir=self.test_dir)
        loaded = storage2.get_worker('persistent-worker')

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded['name'], 'test')

    def test_job_data_persists(self):
        """Test job data persists across storage instances."""
        # Create and save with first instance
        storage1 = FlatFileStorage(config_dir=self.test_dir)
        job = {
            'id': 'persistent-job',
            'playbook': 'test.yml',
            'target': 'localhost',
            'status': 'queued',
            'priority': 50,
            'submitted_at': datetime.now().isoformat()
        }
        storage1.save_job(job)

        # Read with new instance
        storage2 = FlatFileStorage(config_dir=self.test_dir)
        loaded = storage2.get_job('persistent-job')

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded['playbook'], 'test.yml')


class TestLocalWorker(unittest.TestCase):
    """Test special handling for local worker (__local__)."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(config_dir=self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_local_worker_can_be_saved(self):
        """Test that __local__ worker ID works correctly."""
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'registered_at': datetime.now().isoformat()
        }
        result = self.storage.save_worker(local_worker)
        self.assertTrue(result)

        loaded = self.storage.get_worker('__local__')
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded['is_local'])
        self.assertEqual(loaded['priority_boost'], -1000)

    def test_jobs_can_be_assigned_to_local(self):
        """Test jobs can be assigned to __local__ worker."""
        job = {
            'id': 'local-job',
            'playbook': 'test.yml',
            'target': 'localhost',
            'status': 'assigned',
            'assigned_worker': '__local__',
            'submitted_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        local_jobs = self.storage.get_worker_jobs('__local__')
        self.assertEqual(len(local_jobs), 1)
        self.assertEqual(local_jobs[0]['id'], 'local-job')


if __name__ == '__main__':
    unittest.main()
