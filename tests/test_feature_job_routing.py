"""
Feature Validation Test for Job Priority & Assignment (Feature 7)

This test validates the complete job routing workflow,
simulating realistic scenarios for automatic job assignment.
"""

import os
import sys
import tempfile
import shutil
import unittest
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.storage.flatfile import FlatFileStorage
from web.job_router import JobRouter


class TestFeatureJobRouting(unittest.TestCase):
    """
    Feature validation test for job routing workflow.

    Simulates:
    1. Multi-worker cluster setup
    2. Job submission with tag requirements
    3. Automatic routing based on tags and load
    4. Priority-based job ordering
    5. Worker capacity management
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)
        self.router = JobRouter(self.storage)

        # Register diverse workers
        workers = [
            {
                'id': 'gpu-worker-1',
                'name': 'GPU Worker 1 (High Memory)',
                'tags': ['gpu', 'high-memory', 'network-a'],
                'status': 'online',
                'max_concurrent_jobs': 4,
                'system_stats': {
                    'cpu_percent': 20,
                    'memory_percent': 30,
                    'load_1m': 0.5
                },
                'registered_at': datetime.now().isoformat(),
                'last_checkin': datetime.now().isoformat()
            },
            {
                'id': 'gpu-worker-2',
                'name': 'GPU Worker 2 (Standard)',
                'tags': ['gpu', 'network-a'],
                'status': 'online',
                'max_concurrent_jobs': 2,
                'system_stats': {
                    'cpu_percent': 60,
                    'memory_percent': 70,
                    'load_1m': 1.5
                },
                'registered_at': datetime.now().isoformat(),
                'last_checkin': datetime.now().isoformat()
            },
            {
                'id': 'cpu-worker-1',
                'name': 'CPU Worker 1 (Network B)',
                'tags': ['cpu', 'network-b'],
                'status': 'online',
                'max_concurrent_jobs': 4,
                'system_stats': {
                    'cpu_percent': 10,
                    'memory_percent': 20,
                    'load_1m': 0.2
                },
                'registered_at': datetime.now().isoformat(),
                'last_checkin': datetime.now().isoformat()
            },
            {
                'id': 'batch-worker',
                'name': 'Batch Processing Worker',
                'tags': ['cpu', 'batch', 'long-running'],
                'status': 'online',
                'max_concurrent_jobs': 1,
                'system_stats': {
                    'cpu_percent': 5,
                    'memory_percent': 10,
                    'load_1m': 0.1
                },
                'registered_at': datetime.now().isoformat(),
                'last_checkin': datetime.now().isoformat()
            }
        ]

        for worker in workers:
            self.storage.save_worker(worker)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_complete_routing_workflow(self):
        """Test complete job routing workflow."""
        print("\n=== Feature 7: Job Routing Validation ===\n")

        # =====================================================================
        # Step 1: Submit jobs with various requirements
        # =====================================================================
        print("Step 1: Submit jobs with various requirements...")

        jobs = [
            {
                'id': 'job-gpu-required',
                'playbook': 'ml-training.yml',
                'status': 'queued',
                'required_tags': ['gpu'],
                'preferred_tags': ['high-memory'],
                'priority': 75,
                'job_type': 'normal',
                'submitted_at': datetime.now().isoformat()
            },
            {
                'id': 'job-any-worker',
                'playbook': 'backup.yml',
                'status': 'queued',
                'required_tags': [],
                'preferred_tags': [],
                'priority': 25,
                'job_type': 'normal',
                'submitted_at': datetime.now().isoformat()
            },
            {
                'id': 'job-long-running',
                'playbook': 'data-migration.yml',
                'status': 'queued',
                'required_tags': [],
                'preferred_tags': ['long-running'],
                'priority': 50,
                'job_type': 'long_running',
                'submitted_at': datetime.now().isoformat()
            },
            {
                'id': 'job-network-b',
                'playbook': 'deploy.yml',
                'status': 'queued',
                'required_tags': ['network-b'],
                'preferred_tags': [],
                'priority': 90,  # Highest priority
                'job_type': 'normal',
                'submitted_at': datetime.now().isoformat()
            }
        ]

        for job in jobs:
            self.storage.save_job(job)
            print(f"  - Submitted: {job['id']} (priority {job['priority']}, requires {job['required_tags']})")

        # =====================================================================
        # Step 2: Get recommendations for GPU job
        # =====================================================================
        print("\nStep 2: Get worker recommendations for GPU job...")

        recommendations = self.router.get_worker_recommendations('job-gpu-required')

        print(f"  Workers evaluated: {len(recommendations)}")
        for rec in recommendations:
            status = "ELIGIBLE" if rec['eligible'] else "INELIGIBLE"
            print(f"  - {rec['worker_name']}: {status} (score: {rec['scores']['total']})")
            if not rec['eligible']:
                print(f"      Reason: {rec['reason']}")

        # Verify GPU workers are eligible
        eligible = [r for r in recommendations if r['eligible']]
        self.assertEqual(len(eligible), 2)  # gpu-worker-1 and gpu-worker-2

        # gpu-worker-1 should be best (lower load + high-memory tag)
        self.assertEqual(recommendations[0]['worker_id'], 'gpu-worker-1')

        # =====================================================================
        # Step 3: Route pending jobs automatically
        # =====================================================================
        print("\nStep 3: Route pending jobs automatically...")

        results = self.router.route_pending_jobs(limit=10)

        print(f"  Routing results: {len(results)} jobs processed")
        for result in results:
            if result.get('assigned'):
                print(f"  - {result['job_id']} -> {result['worker_name']}")
                print(f"      Score: {result['score']['total']} (tag: {result['score']['tag']}, load: {result['score']['load']})")
            else:
                print(f"  - {result['job_id']}: Not assigned - {result.get('reason', 'Unknown')}")

        # Verify assignments
        assigned = [r for r in results if r.get('assigned')]
        self.assertEqual(len(assigned), 4)  # All jobs should be assigned

        # Verify high priority job (network-b) was routed first
        self.assertEqual(results[0]['job_id'], 'job-network-b')

        # =====================================================================
        # Step 4: Verify job states
        # =====================================================================
        print("\nStep 4: Verify job assignments...")

        for result in results:
            if result.get('assigned'):
                job = self.storage.get_job(result['job_id'])
                self.assertEqual(job['status'], 'assigned')
                self.assertEqual(job['assigned_worker'], result['worker_id'])
                print(f"  - {result['job_id']}: status={job['status']}, worker={job['assigned_worker']}")

        print("\n=== Feature 7 Validation Complete ===")
        print("Job routing workflow validated successfully!")

    def test_tag_based_routing(self):
        """Test routing based on tag requirements."""
        print("\n=== Testing Tag-Based Routing ===\n")

        # Submit job requiring GPU
        self.storage.save_job({
            'id': 'gpu-job',
            'playbook': 'test.yml',
            'status': 'queued',
            'required_tags': ['gpu'],
            'preferred_tags': [],
            'priority': 50,
            'job_type': 'normal'
        })

        result = self.router.route_job('gpu-job')

        self.assertTrue(result['assigned'])
        self.assertIn(result['worker_id'], ['gpu-worker-1', 'gpu-worker-2'])
        print(f"  GPU job routed to: {result['worker_name']}")

        # Submit job requiring non-existent tag
        self.storage.save_job({
            'id': 'special-job',
            'playbook': 'test.yml',
            'status': 'queued',
            'required_tags': ['special-hardware'],
            'preferred_tags': [],
            'priority': 50,
            'job_type': 'normal'
        })

        result = self.router.route_job('special-job')

        self.assertFalse(result.get('assigned'))
        print(f"  Special job: {result.get('reason')}")

        print("\n=== Tag-Based Routing Validated ===")

    def test_load_based_routing(self):
        """Test that lower-load workers are preferred."""
        print("\n=== Testing Load-Based Routing ===\n")

        # Submit job with no tag requirements
        self.storage.save_job({
            'id': 'any-job',
            'playbook': 'test.yml',
            'status': 'queued',
            'required_tags': [],
            'preferred_tags': [],
            'priority': 50,
            'job_type': 'normal'
        })

        result = self.router.route_job('any-job')

        self.assertTrue(result['assigned'])
        print(f"  Job routed to: {result['worker_name']}")
        print(f"  Load score: {result['score']['load']}")

        # batch-worker or cpu-worker-1 should be selected (lowest load)
        self.assertIn(result['worker_id'], ['batch-worker', 'cpu-worker-1'])

        print("\n=== Load-Based Routing Validated ===")

    def test_worker_capacity_limits(self):
        """Test that workers at capacity are not assigned new jobs."""
        print("\n=== Testing Worker Capacity Limits ===\n")

        # batch-worker has max_concurrent_jobs=1
        # Assign a job to it
        self.storage.save_job({
            'id': 'batch-job-1',
            'playbook': 'test.yml',
            'status': 'running',
            'assigned_worker': 'batch-worker',
            'required_tags': [],
            'preferred_tags': ['long-running'],
            'priority': 50,
            'job_type': 'long_running'
        })

        # Now try to route another long-running job
        self.storage.save_job({
            'id': 'batch-job-2',
            'playbook': 'test2.yml',
            'status': 'queued',
            'required_tags': [],
            'preferred_tags': ['long-running'],
            'priority': 50,
            'job_type': 'long_running'
        })

        result = self.router.route_job('batch-job-2')

        # Should be assigned, but NOT to batch-worker (at capacity)
        self.assertTrue(result['assigned'])
        self.assertNotEqual(result['worker_id'], 'batch-worker')
        print(f"  Job routed to: {result['worker_name']} (batch-worker at capacity)")

        print("\n=== Capacity Limits Validated ===")

    def test_priority_ordering(self):
        """Test that higher priority jobs are routed first."""
        print("\n=== Testing Priority Ordering ===\n")

        # Submit jobs with different priorities
        jobs = [
            {'id': 'low-pri', 'priority': 25},
            {'id': 'high-pri', 'priority': 90},
            {'id': 'med-pri', 'priority': 50},
        ]

        for job_data in jobs:
            self.storage.save_job({
                'id': job_data['id'],
                'playbook': 'test.yml',
                'status': 'queued',
                'required_tags': [],
                'preferred_tags': [],
                'priority': job_data['priority'],
                'job_type': 'normal',
                'submitted_at': datetime.now().isoformat()
            })
            print(f"  Submitted: {job_data['id']} (priority {job_data['priority']})")

        results = self.router.route_pending_jobs()

        print("\n  Routing order:")
        for i, result in enumerate(results):
            print(f"  {i+1}. {result['job_id']}")

        # Verify high priority was routed first
        self.assertEqual(results[0]['job_id'], 'high-pri')
        self.assertEqual(results[1]['job_id'], 'med-pri')
        self.assertEqual(results[2]['job_id'], 'low-pri')

        print("\n=== Priority Ordering Validated ===")


class TestJobRoutingEdgeCases(unittest.TestCase):
    """Test edge cases in job routing."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)
        self.router = JobRouter(self.storage)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_no_workers_available(self):
        """Test routing when no workers are registered."""
        self.storage.save_job({
            'id': 'j1',
            'playbook': 'test.yml',
            'status': 'queued',
            'required_tags': [],
            'preferred_tags': [],
            'priority': 50,
            'job_type': 'normal'
        })

        result = self.router.route_job('j1')

        self.assertFalse(result.get('assigned'))
        self.assertIn('No eligible', result.get('reason', ''))

    def test_all_workers_offline(self):
        """Test routing when all workers are offline."""
        self.storage.save_worker({
            'id': 'w1',
            'name': 'Offline Worker',
            'tags': [],
            'status': 'offline',
            'max_concurrent_jobs': 2
        })

        self.storage.save_job({
            'id': 'j1',
            'playbook': 'test.yml',
            'status': 'queued',
            'required_tags': [],
            'preferred_tags': [],
            'priority': 50,
            'job_type': 'normal'
        })

        result = self.router.route_job('j1')

        self.assertFalse(result.get('assigned'))

    def test_all_workers_at_capacity(self):
        """Test routing when all workers are at capacity."""
        self.storage.save_worker({
            'id': 'w1',
            'name': 'Full Worker',
            'tags': [],
            'status': 'busy',
            'max_concurrent_jobs': 1
        })

        self.storage.save_job({
            'id': 'existing',
            'playbook': 'test.yml',
            'status': 'running',
            'assigned_worker': 'w1'
        })

        self.storage.save_job({
            'id': 'new-job',
            'playbook': 'test.yml',
            'status': 'queued',
            'required_tags': [],
            'preferred_tags': [],
            'priority': 50,
            'job_type': 'normal'
        })

        result = self.router.route_job('new-job')

        self.assertFalse(result.get('assigned'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
