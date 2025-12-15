"""
Feature Validation Test for Job Queue API (Feature 6)

This test validates the complete job submission and lifecycle workflow,
simulating a realistic scenario from job submission to completion.
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


class TestFeatureJobQueueWorkflow(unittest.TestCase):
    """
    Feature validation test for job queue workflow.

    Simulates:
    1. Job submission with various options
    2. Job listing and filtering
    3. Job assignment to worker
    4. Job execution lifecycle (start, complete)
    5. Job cancellation
    6. Multiple jobs with priority handling
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

        # Register test workers
        self.worker_1 = {
            'id': 'worker-gpu-01',
            'name': 'GPU Worker 1',
            'tags': ['gpu', 'high-memory', 'network-a'],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat()
        }
        self.worker_2 = {
            'id': 'worker-cpu-01',
            'name': 'CPU Worker 1',
            'tags': ['cpu', 'network-b'],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'last_checkin': datetime.now().isoformat()
        }
        self.storage.save_worker(self.worker_1)
        self.storage.save_worker(self.worker_2)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_complete_job_lifecycle(self):
        """Test complete job lifecycle from submission to completion."""
        print("\n=== Feature 6: Job Queue Workflow Validation ===\n")

        # =====================================================================
        # Step 1: Submit a job
        # =====================================================================
        print("Step 1: Submit a job...")

        job = {
            'id': 'job-001',
            'playbook': 'deploy-app.yml',
            'target': 'production',
            'required_tags': ['gpu'],
            'preferred_tags': ['high-memory'],
            'priority': 75,
            'job_type': 'normal',
            'extra_vars': {'version': '2.0.0'},
            'status': 'queued',
            'assigned_worker': None,
            'submitted_by': 'user@example.com',
            'submitted_at': datetime.now().isoformat(),
            'assigned_at': None,
            'started_at': None,
            'completed_at': None,
            'log_file': None,
            'exit_code': None,
            'error_message': None
        }

        result = self.storage.save_job(job)
        self.assertTrue(result)
        print(f"  - Job submitted: {job['id']}")
        print(f"  - Playbook: {job['playbook']}")
        print(f"  - Priority: {job['priority']}")

        # =====================================================================
        # Step 2: Verify job is in queue
        # =====================================================================
        print("\nStep 2: Verify job is in queue...")

        pending_jobs = self.storage.get_pending_jobs()
        self.assertEqual(len(pending_jobs), 1)
        self.assertEqual(pending_jobs[0]['id'], 'job-001')
        print(f"  - Pending jobs: {len(pending_jobs)}")

        # =====================================================================
        # Step 3: Assign job to worker
        # =====================================================================
        print("\nStep 3: Assign job to worker...")

        assign_time = datetime.now().isoformat()
        updates = {
            'status': 'assigned',
            'assigned_worker': 'worker-gpu-01',
            'assigned_at': assign_time
        }

        result = self.storage.update_job('job-001', updates)
        self.assertTrue(result)

        job = self.storage.get_job('job-001')
        self.assertEqual(job['status'], 'assigned')
        self.assertEqual(job['assigned_worker'], 'worker-gpu-01')
        print(f"  - Assigned to: {job['assigned_worker']}")

        # =====================================================================
        # Step 4: Worker starts job
        # =====================================================================
        print("\nStep 4: Worker starts job...")

        start_time = datetime.now().isoformat()
        updates = {
            'status': 'running',
            'started_at': start_time,
            'log_file': 'job-001-deploy.log'
        }

        result = self.storage.update_job('job-001', updates)
        self.assertTrue(result)

        job = self.storage.get_job('job-001')
        self.assertEqual(job['status'], 'running')
        self.assertIsNotNone(job['started_at'])
        print(f"  - Status: {job['status']}")
        print(f"  - Log file: {job['log_file']}")

        # =====================================================================
        # Step 5: Worker completes job
        # =====================================================================
        print("\nStep 5: Worker completes job...")

        complete_time = datetime.now().isoformat()
        updates = {
            'status': 'completed',
            'completed_at': complete_time,
            'exit_code': 0
        }

        result = self.storage.update_job('job-001', updates)
        self.assertTrue(result)

        job = self.storage.get_job('job-001')
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['exit_code'], 0)
        print(f"  - Final status: {job['status']}")
        print(f"  - Exit code: {job['exit_code']}")

        print("\n=== Feature 6 Validation Complete ===")
        print("Job queue lifecycle validated successfully!")

    def test_job_priority_ordering(self):
        """Test that jobs are prioritized correctly."""
        print("\n=== Testing Job Priority Ordering ===\n")

        # Submit jobs with different priorities
        jobs = [
            {'id': 'low-priority', 'playbook': 'test.yml', 'priority': 25,
             'status': 'queued', 'submitted_at': '2024-01-01T10:00:00'},
            {'id': 'high-priority', 'playbook': 'test.yml', 'priority': 90,
             'status': 'queued', 'submitted_at': '2024-01-01T10:00:00'},
            {'id': 'medium-priority', 'playbook': 'test.yml', 'priority': 50,
             'status': 'queued', 'submitted_at': '2024-01-01T10:00:00'},
        ]

        for job in jobs:
            self.storage.save_job(job)
            print(f"  - Submitted: {job['id']} (priority {job['priority']})")

        # Get pending jobs
        pending = self.storage.get_pending_jobs()

        self.assertEqual(len(pending), 3)
        self.assertEqual(pending[0]['id'], 'high-priority')
        self.assertEqual(pending[1]['id'], 'medium-priority')
        self.assertEqual(pending[2]['id'], 'low-priority')

        print("\n  Pending job order (highest priority first):")
        for i, job in enumerate(pending):
            print(f"  {i+1}. {job['id']} (priority {job['priority']})")

        print("\n=== Priority Ordering Validated ===")

    def test_job_filtering(self):
        """Test job filtering capabilities."""
        print("\n=== Testing Job Filtering ===\n")

        # Submit various jobs
        jobs = [
            {'id': 'j1', 'playbook': 'deploy.yml', 'status': 'queued', 'assigned_worker': None,
             'submitted_at': '2024-01-01T10:00:00'},
            {'id': 'j2', 'playbook': 'deploy.yml', 'status': 'running', 'assigned_worker': 'worker-gpu-01',
             'submitted_at': '2024-01-01T11:00:00'},
            {'id': 'j3', 'playbook': 'backup.yml', 'status': 'completed', 'assigned_worker': 'worker-cpu-01',
             'submitted_at': '2024-01-01T12:00:00'},
            {'id': 'j4', 'playbook': 'backup.yml', 'status': 'failed', 'assigned_worker': 'worker-gpu-01',
             'submitted_at': '2024-01-01T13:00:00'},
        ]

        for job in jobs:
            self.storage.save_job(job)

        # Filter by status (storage uses direct equality, not list)
        running_jobs = self.storage.get_all_jobs({'status': 'running'})
        self.assertEqual(len(running_jobs), 1)
        print(f"  - Running jobs: {len(running_jobs)}")

        # Filter by playbook
        deploy_jobs = self.storage.get_all_jobs({'playbook': 'deploy.yml'})
        self.assertEqual(len(deploy_jobs), 2)
        print(f"  - Deploy.yml jobs: {len(deploy_jobs)}")

        # Filter by worker
        gpu_worker_jobs = self.storage.get_all_jobs({'assigned_worker': 'worker-gpu-01'})
        self.assertEqual(len(gpu_worker_jobs), 2)
        print(f"  - GPU worker jobs: {len(gpu_worker_jobs)}")

        # Get worker jobs directly
        worker_jobs = self.storage.get_worker_jobs('worker-gpu-01')
        self.assertEqual(len(worker_jobs), 2)
        print(f"  - Worker-gpu-01 assignments: {len(worker_jobs)}")

        print("\n=== Job Filtering Validated ===")

    def test_job_cancellation(self):
        """Test job cancellation scenarios."""
        print("\n=== Testing Job Cancellation ===\n")

        # Submit a job
        job = {
            'id': 'cancel-test',
            'playbook': 'long-running.yml',
            'status': 'queued',
            'submitted_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)
        print(f"  - Submitted job: {job['id']}")

        # Cancel the queued job
        updates = {
            'status': 'cancelled',
            'completed_at': datetime.now().isoformat(),
            'error_message': 'Cancelled by user'
        }
        result = self.storage.update_job('cancel-test', updates)
        self.assertTrue(result)

        job = self.storage.get_job('cancel-test')
        self.assertEqual(job['status'], 'cancelled')
        print(f"  - Status after cancel: {job['status']}")
        print(f"  - Error message: {job['error_message']}")

        # Verify cancelled jobs don't appear in pending
        pending = self.storage.get_pending_jobs()
        self.assertEqual(len(pending), 0)
        print(f"  - Pending jobs (should be 0): {len(pending)}")

        print("\n=== Job Cancellation Validated ===")

    def test_job_failure_handling(self):
        """Test handling of failed jobs."""
        print("\n=== Testing Job Failure Handling ===\n")

        # Submit and run a job that will fail
        job = {
            'id': 'fail-test',
            'playbook': 'failing.yml',
            'status': 'queued',
            'assigned_worker': None,
            'submitted_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        # Assign to worker
        self.storage.update_job('fail-test', {
            'status': 'assigned',
            'assigned_worker': 'worker-cpu-01'
        })

        # Start job
        self.storage.update_job('fail-test', {
            'status': 'running',
            'started_at': datetime.now().isoformat()
        })

        # Job fails
        self.storage.update_job('fail-test', {
            'status': 'failed',
            'exit_code': 2,
            'error_message': 'Task failed: unreachable hosts',
            'completed_at': datetime.now().isoformat()
        })

        job = self.storage.get_job('fail-test')
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['exit_code'], 2)
        print(f"  - Job status: {job['status']}")
        print(f"  - Exit code: {job['exit_code']}")
        print(f"  - Error: {job['error_message']}")

        print("\n=== Job Failure Handling Validated ===")


class TestJobQueueIntegration(unittest.TestCase):
    """Integration tests for job queue with workers."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_multiple_workers_multiple_jobs(self):
        """Test job distribution across multiple workers."""
        print("\n=== Testing Multi-Worker Job Distribution ===\n")

        # Register multiple workers
        workers = [
            {'id': 'w1', 'name': 'Worker 1', 'status': 'online', 'tags': ['gpu']},
            {'id': 'w2', 'name': 'Worker 2', 'status': 'online', 'tags': ['cpu']},
            {'id': 'w3', 'name': 'Worker 3', 'status': 'online', 'tags': ['gpu', 'cpu']},
        ]
        for w in workers:
            w['registered_at'] = datetime.now().isoformat()
            self.storage.save_worker(w)
            print(f"  - Registered worker: {w['name']} (tags: {w['tags']})")

        # Submit multiple jobs
        jobs = [
            {'id': 'j1', 'required_tags': ['gpu'], 'priority': 50},
            {'id': 'j2', 'required_tags': ['cpu'], 'priority': 75},
            {'id': 'j3', 'required_tags': [], 'priority': 25},
            {'id': 'j4', 'required_tags': ['gpu'], 'priority': 90},
        ]

        print("\n  Submitting jobs:")
        for j in jobs:
            job = {
                'id': j['id'],
                'playbook': 'test.yml',
                'status': 'queued',
                'required_tags': j['required_tags'],
                'priority': j['priority'],
                'assigned_worker': None,
                'submitted_at': datetime.now().isoformat()
            }
            self.storage.save_job(job)
            print(f"    - {j['id']}: priority {j['priority']}, requires {j['required_tags']}")

        # Get pending jobs
        pending = self.storage.get_pending_jobs()
        self.assertEqual(len(pending), 4)
        print(f"\n  Total pending jobs: {len(pending)}")
        print("  Priority order:")
        for job in pending:
            print(f"    - {job['id']}: priority {job['priority']}")

        # Simulate job assignment (would be done by router)
        # Assign high-priority GPU job to worker with GPU
        self.storage.update_job('j4', {
            'status': 'assigned',
            'assigned_worker': 'w1'
        })

        # Check remaining pending jobs
        pending = self.storage.get_pending_jobs()
        self.assertEqual(len(pending), 3)
        print(f"\n  After assigning j4: {len(pending)} pending")

        # Check worker assignments
        w1_jobs = self.storage.get_worker_jobs('w1')
        self.assertEqual(len(w1_jobs), 1)
        print(f"  Worker w1 jobs: {len(w1_jobs)}")

        print("\n=== Multi-Worker Distribution Validated ===")


if __name__ == '__main__':
    unittest.main(verbosity=2)
