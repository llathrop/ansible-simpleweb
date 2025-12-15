"""
Unit tests for Worker Registration API (Feature 2).

Tests the worker registration logic and API behavior.
Note: Full API tests require Flask. Tests are designed to work without Flask
by testing the underlying logic directly.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.storage.flatfile import FlatFileStorage

# Check if Flask is available
try:
    import flask
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


class TestWorkerRegistrationLogic(unittest.TestCase):
    """Test worker registration logic without Flask dependency."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(config_dir=self.test_dir)
        self.registration_token = 'test-secret-token'

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_worker(self, name, tags, token, existing_workers=None):
        """
        Simulate worker registration logic.

        This mirrors the logic in api_worker_register without Flask dependencies.
        """
        import uuid

        # Validate required fields
        if not name:
            return {'error': 'Worker name is required'}, 400

        if not token:
            return {'error': 'Registration token is required'}, 400

        # Validate registration token
        if token != self.registration_token:
            return {'error': 'Invalid registration token'}, 401

        # Check if worker with this name already exists
        existing_workers = existing_workers or self.storage.get_all_workers()
        for w in existing_workers:
            if w.get('name') == name and not w.get('is_local'):
                # Update existing worker
                worker_id = w['id']
                worker = {
                    'id': worker_id,
                    'name': name,
                    'tags': tags,
                    'priority_boost': w.get('priority_boost', 0),
                    'status': 'online',
                    'is_local': False,
                    'registered_at': w.get('registered_at', datetime.now().isoformat()),
                    'last_checkin': datetime.now().isoformat(),
                    'sync_revision': None,
                    'current_jobs': w.get('current_jobs', []),
                    'stats': w.get('stats', {})
                }
                self.storage.save_worker(worker)
                return {
                    'worker_id': worker_id,
                    'message': 'Worker re-registered successfully'
                }, 200

        # Create new worker
        worker_id = str(uuid.uuid4())
        worker = {
            'id': worker_id,
            'name': name,
            'tags': tags,
            'priority_boost': 0,
            'status': 'online',
            'is_local': False,
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat(),
            'sync_revision': None,
            'current_jobs': [],
            'stats': {}
        }

        if not self.storage.save_worker(worker):
            return {'error': 'Failed to save worker'}, 500

        return {
            'worker_id': worker_id,
            'message': 'Worker registered successfully'
        }, 201

    def _delete_worker(self, worker_id):
        """
        Simulate worker deletion logic.
        """
        if worker_id == '__local__':
            return {'error': 'Cannot delete local executor'}, 400

        worker = self.storage.get_worker(worker_id)
        if not worker:
            return {'error': 'Worker not found'}, 404

        # Check for active jobs
        active_jobs = self.storage.get_worker_jobs(worker_id, statuses=['assigned', 'running'])
        if active_jobs:
            return {
                'error': 'Worker has active jobs',
                'active_jobs': len(active_jobs)
            }, 409

        if not self.storage.delete_worker(worker_id):
            return {'error': 'Failed to delete worker'}, 500

        return {'message': 'Worker deleted successfully'}, 200

    def _worker_checkin(self, worker_id, checkin_data):
        """
        Simulate worker checkin logic.
        """
        worker = self.storage.get_worker(worker_id)
        if not worker:
            return {'error': 'Worker not found'}, 404

        update_data = {}
        if 'sync_revision' in checkin_data:
            update_data['sync_revision'] = checkin_data['sync_revision']
        if 'system_stats' in checkin_data:
            update_data['stats'] = checkin_data['system_stats']
        if 'status' in checkin_data:
            update_data['status'] = checkin_data['status']

        if not self.storage.update_worker_checkin(worker_id, update_data):
            return {'error': 'Failed to update worker'}, 500

        return {'message': 'Checkin successful'}, 200

    # =========================================================================
    # Registration Tests
    # =========================================================================

    def test_register_worker_success(self):
        """Test successful worker registration."""
        result, status = self._create_worker(
            name='new-worker',
            tags=['network-a', 'gpu'],
            token='test-secret-token'
        )

        self.assertEqual(status, 201)
        self.assertIn('worker_id', result)
        self.assertEqual(result['message'], 'Worker registered successfully')

        # Verify worker was saved
        workers = self.storage.get_all_workers()
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0]['name'], 'new-worker')
        self.assertEqual(workers[0]['tags'], ['network-a', 'gpu'])
        self.assertEqual(workers[0]['status'], 'online')

    def test_register_worker_invalid_token(self):
        """Test registration with invalid token."""
        result, status = self._create_worker(
            name='bad-worker',
            tags=[],
            token='wrong-token'
        )

        self.assertEqual(status, 401)
        self.assertIn('error', result)
        self.assertIn('Invalid registration token', result['error'])

    def test_register_worker_missing_name(self):
        """Test registration without name."""
        result, status = self._create_worker(
            name='',
            tags=['test'],
            token='test-secret-token'
        )

        self.assertEqual(status, 400)
        self.assertIn('error', result)

    def test_register_worker_missing_token(self):
        """Test registration without token."""
        result, status = self._create_worker(
            name='worker-no-token',
            tags=[],
            token=''
        )

        self.assertEqual(status, 400)

    def test_register_worker_reregistration(self):
        """Test re-registering an existing worker updates it."""
        # Create existing worker
        existing_id = 'existing-id'
        existing = {
            'id': existing_id,
            'name': 'existing-worker',
            'tags': ['old-tag'],
            'status': 'offline',
            'is_local': False,
            'registered_at': (datetime.now() - timedelta(days=1)).isoformat(),
            'last_checkin': (datetime.now() - timedelta(hours=2)).isoformat()
        }
        self.storage.save_worker(existing)

        # Re-register with new tags
        result, status = self._create_worker(
            name='existing-worker',
            tags=['new-tag-1', 'new-tag-2'],
            token='test-secret-token'
        )

        self.assertEqual(status, 200)
        self.assertEqual(result['worker_id'], existing_id)
        self.assertIn('re-registered', result['message'])

        # Verify worker was updated
        updated = self.storage.get_worker(existing_id)
        self.assertEqual(updated['tags'], ['new-tag-1', 'new-tag-2'])
        self.assertEqual(updated['status'], 'online')

    def test_register_multiple_workers(self):
        """Test registering multiple workers."""
        for i in range(3):
            result, status = self._create_worker(
                name=f'worker-{i}',
                tags=[f'tag-{i}'],
                token='test-secret-token'
            )
            self.assertEqual(status, 201)

        workers = self.storage.get_all_workers()
        self.assertEqual(len(workers), 3)

    # =========================================================================
    # Get Workers Tests
    # =========================================================================

    def test_get_all_workers(self):
        """Test getting all workers."""
        # Create some workers
        for i in range(3):
            self._create_worker(f'worker-{i}', [f'tag-{i}'], 'test-secret-token')

        workers = self.storage.get_all_workers()
        self.assertEqual(len(workers), 3)

    def test_get_workers_by_status(self):
        """Test filtering workers by status."""
        self._create_worker('online-1', ['a'], 'test-secret-token')
        self._create_worker('online-2', ['b'], 'test-secret-token')

        # Create an offline worker manually
        offline = {
            'id': 'offline-id',
            'name': 'offline-1',
            'tags': ['c'],
            'status': 'offline',
            'is_local': False,
            'registered_at': datetime.now().isoformat()
        }
        self.storage.save_worker(offline)

        online_workers = self.storage.get_workers_by_status(['online'])
        self.assertEqual(len(online_workers), 2)

        offline_workers = self.storage.get_workers_by_status(['offline'])
        self.assertEqual(len(offline_workers), 1)

    def test_get_single_worker(self):
        """Test getting a single worker by ID."""
        result, _ = self._create_worker('single-worker', ['test'], 'test-secret-token')
        worker_id = result['worker_id']

        worker = self.storage.get_worker(worker_id)
        self.assertIsNotNone(worker)
        self.assertEqual(worker['name'], 'single-worker')

    def test_get_worker_not_found(self):
        """Test getting non-existent worker."""
        worker = self.storage.get_worker('non-existent-id')
        self.assertIsNone(worker)

    # =========================================================================
    # Delete Worker Tests
    # =========================================================================

    def test_delete_worker_success(self):
        """Test deleting a worker."""
        result, _ = self._create_worker('to-delete', ['test'], 'test-secret-token')
        worker_id = result['worker_id']

        delete_result, status = self._delete_worker(worker_id)

        self.assertEqual(status, 200)
        self.assertIn('deleted successfully', delete_result['message'])

        # Verify deletion
        self.assertIsNone(self.storage.get_worker(worker_id))

    def test_delete_local_worker_fails(self):
        """Test that local worker cannot be deleted."""
        # Create local worker
        local = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local'],
            'status': 'online',
            'is_local': True,
            'registered_at': datetime.now().isoformat()
        }
        self.storage.save_worker(local)

        result, status = self._delete_worker('__local__')

        self.assertEqual(status, 400)
        self.assertIn('Cannot delete local executor', result['error'])

        # Verify not deleted
        self.assertIsNotNone(self.storage.get_worker('__local__'))

    def test_delete_worker_not_found(self):
        """Test deleting non-existent worker."""
        result, status = self._delete_worker('non-existent-id')
        self.assertEqual(status, 404)

    def test_delete_worker_with_active_jobs_fails(self):
        """Test that worker with active jobs cannot be deleted."""
        result, _ = self._create_worker('busy-worker', ['test'], 'test-secret-token')
        worker_id = result['worker_id']

        # Create an active job assigned to this worker
        job = {
            'id': 'active-job',
            'playbook': 'test.yml',
            'target': 'localhost',
            'status': 'running',
            'assigned_worker': worker_id,
            'submitted_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        delete_result, status = self._delete_worker(worker_id)

        self.assertEqual(status, 409)
        self.assertIn('active jobs', delete_result['error'])

        # Verify not deleted
        self.assertIsNotNone(self.storage.get_worker(worker_id))

    # =========================================================================
    # Check-in Tests
    # =========================================================================

    def test_worker_checkin_success(self):
        """Test successful worker check-in."""
        result, _ = self._create_worker('checkin-worker', ['test'], 'test-secret-token')
        worker_id = result['worker_id']

        old_worker = self.storage.get_worker(worker_id)
        old_checkin = old_worker['last_checkin']

        checkin_result, status = self._worker_checkin(worker_id, {
            'sync_revision': 'new-rev-123',
            'system_stats': {
                'load_1m': 0.75,
                'memory_percent': 60
            }
        })

        self.assertEqual(status, 200)
        self.assertEqual(checkin_result['message'], 'Checkin successful')

        # Verify worker was updated
        updated = self.storage.get_worker(worker_id)
        self.assertEqual(updated['sync_revision'], 'new-rev-123')
        self.assertEqual(updated['stats']['load_1m'], 0.75)
        self.assertGreater(updated['last_checkin'], old_checkin)

    def test_worker_checkin_not_found(self):
        """Test check-in for non-existent worker."""
        result, status = self._worker_checkin('non-existent-id', {})
        self.assertEqual(status, 404)

    def test_worker_checkin_partial_update(self):
        """Test checkin with only some fields."""
        result, _ = self._create_worker('partial-checkin', ['test'], 'test-secret-token')
        worker_id = result['worker_id']

        # Only update sync_revision
        self._worker_checkin(worker_id, {'sync_revision': 'rev-456'})

        updated = self.storage.get_worker(worker_id)
        self.assertEqual(updated['sync_revision'], 'rev-456')


class TestLocalWorkerInitialization(unittest.TestCase):
    """Test local worker initialization logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(config_dir=self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_init_local_worker(self):
        """Test creating local worker with correct properties."""
        local_worker_tags = ['local', 'test-env']

        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': local_worker_tags,
            'priority_boost': -1000,  # Always lowest priority
            'status': 'online',
            'is_local': True,
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat(),
            'sync_revision': None,
            'current_jobs': [],
            'stats': {
                'load_1m': 0.0,
                'memory_percent': 0,
                'jobs_completed': 0,
                'jobs_failed': 0,
                'avg_job_duration': 0
            }
        }
        self.storage.save_worker(local_worker)

        saved = self.storage.get_worker('__local__')
        self.assertIsNotNone(saved)
        self.assertEqual(saved['name'], 'local-executor')
        self.assertEqual(saved['priority_boost'], -1000)
        self.assertTrue(saved['is_local'])
        self.assertEqual(saved['status'], 'online')
        self.assertEqual(saved['tags'], local_worker_tags)

    def test_local_worker_is_lowest_priority(self):
        """Test that local worker has lowest priority boost."""
        # Create local worker
        local = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'registered_at': datetime.now().isoformat()
        }
        self.storage.save_worker(local)

        # Create remote workers with various boosts
        for i, boost in enumerate([0, 10, -5, 50]):
            worker = {
                'id': f'remote-{i}',
                'name': f'remote-worker-{i}',
                'tags': ['remote'],
                'priority_boost': boost,
                'status': 'online',
                'is_local': False,
                'registered_at': datetime.now().isoformat()
            }
            self.storage.save_worker(worker)

        # Verify local has lowest boost
        workers = self.storage.get_all_workers()
        local_boost = None
        min_remote_boost = float('inf')

        for w in workers:
            if w.get('is_local'):
                local_boost = w['priority_boost']
            else:
                min_remote_boost = min(min_remote_boost, w['priority_boost'])

        self.assertIsNotNone(local_boost)
        self.assertLess(local_boost, min_remote_boost)


class TestClusterStatusLogic(unittest.TestCase):
    """Test cluster status calculation logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(config_dir=self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_count_workers_by_status(self):
        """Test counting workers by status."""
        # Create workers with various statuses
        for i, status in enumerate(['online', 'online', 'offline', 'busy', 'stale']):
            worker = {
                'id': f'worker-{i}',
                'name': f'worker-{i}',
                'tags': [],
                'status': status,
                'is_local': False,
                'registered_at': datetime.now().isoformat()
            }
            self.storage.save_worker(worker)

        workers = self.storage.get_all_workers()

        # Count by status
        counts = {'online': 0, 'offline': 0, 'busy': 0, 'stale': 0}
        for w in workers:
            status = w.get('status', 'unknown')
            if status in counts:
                counts[status] += 1

        self.assertEqual(counts['online'], 2)
        self.assertEqual(counts['offline'], 1)
        self.assertEqual(counts['busy'], 1)
        self.assertEqual(counts['stale'], 1)

    def test_count_jobs_by_status(self):
        """Test counting jobs by status."""
        # Create jobs with various statuses
        for i, status in enumerate(['queued', 'queued', 'assigned', 'running', 'completed', 'failed']):
            job = {
                'id': f'job-{i}',
                'playbook': 'test.yml',
                'target': 'localhost',
                'status': status,
                'submitted_at': datetime.now().isoformat()
            }
            self.storage.save_job(job)

        jobs = self.storage.get_all_jobs()

        # Count by status
        counts = {'queued': 0, 'assigned': 0, 'running': 0, 'completed': 0, 'failed': 0}
        for j in jobs:
            status = j.get('status', 'unknown')
            if status in counts:
                counts[status] += 1

        self.assertEqual(counts['queued'], 2)
        self.assertEqual(counts['assigned'], 1)
        self.assertEqual(counts['running'], 1)
        self.assertEqual(counts['completed'], 1)
        self.assertEqual(counts['failed'], 1)

    def test_detect_stale_workers(self):
        """Test detection of stale workers."""
        checkin_interval = 600  # 10 minutes

        # Create worker with recent checkin
        recent = {
            'id': 'recent',
            'name': 'recent-worker',
            'tags': [],
            'status': 'online',
            'is_local': False,
            'last_checkin': datetime.now().isoformat(),
            'registered_at': datetime.now().isoformat()
        }
        self.storage.save_worker(recent)

        # Create worker with old checkin (stale)
        old_time = (datetime.now() - timedelta(seconds=checkin_interval * 3)).isoformat()
        stale = {
            'id': 'stale',
            'name': 'stale-worker',
            'tags': [],
            'status': 'online',
            'is_local': False,
            'last_checkin': old_time,
            'registered_at': datetime.now().isoformat()
        }
        self.storage.save_worker(stale)

        # Local worker should never be marked stale
        local = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': [],
            'status': 'online',
            'is_local': True,
            'last_checkin': old_time,
            'registered_at': datetime.now().isoformat()
        }
        self.storage.save_worker(local)

        # Detect stale workers
        stale_threshold = datetime.now().timestamp() - (checkin_interval * 2)
        stale_workers = []

        for w in self.storage.get_all_workers():
            if w.get('is_local'):
                continue
            last_checkin = w.get('last_checkin', '')
            if last_checkin:
                try:
                    checkin_time = datetime.fromisoformat(last_checkin).timestamp()
                    if checkin_time < stale_threshold:
                        stale_workers.append(w['id'])
                except (ValueError, TypeError):
                    pass

        self.assertEqual(len(stale_workers), 1)
        self.assertEqual(stale_workers[0], 'stale')


if __name__ == '__main__':
    unittest.main()
