"""
Feature Validation Test for Worker & Job Queue Storage (Feature 1)

This test validates the complete feature workflow for cluster storage support,
simulating realistic usage scenarios for worker registration, job submission,
and the interaction between workers and jobs.
"""

import os
import sys
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.storage.flatfile import FlatFileStorage


class TestFeatureClusterStorage(unittest.TestCase):
    """
    Feature validation test for cluster storage support.

    This test simulates a complete cluster workflow:
    1. Primary server starts with local executor
    2. Remote workers register
    3. Jobs are submitted to queue
    4. Jobs are assigned to workers
    5. Workers check in with status updates
    6. Jobs complete and results are stored
    7. Workers can be removed gracefully
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(config_dir=self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_complete_cluster_workflow(self):
        """
        Test the complete workflow of a cluster operation.

        This validates Feature 1 by simulating a realistic cluster scenario
        from worker registration through job completion.
        """
        # =====================================================================
        # Step 1: Initialize local executor as implicit worker
        # =====================================================================
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local', 'default'],
            'priority_boost': -1000,  # Always lowest priority
            'status': 'online',
            'is_local': True,
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat(),
            'sync_revision': None,
            'current_jobs': [],
            'stats': {
                'load_1m': 0.1,
                'memory_percent': 30,
                'jobs_completed': 0,
                'jobs_failed': 0
            }
        }
        self.assertTrue(self.storage.save_worker(local_worker))

        # Verify local worker exists
        workers = self.storage.get_all_workers()
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0]['id'], '__local__')

        # =====================================================================
        # Step 2: Register remote workers
        # =====================================================================
        worker1 = {
            'id': 'worker-network-a',
            'name': 'worker-network-a',
            'tags': ['network-a', 'gpu', 'high-memory'],
            'priority_boost': 0,
            'status': 'online',
            'is_local': False,
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat(),
            'sync_revision': 'abc123',
            'current_jobs': [],
            'stats': {
                'load_1m': 0.2,
                'memory_percent': 40,
                'jobs_completed': 50,
                'jobs_failed': 2
            }
        }
        worker2 = {
            'id': 'worker-network-b',
            'name': 'worker-network-b',
            'tags': ['network-b', 'standard'],
            'priority_boost': 0,
            'status': 'online',
            'is_local': False,
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat(),
            'sync_revision': 'abc123',
            'current_jobs': [],
            'stats': {
                'load_1m': 0.3,
                'memory_percent': 50,
                'jobs_completed': 30,
                'jobs_failed': 1
            }
        }
        self.assertTrue(self.storage.save_worker(worker1))
        self.assertTrue(self.storage.save_worker(worker2))

        # Verify all workers exist
        workers = self.storage.get_all_workers()
        self.assertEqual(len(workers), 3)

        # =====================================================================
        # Step 3: Submit jobs to the queue
        # =====================================================================
        jobs = [
            {
                'id': 'job-1',
                'playbook': 'hardware-inventory.yml',
                'target': 'webservers',
                'required_tags': ['network-a'],  # Must run on network-a worker
                'preferred_tags': ['gpu'],
                'priority': 80,
                'job_type': 'normal',
                'status': 'queued',
                'assigned_worker': None,
                'submitted_by': 'user',
                'submitted_at': (datetime.now() - timedelta(minutes=5)).isoformat()
            },
            {
                'id': 'job-2',
                'playbook': 'software-inventory.yml',
                'target': 'dbservers',
                'required_tags': ['network-b'],  # Must run on network-b worker
                'preferred_tags': [],
                'priority': 50,
                'job_type': 'normal',
                'status': 'queued',
                'assigned_worker': None,
                'submitted_by': 'schedule:daily-inventory',
                'submitted_at': (datetime.now() - timedelta(minutes=3)).isoformat()
            },
            {
                'id': 'job-3',
                'playbook': 'system-health.yml',
                'target': 'all',
                'required_tags': [],  # Can run on any worker
                'preferred_tags': ['high-memory'],
                'priority': 30,
                'job_type': 'long_running',
                'status': 'queued',
                'assigned_worker': None,
                'submitted_by': 'user',
                'submitted_at': datetime.now().isoformat()
            }
        ]
        for job in jobs:
            self.assertTrue(self.storage.save_job(job))

        # Verify jobs in queue
        all_jobs = self.storage.get_all_jobs()
        self.assertEqual(len(all_jobs), 3)

        # Get pending jobs (sorted by priority)
        pending = self.storage.get_pending_jobs()
        self.assertEqual(len(pending), 3)
        self.assertEqual(pending[0]['id'], 'job-1')  # Highest priority
        self.assertEqual(pending[1]['id'], 'job-2')  # Medium priority
        self.assertEqual(pending[2]['id'], 'job-3')  # Lowest priority

        # =====================================================================
        # Step 4: Simulate job assignment
        # =====================================================================
        # Job 1 requires network-a, assign to worker-network-a
        self.assertTrue(self.storage.update_job('job-1', {
            'status': 'assigned',
            'assigned_worker': 'worker-network-a',
            'assigned_at': datetime.now().isoformat()
        }))

        # Job 2 requires network-b, assign to worker-network-b
        self.assertTrue(self.storage.update_job('job-2', {
            'status': 'assigned',
            'assigned_worker': 'worker-network-b',
            'assigned_at': datetime.now().isoformat()
        }))

        # Job 3 has no required tags - would normally go to remote worker
        # but for this test, simulate it going to local
        self.assertTrue(self.storage.update_job('job-3', {
            'status': 'assigned',
            'assigned_worker': '__local__',
            'assigned_at': datetime.now().isoformat()
        }))

        # Update worker current_jobs
        worker1['current_jobs'] = ['job-1']
        self.storage.save_worker(worker1)

        worker2['current_jobs'] = ['job-2']
        self.storage.save_worker(worker2)

        local_worker['current_jobs'] = ['job-3']
        self.storage.save_worker(local_worker)

        # Verify pending queue is now empty
        pending = self.storage.get_pending_jobs()
        self.assertEqual(len(pending), 0)

        # Verify jobs assigned to workers
        worker_a_jobs = self.storage.get_worker_jobs('worker-network-a')
        self.assertEqual(len(worker_a_jobs), 1)
        self.assertEqual(worker_a_jobs[0]['id'], 'job-1')

        local_jobs = self.storage.get_worker_jobs('__local__')
        self.assertEqual(len(local_jobs), 1)
        self.assertEqual(local_jobs[0]['id'], 'job-3')

        # =====================================================================
        # Step 5: Simulate job execution start
        # =====================================================================
        self.assertTrue(self.storage.update_job('job-1', {
            'status': 'running',
            'started_at': datetime.now().isoformat()
        }))
        self.assertTrue(self.storage.update_job('job-2', {
            'status': 'running',
            'started_at': datetime.now().isoformat()
        }))
        self.assertTrue(self.storage.update_job('job-3', {
            'status': 'running',
            'started_at': datetime.now().isoformat()
        }))

        # =====================================================================
        # Step 6: Worker check-in during job execution
        # =====================================================================
        self.assertTrue(self.storage.update_worker_checkin('worker-network-a', {
            'stats': {
                'load_1m': 0.8,  # Higher load during job
                'memory_percent': 65
            },
            'sync_revision': 'abc123'
        }))

        # Verify checkin updated worker
        updated_worker = self.storage.get_worker('worker-network-a')
        self.assertEqual(updated_worker['stats']['load_1m'], 0.8)

        # =====================================================================
        # Step 7: Simulate job completion
        # =====================================================================
        # Job 1 completes successfully
        self.assertTrue(self.storage.update_job('job-1', {
            'status': 'completed',
            'completed_at': datetime.now().isoformat(),
            'exit_code': 0,
            'log_file': 'logs/job-1.log'
        }))

        # Job 2 fails
        self.assertTrue(self.storage.update_job('job-2', {
            'status': 'failed',
            'completed_at': datetime.now().isoformat(),
            'exit_code': 1,
            'error_message': 'Connection timeout to dbserver-01',
            'log_file': 'logs/job-2.log'
        }))

        # Job 3 completes
        self.assertTrue(self.storage.update_job('job-3', {
            'status': 'completed',
            'completed_at': datetime.now().isoformat(),
            'exit_code': 0,
            'log_file': 'logs/job-3.log'
        }))

        # Update worker current_jobs (clear them)
        worker1['current_jobs'] = []
        worker1['stats']['jobs_completed'] = 51
        self.storage.save_worker(worker1)

        worker2['current_jobs'] = []
        worker2['stats']['jobs_failed'] = 2
        self.storage.save_worker(worker2)

        local_worker['current_jobs'] = []
        local_worker['stats']['jobs_completed'] = 1
        self.storage.save_worker(local_worker)

        # Verify job states
        job1 = self.storage.get_job('job-1')
        self.assertEqual(job1['status'], 'completed')
        self.assertEqual(job1['exit_code'], 0)

        job2 = self.storage.get_job('job-2')
        self.assertEqual(job2['status'], 'failed')
        self.assertIn('timeout', job2['error_message'])

        # =====================================================================
        # Step 8: Verify filtering and queries work correctly
        # =====================================================================
        # Get completed jobs
        completed = self.storage.get_all_jobs({'status': 'completed'})
        self.assertEqual(len(completed), 2)

        # Get failed jobs
        failed = self.storage.get_all_jobs({'status': 'failed'})
        self.assertEqual(len(failed), 1)

        # Get online workers
        online = self.storage.get_workers_by_status(['online'])
        self.assertEqual(len(online), 3)

        # =====================================================================
        # Step 9: Simulate worker going offline
        # =====================================================================
        self.assertTrue(self.storage.update_worker_checkin('worker-network-b', {
            'status': 'stale'
        }))

        stale_workers = self.storage.get_workers_by_status(['stale'])
        self.assertEqual(len(stale_workers), 1)
        self.assertEqual(stale_workers[0]['id'], 'worker-network-b')

        # =====================================================================
        # Step 10: Remove worker gracefully
        # =====================================================================
        self.assertTrue(self.storage.delete_worker('worker-network-b'))

        workers = self.storage.get_all_workers()
        self.assertEqual(len(workers), 2)

        # Verify jobs from deleted worker still exist
        job2_after = self.storage.get_job('job-2')
        self.assertIsNotNone(job2_after)
        self.assertEqual(job2_after['assigned_worker'], 'worker-network-b')

        print("\n=== Feature Validation Test Complete ===")
        print(f"Workers remaining: {len(self.storage.get_all_workers())}")
        print(f"Jobs in queue: {len(self.storage.get_all_jobs())}")
        print("All cluster storage operations validated successfully!")

    def test_data_integrity_across_operations(self):
        """
        Test that data remains consistent across multiple operations.

        This validates that the storage backend maintains data integrity
        when performing concurrent-like operations.
        """
        # Create initial state
        for i in range(5):
            worker = {
                'id': f'worker-{i}',
                'name': f'worker-{i}',
                'tags': [f'tag-{i}'],
                'status': 'online',
                'registered_at': datetime.now().isoformat()
            }
            self.storage.save_worker(worker)

            job = {
                'id': f'job-{i}',
                'playbook': f'play-{i}.yml',
                'target': 'localhost',
                'status': 'queued',
                'priority': 50,
                'submitted_at': datetime.now().isoformat()
            }
            self.storage.save_job(job)

        # Perform many updates
        for i in range(5):
            self.storage.update_job(f'job-{i}', {'status': 'running'})
            self.storage.update_worker_checkin(f'worker-{i}', {
                'stats': {'load_1m': 0.5 + (i * 0.1)}
            })

        # Verify all data is intact
        workers = self.storage.get_all_workers()
        jobs = self.storage.get_all_jobs()

        self.assertEqual(len(workers), 5)
        self.assertEqual(len(jobs), 5)

        # Verify updates were applied
        for i in range(5):
            job = self.storage.get_job(f'job-{i}')
            self.assertEqual(job['status'], 'running')

            worker = self.storage.get_worker(f'worker-{i}')
            self.assertAlmostEqual(worker['stats']['load_1m'], 0.5 + (i * 0.1))

    def test_storage_backend_type(self):
        """Verify the storage backend type is correctly identified."""
        self.assertEqual(self.storage.get_backend_type(), 'flatfile')

    def test_storage_health_check(self):
        """Verify storage health check works."""
        self.assertTrue(self.storage.health_check())


if __name__ == '__main__':
    # Run with verbose output
    unittest.main(verbosity=2)
