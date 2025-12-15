"""
Feature Validation Test for Local Executor as Lowest-Priority Worker (Feature 12)

This test validates the complete local worker integration including:
- Implicit __local__ worker
- Lowest priority scoring
- Uses existing execution code
- Seamless with remote workers
"""

import os
import sys
import tempfile
import shutil
import unittest
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.storage.flatfile import FlatFileStorage
from web.job_router import JobRouter


class TestFeatureLocalWorker(unittest.TestCase):
    """
    Feature validation test for local worker integration.

    Simulates:
    1. Local worker is automatically created with __local__ ID
    2. Remote workers register and become available
    3. Job submitted that both can handle
    4. Job routes to remote worker (higher priority)
    5. When remote is busy, job routes to local
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)
        self.router = JobRouter(self.storage)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_complete_local_worker_workflow(self):
        """Test complete local worker workflow."""
        print("\n=== Feature 12: Local Executor Integration Validation ===\n")

        # =====================================================================
        # Step 1: Initialize local worker (happens at startup)
        # =====================================================================
        print("Step 1: Initialize local worker...")

        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local', 'web'],
            'priority_boost': -1000,  # Always lowest priority
            'status': 'online',
            'is_local': True,
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat(),
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        self.assertEqual(local_worker['id'], '__local__')
        self.assertEqual(local_worker['priority_boost'], -1000)
        self.assertTrue(local_worker['is_local'])

        print(f"  - Worker ID: {local_worker['id']}")
        print(f"  - Priority boost: {local_worker['priority_boost']}")
        print(f"  - Is local: {local_worker['is_local']}")

        # =====================================================================
        # Step 2: Remote worker registers
        # =====================================================================
        print("\nStep 2: Remote worker registers...")

        remote_worker = {
            'id': 'remote-worker-1',
            'name': 'Remote Worker 1',
            'tags': ['web', 'production'],
            'priority_boost': 0,  # Normal priority
            'status': 'online',
            'is_local': False,
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat(),
            'max_concurrent_jobs': 3,
            'system_stats': {}
        }
        self.storage.save_worker(remote_worker)

        print(f"  - Worker ID: {remote_worker['id']}")
        print(f"  - Priority boost: {remote_worker['priority_boost']}")
        print(f"  - Is local: {remote_worker['is_local']}")

        # =====================================================================
        # Step 3: Submit job that both workers can handle
        # =====================================================================
        print("\nStep 3: Submit job (both workers eligible)...")

        job = {
            'id': 'test-job-1',
            'playbook': 'deploy.yml',
            'target': 'webservers',
            'status': 'queued',
            'priority': 0,
            'required_tags': ['web'],  # Both workers have this
            'preferred_tags': [],
            'submitted_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        print(f"  - Job ID: {job['id']}")
        print(f"  - Required tags: {job['required_tags']}")

        # =====================================================================
        # Step 4: Get worker recommendations
        # =====================================================================
        print("\nStep 4: Get worker recommendations...")

        recommendations = self.router.get_worker_recommendations('test-job-1')

        self.assertEqual(len(recommendations), 2)
        print(f"  - Candidates: {len(recommendations)}")

        for rec in recommendations:
            print(f"    - {rec['worker_name']}: score={rec['scores']['total']:.1f}, "
                  f"priority_boost={rec['scores']['priority_boost']}, "
                  f"is_local={rec['is_local']}")

        # Remote should be first (higher score)
        self.assertFalse(recommendations[0]['is_local'])
        self.assertTrue(recommendations[1]['is_local'])

        # =====================================================================
        # Step 5: Route job - should go to remote
        # =====================================================================
        print("\nStep 5: Route job (should prefer remote)...")

        result = self.router.route_job('test-job-1')

        self.assertTrue(result.get('assigned'))
        self.assertEqual(result['worker_id'], 'remote-worker-1')

        print(f"  - Assigned to: {result['worker_name']}")
        print(f"  - Worker ID: {result['worker_id']}")
        print(f"  - Score: {result['score']}")

        # =====================================================================
        # Step 6: Submit another job, make remote busy
        # =====================================================================
        print("\nStep 6: Make remote worker busy, submit another job...")

        # Update remote worker to busy (at capacity)
        self.storage.update_worker_checkin('remote-worker-1', {
            'status': 'busy',
            'max_concurrent_jobs': 1  # Set capacity to 1
        })

        # Add 3 jobs to remote worker so it's over capacity
        for i in range(3):
            busy_job = {
                'id': f'busy-job-{i}',
                'playbook': 'busy.yml',
                'target': 'all',
                'status': 'running',
                'assigned_worker': 'remote-worker-1'
            }
            self.storage.save_job(busy_job)

        # New job
        job2 = {
            'id': 'test-job-2',
            'playbook': 'backup.yml',
            'target': 'webservers',
            'status': 'queued',
            'priority': 0,
            'required_tags': ['web'],
            'preferred_tags': [],
            'submitted_at': datetime.now().isoformat()
        }
        self.storage.save_job(job2)

        print(f"  - New job: {job2['id']}")
        print(f"  - Remote worker busy with 3 jobs")

        # =====================================================================
        # Step 7: Route should fall back to local
        # =====================================================================
        print("\nStep 7: Route job (should fall back to local)...")

        result2 = self.router.route_job('test-job-2')

        self.assertTrue(result2.get('assigned'))
        self.assertEqual(result2['worker_id'], '__local__')

        print(f"  - Assigned to: {result2['worker_name']}")
        print(f"  - Worker ID: {result2['worker_id']}")
        print(f"  - Local worker used as fallback: True")

        # =====================================================================
        # Step 8: Verify final state
        # =====================================================================
        print("\nStep 8: Verify final state...")

        job1 = self.storage.get_job('test-job-1')
        job2_final = self.storage.get_job('test-job-2')

        self.assertEqual(job1['assigned_worker'], 'remote-worker-1')
        self.assertEqual(job2_final['assigned_worker'], '__local__')

        print(f"  - Job 1 -> {job1['assigned_worker']} (remote)")
        print(f"  - Job 2 -> {job2_final['assigned_worker']} (local fallback)")

        print("\n=== Feature 12 Validation Complete ===")
        print("Local worker integration validated successfully!")

    def test_local_only_mode(self):
        """Test operation with only local worker (standalone mode)."""
        print("\n=== Testing Standalone Mode (Local Only) ===\n")

        # Only local worker
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'max_concurrent_jobs': 5,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        # Submit multiple jobs
        for i in range(3):
            job = {
                'id': f'standalone-job-{i}',
                'playbook': f'playbook-{i}.yml',
                'target': 'all',
                'status': 'queued',
                'required_tags': [],
                'preferred_tags': []
            }
            self.storage.save_job(job)

        # Route all jobs
        results = self.router.route_pending_jobs(limit=5)

        # All should route to local
        for result in results:
            self.assertTrue(result.get('assigned'))
            self.assertEqual(result['worker_id'], '__local__')

        print(f"  - Jobs routed: {len(results)}")
        print(f"  - All assigned to local worker: True")

        print("\n=== Standalone Mode Validated ===")

    def test_local_worker_excluded_by_tags(self):
        """Test local worker excluded when missing required tags."""
        print("\n=== Testing Tag-Based Exclusion ===\n")

        # Local worker without GPU tag
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        # Remote worker with GPU tag
        remote_worker = {
            'id': 'gpu-worker',
            'name': 'GPU Worker',
            'tags': ['gpu', 'ml'],
            'priority_boost': 0,
            'status': 'online',
            'is_local': False,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(remote_worker)

        # Job requiring GPU
        job = {
            'id': 'gpu-job',
            'playbook': 'train-model.yml',
            'target': 'all',
            'status': 'queued',
            'required_tags': ['gpu'],
            'preferred_tags': []
        }
        self.storage.save_job(job)

        # Route job
        result = self.router.route_job('gpu-job')

        self.assertTrue(result.get('assigned'))
        self.assertEqual(result['worker_id'], 'gpu-worker')

        print(f"  - Job requires: gpu")
        print(f"  - Local worker tags: local")
        print(f"  - Remote worker tags: gpu, ml")
        print(f"  - Routed to: {result['worker_id']} (correct)")

        # Check recommendations show local as ineligible
        recommendations = self.router.get_worker_recommendations('gpu-job')
        local_rec = next(r for r in recommendations if r['is_local'])

        self.assertFalse(local_rec['eligible'])
        print(f"  - Local worker eligible: {local_rec['eligible']}")
        print(f"  - Reason: {local_rec['reason']}")

        print("\n=== Tag-Based Exclusion Validated ===")


if __name__ == '__main__':
    unittest.main(verbosity=2)
