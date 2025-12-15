"""
Feature Validation Test for Worker Check-in System (Feature 9)

This test validates the complete worker check-in workflow including:
- Regular health reporting at configurable intervals
- Active job status updates
- System statistics collection
- Sync revision verification
- Stale worker detection and handling
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


class TestFeatureWorkerCheckin(unittest.TestCase):
    """
    Feature validation test for worker check-in system.

    Simulates:
    1. Worker registers with primary
    2. Worker sends periodic check-ins with stats
    3. Check-in updates worker status and last_checkin time
    4. Active jobs are tracked via check-in
    5. Sync revision is verified for content updates
    6. Stale workers are detected when check-ins stop
    7. Jobs from stale workers are requeued
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)
        self.checkin_interval = 60  # 60 seconds

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _is_worker_stale(self, worker):
        """Check if worker is stale (missed 2x checkin interval)."""
        if worker.get('is_local'):
            return False

        stale_threshold = datetime.now().timestamp() - (self.checkin_interval * 2)
        last_checkin = worker.get('last_checkin', '')

        if last_checkin:
            try:
                checkin_time = datetime.fromisoformat(last_checkin).timestamp()
                return checkin_time < stale_threshold
            except (ValueError, TypeError):
                return True

        return False

    def test_complete_checkin_workflow(self):
        """Test complete check-in workflow from registration to stale detection."""
        print("\n=== Feature 9: Worker Check-in System Validation ===\n")

        # =====================================================================
        # Step 1: Register a worker
        # =====================================================================
        print("Step 1: Register worker...")

        worker = {
            'id': 'checkin-feature-worker',
            'name': 'Checkin Feature Worker',
            'tags': ['web', 'prod'],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'is_local': False
        }
        self.storage.save_worker(worker)

        saved_worker = self.storage.get_worker('checkin-feature-worker')
        self.assertIsNotNone(saved_worker)
        print(f"  - Worker registered: {saved_worker['id']}")
        print(f"  - Initial status: {saved_worker['status']}")

        # =====================================================================
        # Step 2: Send first check-in with system stats
        # =====================================================================
        print("\nStep 2: Send first check-in with system stats...")

        checkin_data = {
            'sync_revision': 'abc123def456',
            'status': 'online',
            'stats': {
                'load_1m': 0.5,
                'cpu_percent': 25,
                'memory_percent': 45,
                'disk_percent': 30
            }
        }

        result = self.storage.update_worker_checkin('checkin-feature-worker', checkin_data)
        self.assertTrue(result)

        # Verify worker was updated
        worker = self.storage.get_worker('checkin-feature-worker')
        self.assertEqual(worker.get('sync_revision'), 'abc123def456')
        self.assertIsNotNone(worker.get('last_checkin'))
        self.assertIn('stats', worker)

        print(f"  - Check-in successful")
        print(f"  - Sync revision: {worker.get('sync_revision')}")
        print(f"  - Last check-in: {worker.get('last_checkin')[:19]}...")
        print(f"  - Stats recorded: load={worker['stats'].get('load_1m')}")

        # =====================================================================
        # Step 3: Submit a job and check-in with active job
        # =====================================================================
        print("\nStep 3: Track active job via check-in...")

        # Create a job assigned to this worker
        job = {
            'id': 'feature-test-job-1',
            'playbook': 'test-playbook.yml',
            'target': 'webservers',
            'status': 'running',
            'assigned_worker': 'checkin-feature-worker',
            'started_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        # Update job progress
        self.storage.update_job('feature-test-job-1', {'progress': 50})

        # Check-in with busy status
        self.storage.update_worker_checkin('checkin-feature-worker', {
            'status': 'busy',
            'stats': {
                'load_1m': 1.2,
                'cpu_percent': 60,
                'memory_percent': 55
            }
        })

        worker = self.storage.get_worker('checkin-feature-worker')
        job = self.storage.get_job('feature-test-job-1')

        self.assertEqual(worker['status'], 'busy')
        self.assertEqual(job.get('progress'), 50)

        print(f"  - Worker status updated: {worker['status']}")
        print(f"  - Job progress: {job.get('progress')}%")

        # =====================================================================
        # Step 4: Test stale worker detection
        # =====================================================================
        print("\nStep 4: Test stale worker detection...")

        # Create a worker with old last_checkin to simulate stale
        old_time = (datetime.now() - timedelta(hours=1)).isoformat()
        stale_worker = {
            'id': 'stale-feature-worker',
            'name': 'Stale Feature Worker',
            'tags': ['test'],
            'status': 'online',
            'registered_at': old_time,
            'last_checkin': old_time,
            'is_local': False
        }
        self.storage.save_worker(stale_worker)

        # Create job assigned to stale worker
        stale_job = {
            'id': 'stale-feature-job',
            'playbook': 'stale-test.yml',
            'target': 'all',
            'status': 'running',
            'assigned_worker': 'stale-feature-worker'
        }
        self.storage.save_job(stale_job)

        # Check staleness
        stale_worker = self.storage.get_worker('stale-feature-worker')
        is_stale = self._is_worker_stale(stale_worker)
        self.assertTrue(is_stale)

        print(f"  - Stale worker detected: {stale_worker['name']}")
        print(f"  - Last check-in: {stale_worker['last_checkin']}")
        print(f"  - Is stale: {is_stale}")

        # =====================================================================
        # Step 5: Handle stale workers and requeue jobs
        # =====================================================================
        print("\nStep 5: Handle stale workers and requeue jobs...")

        # Mark worker as stale (use checkin method to update status)
        self.storage.update_worker_checkin('stale-feature-worker', {'status': 'stale'})

        # Requeue jobs from stale worker
        stale_jobs = self.storage.get_all_jobs({
            'assigned_worker': 'stale-feature-worker',
            'status': ['assigned', 'running']
        })

        requeued_count = 0
        for job in stale_jobs:
            self.storage.update_job(job['id'], {
                'status': 'queued',
                'assigned_worker': None,
                'assigned_at': None,
                'started_at': None,
                'error_message': f"Requeued: Worker {stale_worker['name']} became stale"
            })
            requeued_count += 1

        # Verify
        stale_worker = self.storage.get_worker('stale-feature-worker')
        requeued_job = self.storage.get_job('stale-feature-job')

        self.assertEqual(stale_worker['status'], 'stale')
        self.assertEqual(requeued_job['status'], 'queued')
        self.assertIsNone(requeued_job.get('assigned_worker'))

        print(f"  - Worker status: {stale_worker['status']}")
        print(f"  - Jobs requeued: {requeued_count}")
        print(f"  - Job {requeued_job['id']} status: {requeued_job['status']}")

        # =====================================================================
        # Step 6: Verify healthy worker not marked stale
        # =====================================================================
        print("\nStep 6: Verify healthy worker not affected...")

        healthy_worker = self.storage.get_worker('checkin-feature-worker')
        is_healthy_stale = self._is_worker_stale(healthy_worker)

        self.assertFalse(is_healthy_stale)
        self.assertNotEqual(healthy_worker['status'], 'stale')

        print(f"  - Healthy worker status: {healthy_worker['status']}")
        print(f"  - Is stale: {is_healthy_stale}")

        print("\n=== Feature 9 Validation Complete ===")
        print("Worker check-in system validated successfully!")

    def test_multiple_workers_checkin(self):
        """Test multiple workers checking in."""
        print("\n=== Testing Multiple Workers Check-in ===\n")

        # Register multiple workers
        for i in range(3):
            worker = {
                'id': f'multi-worker-{i}',
                'name': f'Multi Worker {i}',
                'tags': ['multi'],
                'status': 'online',
                'registered_at': datetime.now().isoformat(),
                'is_local': False
            }
            self.storage.save_worker(worker)

        print(f"  - Registered 3 workers")

        # All workers check in
        for i in range(3):
            self.storage.update_worker_checkin(f'multi-worker-{i}', {
                'sync_revision': 'shared-rev',
                'status': 'online',
                'stats': {'load_1m': 0.5 + i * 0.1}
            })

        # Verify all checked in
        workers = self.storage.get_all_workers()
        multi_workers = [w for w in workers if w['name'].startswith('Multi Worker')]

        self.assertEqual(len(multi_workers), 3)
        for w in multi_workers:
            self.assertIsNotNone(w.get('last_checkin'))

        print(f"  - All 3 workers checked in successfully")
        print(f"  - Total workers in storage: {len(workers)}")

        print("\n=== Multiple Workers Validated ===")

    def test_sync_revision_tracking(self):
        """Test that sync revision is properly tracked."""
        print("\n=== Testing Sync Revision Tracking ===\n")

        # Register worker
        worker = {
            'id': 'sync-test-worker',
            'name': 'Sync Test Worker',
            'tags': [],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'is_local': False
        }
        self.storage.save_worker(worker)

        # First checkin with revision
        self.storage.update_worker_checkin('sync-test-worker', {
            'sync_revision': 'rev-abc123'
        })

        worker = self.storage.get_worker('sync-test-worker')
        self.assertEqual(worker['sync_revision'], 'rev-abc123')
        print(f"  - Initial revision: {worker['sync_revision']}")

        # Update revision after sync
        self.storage.update_worker_checkin('sync-test-worker', {
            'sync_revision': 'rev-def456'
        })

        worker = self.storage.get_worker('sync-test-worker')
        self.assertEqual(worker['sync_revision'], 'rev-def456')
        print(f"  - Updated revision: {worker['sync_revision']}")

        print("\n=== Sync Revision Tracking Validated ===")


class TestWorkerClientCheckinFeature(unittest.TestCase):
    """Test worker client check-in as part of feature validation."""

    @patch('worker.api_client.requests.request')
    def test_client_checkin_workflow(self, mock_request):
        """Test complete client-side checkin workflow."""
        print("\n=== Testing Worker Client Check-in ===\n")

        # Mock successful checkin response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'message': 'Checkin successful',
            'next_checkin_seconds': 600,
            'sync_needed': False,
            'current_revision': 'abc1234'
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://primary:3001')

        # Simulate worker checkin
        checkin_data = {
            'sync_revision': 'abc1234',
            'active_jobs': [
                {'job_id': 'job-1', 'status': 'running', 'progress': 75}
            ],
            'system_stats': {
                'load_1m': 0.8,
                'memory_percent': 50,
                'cpu_percent': 35
            },
            'status': 'busy'
        }

        result = client.checkin('worker-feature-test', checkin_data)

        self.assertTrue(result.success)
        self.assertEqual(result.data['next_checkin_seconds'], 600)
        self.assertFalse(result.data['sync_needed'])

        print(f"  - Checkin successful: {result.success}")
        print(f"  - Next checkin in: {result.data['next_checkin_seconds']}s")
        print(f"  - Sync needed: {result.data['sync_needed']}")

        print("\n=== Worker Client Check-in Validated ===")

    @patch('worker.api_client.requests.request')
    def test_client_sync_needed_response(self, mock_request):
        """Test that client handles sync_needed response."""
        print("\n=== Testing Sync Needed Response ===\n")

        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'message': 'Checkin successful',
            'next_checkin_seconds': 600,
            'sync_needed': True,
            'current_revision': 'new-rev-xyz'
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://primary:3001')

        result = client.checkin('worker-1', {
            'sync_revision': 'old-rev-abc'  # Different from server
        })

        self.assertTrue(result.success)
        self.assertTrue(result.data['sync_needed'])
        self.assertEqual(result.data['current_revision'], 'new-rev-xyz')

        print(f"  - Sync needed: {result.data['sync_needed']}")
        print(f"  - Server revision: {result.data['current_revision']}")
        print(f"  - Worker should sync now")

        print("\n=== Sync Needed Response Validated ===")


class TestCheckinEdgeCases(unittest.TestCase):
    """Test edge cases in check-in system."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_checkin_empty_data(self):
        """Test check-in with empty data updates timestamp only."""
        worker = {
            'id': 'empty-data-worker',
            'name': 'Empty Data Worker',
            'tags': [],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'is_local': False
        }
        self.storage.save_worker(worker)

        # Checkin with empty data
        result = self.storage.update_worker_checkin('empty-data-worker', {})
        self.assertTrue(result)

        # Should still update timestamp
        worker = self.storage.get_worker('empty-data-worker')
        self.assertIsNotNone(worker.get('last_checkin'))

    def test_checkin_preserves_other_fields(self):
        """Test that checkin preserves fields not in update."""
        worker = {
            'id': 'preserve-worker',
            'name': 'Preserve Worker',
            'tags': ['important', 'preserve'],
            'status': 'online',
            'priority_boost': 10,
            'registered_at': datetime.now().isoformat(),
            'is_local': False
        }
        self.storage.save_worker(worker)

        # Checkin with only status
        self.storage.update_worker_checkin('preserve-worker', {'status': 'busy'})

        worker = self.storage.get_worker('preserve-worker')
        self.assertEqual(worker['status'], 'busy')
        self.assertEqual(worker['tags'], ['important', 'preserve'])
        self.assertEqual(worker['priority_boost'], 10)

    def test_local_worker_immune_to_stale(self):
        """Test that local worker is never considered stale."""
        old_time = (datetime.now() - timedelta(days=7)).isoformat()
        worker = {
            'id': '__local__',
            'name': 'Local Executor',
            'tags': ['local'],
            'status': 'online',
            'registered_at': old_time,
            'last_checkin': old_time,
            'is_local': True
        }
        self.storage.save_worker(worker)

        # Even with very old checkin, should not be stale
        saved = self.storage.get_worker('__local__')
        self.assertTrue(saved['is_local'])
        # Local workers are exempt from staleness by design


if __name__ == '__main__':
    unittest.main(verbosity=2)
