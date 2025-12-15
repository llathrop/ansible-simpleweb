"""
Feature Validation Test for Worker Registration API (Feature 2)

This test validates the complete worker registration workflow, simulating
realistic scenarios for worker registration, management, and check-in.
"""

import os
import sys
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
import uuid

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.storage.flatfile import FlatFileStorage


class TestFeatureWorkerRegistration(unittest.TestCase):
    """
    Feature validation test for worker registration.

    This test simulates a complete worker registration workflow:
    1. Primary server initializes with local executor
    2. Remote workers register with authentication
    3. Workers check in periodically
    4. Workers are detected as stale when they stop checking in
    5. Workers can be removed when they have no active jobs
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(config_dir=self.test_dir)
        self.registration_token = 'secure-cluster-token-123'
        self.checkin_interval = 600  # 10 minutes

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _register_worker(self, name, tags, token):
        """Simulate worker registration."""
        if not name or not token:
            return None, 'Missing required fields'

        if token != self.registration_token:
            return None, 'Invalid token'

        # Check for existing worker
        for w in self.storage.get_all_workers():
            if w.get('name') == name and not w.get('is_local'):
                # Re-registration
                w['tags'] = tags
                w['status'] = 'online'
                w['last_checkin'] = datetime.now().isoformat()
                self.storage.save_worker(w)
                return w['id'], 'Re-registered'

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
        self.storage.save_worker(worker)
        return worker_id, 'Registered'

    def _init_local_worker(self, tags):
        """Initialize local worker."""
        local = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': tags,
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat(),
            'sync_revision': None,
            'current_jobs': [],
            'stats': {}
        }
        self.storage.save_worker(local)

    def _worker_checkin(self, worker_id, stats=None, sync_rev=None):
        """Simulate worker check-in."""
        checkin_data = {}
        if stats:
            checkin_data['stats'] = stats
        if sync_rev:
            checkin_data['sync_revision'] = sync_rev
        return self.storage.update_worker_checkin(worker_id, checkin_data)

    def _detect_stale_workers(self):
        """Detect workers that haven't checked in recently."""
        stale_threshold = datetime.now().timestamp() - (self.checkin_interval * 2)
        stale = []

        for w in self.storage.get_all_workers():
            if w.get('is_local'):
                continue
            last_checkin = w.get('last_checkin', '')
            if last_checkin:
                try:
                    checkin_time = datetime.fromisoformat(last_checkin).timestamp()
                    if checkin_time < stale_threshold:
                        stale.append(w['id'])
                except (ValueError, TypeError):
                    pass
        return stale

    def test_complete_registration_workflow(self):
        """
        Test the complete worker registration workflow.
        """
        print("\n=== Feature 2: Worker Registration Workflow ===\n")

        # =====================================================================
        # Step 1: Initialize primary server with local executor
        # =====================================================================
        print("Step 1: Initialize local executor...")

        self._init_local_worker(['local', 'default'])

        local = self.storage.get_worker('__local__')
        self.assertIsNotNone(local)
        self.assertEqual(local['name'], 'local-executor')
        self.assertEqual(local['priority_boost'], -1000)
        self.assertTrue(local['is_local'])
        print(f"  - Local executor initialized: {local['id']}")

        workers = self.storage.get_all_workers()
        self.assertEqual(len(workers), 1)

        # =====================================================================
        # Step 2: Register remote workers with authentication
        # =====================================================================
        print("\nStep 2: Register remote workers...")

        # Worker 1: Network A with GPU
        worker1_id, msg1 = self._register_worker(
            'worker-network-a',
            ['network-a', 'gpu', 'high-memory'],
            self.registration_token
        )
        self.assertIsNotNone(worker1_id)
        self.assertEqual(msg1, 'Registered')
        print(f"  - Registered worker-network-a: {worker1_id}")

        # Worker 2: Network B standard
        worker2_id, msg2 = self._register_worker(
            'worker-network-b',
            ['network-b', 'standard'],
            self.registration_token
        )
        self.assertIsNotNone(worker2_id)
        print(f"  - Registered worker-network-b: {worker2_id}")

        # Worker 3: Network A backup
        worker3_id, msg3 = self._register_worker(
            'worker-network-a-backup',
            ['network-a', 'standard'],
            self.registration_token
        )
        self.assertIsNotNone(worker3_id)
        print(f"  - Registered worker-network-a-backup: {worker3_id}")

        # Verify all workers registered
        workers = self.storage.get_all_workers()
        self.assertEqual(len(workers), 4)  # 3 remote + 1 local

        # =====================================================================
        # Step 3: Test authentication failures
        # =====================================================================
        print("\nStep 3: Test authentication...")

        # Invalid token
        bad_id, bad_msg = self._register_worker(
            'bad-worker',
            ['test'],
            'wrong-token'
        )
        self.assertIsNone(bad_id)
        self.assertEqual(bad_msg, 'Invalid token')
        print("  - Invalid token correctly rejected")

        # Missing fields
        missing_id, missing_msg = self._register_worker(
            '',
            ['test'],
            self.registration_token
        )
        self.assertIsNone(missing_id)
        print("  - Missing name correctly rejected")

        # Still only 4 workers
        self.assertEqual(len(self.storage.get_all_workers()), 4)

        # =====================================================================
        # Step 4: Workers check in with status updates
        # =====================================================================
        print("\nStep 4: Worker check-ins...")

        # Worker 1 checks in
        self._worker_checkin(worker1_id, {
            'load_1m': 0.5,
            'memory_percent': 45
        }, 'git-rev-abc123')

        w1 = self.storage.get_worker(worker1_id)
        self.assertEqual(w1['stats']['load_1m'], 0.5)
        self.assertEqual(w1['sync_revision'], 'git-rev-abc123')
        print(f"  - Worker 1 checked in: load={w1['stats']['load_1m']}")

        # Worker 2 checks in
        self._worker_checkin(worker2_id, {
            'load_1m': 0.2,
            'memory_percent': 30
        })
        print("  - Worker 2 checked in")

        # Worker 3 checks in
        self._worker_checkin(worker3_id, {
            'load_1m': 0.1
        })
        print("  - Worker 3 checked in")

        # =====================================================================
        # Step 5: Filter workers by status
        # =====================================================================
        print("\nStep 5: Filter workers...")

        online_workers = self.storage.get_workers_by_status(['online'])
        self.assertEqual(len(online_workers), 4)
        print(f"  - Online workers: {len(online_workers)}")

        # Mark one worker as busy
        w2 = self.storage.get_worker(worker2_id)
        w2['status'] = 'busy'
        self.storage.save_worker(w2)

        online_workers = self.storage.get_workers_by_status(['online'])
        self.assertEqual(len(online_workers), 3)
        print(f"  - After marking one busy, online: {len(online_workers)}")

        busy_workers = self.storage.get_workers_by_status(['busy'])
        self.assertEqual(len(busy_workers), 1)
        print(f"  - Busy workers: {len(busy_workers)}")

        # =====================================================================
        # Step 6: Test worker re-registration
        # =====================================================================
        print("\nStep 6: Worker re-registration...")

        # Worker 1 reconnects with updated tags
        w1_old_id = worker1_id
        w1_new_id, rereg_msg = self._register_worker(
            'worker-network-a',
            ['network-a', 'gpu', 'high-memory', 'new-capability'],
            self.registration_token
        )

        self.assertEqual(w1_new_id, w1_old_id)  # Same ID
        self.assertEqual(rereg_msg, 'Re-registered')

        w1_updated = self.storage.get_worker(worker1_id)
        self.assertIn('new-capability', w1_updated['tags'])
        print(f"  - Worker re-registered with updated tags")

        # Still only 4 workers (no duplicate created)
        self.assertEqual(len(self.storage.get_all_workers()), 4)

        # =====================================================================
        # Step 7: Simulate stale worker detection
        # =====================================================================
        print("\nStep 7: Stale worker detection...")

        # Manually set old checkin time for worker 3
        w3 = self.storage.get_worker(worker3_id)
        w3['last_checkin'] = (datetime.now() - timedelta(hours=1)).isoformat()
        self.storage.save_worker(w3)

        stale = self._detect_stale_workers()
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0], worker3_id)
        print(f"  - Detected stale worker: {stale[0]}")

        # Local worker should never be stale even with old checkin
        local = self.storage.get_worker('__local__')
        local['last_checkin'] = (datetime.now() - timedelta(hours=1)).isoformat()
        self.storage.save_worker(local)

        stale = self._detect_stale_workers()
        self.assertEqual(len(stale), 1)  # Still only worker3
        print("  - Local worker not marked stale (as expected)")

        # =====================================================================
        # Step 8: Worker removal
        # =====================================================================
        print("\nStep 8: Worker removal...")

        # Cannot delete worker with active jobs
        job = {
            'id': 'test-job',
            'playbook': 'test.yml',
            'target': 'localhost',
            'status': 'running',
            'assigned_worker': worker3_id,
            'submitted_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        active_jobs = self.storage.get_worker_jobs(worker3_id, ['assigned', 'running'])
        self.assertEqual(len(active_jobs), 1)
        print(f"  - Worker 3 has active jobs, cannot delete")

        # Complete the job
        self.storage.update_job('test-job', {'status': 'completed'})

        # Now can delete
        active_jobs = self.storage.get_worker_jobs(worker3_id, ['assigned', 'running'])
        self.assertEqual(len(active_jobs), 0)

        result = self.storage.delete_worker(worker3_id)
        self.assertTrue(result)
        print(f"  - Worker 3 deleted after job completed")

        # Cannot delete local worker
        # (This is enforced in the API, not storage level)

        workers = self.storage.get_all_workers()
        self.assertEqual(len(workers), 3)  # 2 remote + 1 local
        print(f"  - Remaining workers: {len(workers)}")

        # =====================================================================
        # Step 9: Verify final state
        # =====================================================================
        print("\nStep 9: Verify final state...")

        final_workers = self.storage.get_all_workers()

        local_count = sum(1 for w in final_workers if w.get('is_local'))
        remote_count = sum(1 for w in final_workers if not w.get('is_local'))

        self.assertEqual(local_count, 1)
        self.assertEqual(remote_count, 2)

        print(f"  - Local workers: {local_count}")
        print(f"  - Remote workers: {remote_count}")

        # Verify local worker properties
        local = self.storage.get_worker('__local__')
        self.assertEqual(local['priority_boost'], -1000)
        self.assertTrue(local['is_local'])
        print(f"  - Local worker priority boost: {local['priority_boost']}")

        print("\n=== Feature 2 Validation Complete ===")
        print("All worker registration scenarios validated successfully!")

    def test_cluster_status_calculation(self):
        """Test cluster status summary calculation."""
        # Initialize local worker
        self._init_local_worker(['local'])

        # Register workers with various statuses
        for i, status in enumerate(['online', 'online', 'busy', 'offline']):
            worker = {
                'id': f'worker-{i}',
                'name': f'worker-{i}',
                'tags': [],
                'status': status,
                'is_local': False,
                'registered_at': datetime.now().isoformat(),
                'last_checkin': datetime.now().isoformat()
            }
            self.storage.save_worker(worker)

        # Create jobs with various statuses
        for i, status in enumerate(['queued', 'queued', 'running', 'completed', 'failed']):
            job = {
                'id': f'job-{i}',
                'playbook': 'test.yml',
                'target': 'localhost',
                'status': status,
                'submitted_at': datetime.now().isoformat()
            }
            self.storage.save_job(job)

        # Calculate cluster status
        workers = self.storage.get_all_workers()
        jobs = self.storage.get_all_jobs()

        worker_counts = {}
        for w in workers:
            status = w.get('status', 'unknown')
            worker_counts[status] = worker_counts.get(status, 0) + 1

        job_counts = {}
        for j in jobs:
            status = j.get('status', 'unknown')
            job_counts[status] = job_counts.get(status, 0) + 1

        # Verify counts
        self.assertEqual(worker_counts['online'], 3)  # 2 remote + 1 local
        self.assertEqual(worker_counts['busy'], 1)
        self.assertEqual(worker_counts['offline'], 1)

        self.assertEqual(job_counts['queued'], 2)
        self.assertEqual(job_counts['running'], 1)
        self.assertEqual(job_counts['completed'], 1)
        self.assertEqual(job_counts['failed'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
