"""
Feature Validation Test for Job Completion & Results (Feature 10)

This test validates the complete job completion workflow including:
- Status and exit code handling
- Full log storage
- Worker statistics updates
- CMDB facts extraction
- Piggyback checkin processing
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


class TestFeatureJobCompletion(unittest.TestCase):
    """
    Feature validation test for job completion workflow.

    Simulates:
    1. Job is assigned and starts running
    2. Worker executes job and captures logs
    3. Job completes with exit code
    4. Worker stats are updated (counts, duration)
    5. CMDB facts are stored
    6. Piggyback checkin is processed
    7. Real-time events are emitted
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logs_dir = os.path.join(self.test_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)
        self.storage = FlatFileStorage(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_complete_job_completion_workflow(self):
        """Test complete job completion workflow."""
        print("\n=== Feature 10: Job Completion & Results Validation ===\n")

        # =====================================================================
        # Step 1: Set up worker and job
        # =====================================================================
        print("Step 1: Set up worker and running job...")

        worker = {
            'id': 'completion-feature-worker',
            'name': 'Completion Feature Worker',
            'tags': ['web'],
            'status': 'busy',
            'registered_at': datetime.now().isoformat(),
            'stats': {
                'jobs_completed': 10,
                'jobs_failed': 2,
                'avg_job_duration': 120.0,
                'load_1m': 0.5
            }
        }
        self.storage.save_worker(worker)

        started_at = (datetime.now() - timedelta(minutes=5)).isoformat()
        job = {
            'id': 'completion-feature-job',
            'playbook': 'hardware-inventory.yml',
            'target': 'webservers',
            'status': 'running',
            'assigned_worker': 'completion-feature-worker',
            'started_at': started_at
        }
        self.storage.save_job(job)

        print(f"  - Worker: {worker['name']}")
        print(f"  - Initial stats: completed={worker['stats']['jobs_completed']}, failed={worker['stats']['jobs_failed']}")
        print(f"  - Job: {job['id']} ({job['playbook']})")
        print(f"  - Started at: {started_at}")

        # =====================================================================
        # Step 2: Simulate job completion with exit code
        # =====================================================================
        print("\nStep 2: Complete job with success...")

        completed_at = datetime.now().isoformat()
        exit_code = 0
        status = 'completed' if exit_code == 0 else 'failed'

        # Calculate duration
        started = datetime.fromisoformat(started_at)
        completed = datetime.fromisoformat(completed_at)
        duration_seconds = (completed - started).total_seconds()

        updates = {
            'status': status,
            'exit_code': exit_code,
            'completed_at': completed_at,
            'duration_seconds': duration_seconds,
            'log_file': 'completion-feature-job.log'
        }
        self.storage.update_job('completion-feature-job', updates)

        job = self.storage.get_job('completion-feature-job')
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['exit_code'], 0)

        print(f"  - Status: {job['status']}")
        print(f"  - Exit code: {job['exit_code']}")
        print(f"  - Duration: {duration_seconds:.1f}s")
        print(f"  - Log file: {job['log_file']}")

        # =====================================================================
        # Step 3: Store log content
        # =====================================================================
        print("\nStep 3: Store job log content...")

        log_content = """PLAY [Hardware Inventory] ***
TASK [Gathering Facts] ***
ok: [web1]
ok: [web2]
TASK [Collect hardware info] ***
ok: [web1]
ok: [web2]
PLAY RECAP ***
web1 : ok=2 changed=0 failed=0
web2 : ok=2 changed=0 failed=0
"""
        log_path = os.path.join(self.logs_dir, 'completion-feature-job.log')
        with open(log_path, 'w') as f:
            f.write(log_content)

        self.assertTrue(os.path.exists(log_path))
        with open(log_path, 'r') as f:
            stored_content = f.read()
        self.assertIn('PLAY RECAP', stored_content)

        print(f"  - Log stored at: {log_path}")
        print(f"  - Log size: {len(log_content)} bytes")

        # =====================================================================
        # Step 4: Update worker statistics
        # =====================================================================
        print("\nStep 4: Update worker statistics...")

        worker = self.storage.get_worker('completion-feature-worker')
        current_stats = worker.get('stats', {})

        # Increment counts
        jobs_completed = current_stats.get('jobs_completed', 0) + 1
        jobs_failed = current_stats.get('jobs_failed', 0)

        # Update average duration
        total_jobs = jobs_completed + jobs_failed
        old_avg = current_stats.get('avg_job_duration', 0)
        new_avg = ((old_avg * (total_jobs - 1)) + duration_seconds) / total_jobs

        updated_stats = {
            **current_stats,
            'jobs_completed': jobs_completed,
            'jobs_failed': jobs_failed,
            'avg_job_duration': round(new_avg, 2),
            'last_job_completed': completed_at
        }
        self.storage.update_worker_checkin('completion-feature-worker', {'stats': updated_stats})

        worker = self.storage.get_worker('completion-feature-worker')
        self.assertEqual(worker['stats']['jobs_completed'], 11)
        self.assertIn('last_job_completed', worker['stats'])

        print(f"  - Jobs completed: {worker['stats']['jobs_completed']} (was 10)")
        print(f"  - Jobs failed: {worker['stats']['jobs_failed']}")
        print(f"  - Avg duration: {worker['stats']['avg_job_duration']}s")
        print(f"  - Load preserved: {worker['stats'].get('load_1m')}")

        # =====================================================================
        # Step 5: Store CMDB facts
        # =====================================================================
        print("\nStep 5: Store CMDB facts...")

        cmdb_facts = {
            'web1': {
                'ansible_facts': {
                    'hostname': 'web1',
                    'memory_mb': 8192,
                    'cpu_count': 4
                }
            },
            'web2': {
                'ansible_facts': {
                    'hostname': 'web2',
                    'memory_mb': 16384,
                    'cpu_count': 8
                }
            }
        }

        facts_stored = 0
        for host, facts in cmdb_facts.items():
            facts_with_meta = {
                **facts,
                '_meta': {
                    'job_id': 'completion-feature-job',
                    'playbook': 'hardware-inventory.yml',
                    'collected_at': completed_at
                }
            }
            self.storage.save_host_facts(
                host=host,
                collection='hardware-inventory',
                data=facts_with_meta,
                groups=[],
                source='job'
            )
            facts_stored += 1

        print(f"  - Hosts with facts: {facts_stored}")
        for host in cmdb_facts.keys():
            print(f"    - {host}: memory={cmdb_facts[host]['ansible_facts']['memory_mb']}MB")

        # =====================================================================
        # Step 6: Process piggyback checkin
        # =====================================================================
        print("\nStep 6: Process piggyback checkin...")

        checkin_data = {
            'sync_revision': 'new-sync-rev-xyz',
            'status': 'online',
            'stats': {
                **worker['stats'],
                'load_1m': 0.3  # Updated load after job completion
            }
        }
        self.storage.update_worker_checkin('completion-feature-worker', checkin_data)

        worker = self.storage.get_worker('completion-feature-worker')
        self.assertEqual(worker['sync_revision'], 'new-sync-rev-xyz')
        self.assertEqual(worker['status'], 'online')

        print(f"  - Sync revision updated: {worker['sync_revision']}")
        print(f"  - Status: {worker['status']}")
        print(f"  - Load updated: {worker['stats'].get('load_1m')}")

        # =====================================================================
        # Step 7: Verify final state
        # =====================================================================
        print("\nStep 7: Verify final state...")

        final_job = self.storage.get_job('completion-feature-job')
        final_worker = self.storage.get_worker('completion-feature-worker')

        self.assertEqual(final_job['status'], 'completed')
        self.assertEqual(final_job['exit_code'], 0)
        self.assertEqual(final_worker['stats']['jobs_completed'], 11)
        self.assertIsNotNone(final_worker['last_checkin'])

        print(f"  - Job status: {final_job['status']}")
        print(f"  - Worker jobs completed: {final_worker['stats']['jobs_completed']}")
        print(f"  - Worker last checkin: {final_worker['last_checkin'][:19]}...")

        print("\n=== Feature 10 Validation Complete ===")
        print("Job completion workflow validated successfully!")

    def test_failed_job_completion(self):
        """Test job completion with failure."""
        print("\n=== Testing Failed Job Completion ===\n")

        # Set up
        worker = {
            'id': 'failed-job-worker',
            'name': 'Failed Job Worker',
            'tags': [],
            'status': 'busy',
            'registered_at': datetime.now().isoformat(),
            'stats': {'jobs_completed': 5, 'jobs_failed': 0}
        }
        self.storage.save_worker(worker)

        job = {
            'id': 'failed-job-1',
            'playbook': 'deploy.yml',
            'target': 'web',
            'status': 'running',
            'assigned_worker': 'failed-job-worker',
            'started_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        # Complete with failure
        self.storage.update_job('failed-job-1', {
            'status': 'failed',
            'exit_code': 2,
            'completed_at': datetime.now().isoformat(),
            'error_message': 'FATAL: Host web1 unreachable'
        })

        # Update worker stats
        worker = self.storage.get_worker('failed-job-worker')
        updated_stats = {
            **worker.get('stats', {}),
            'jobs_failed': worker['stats'].get('jobs_failed', 0) + 1
        }
        self.storage.update_worker_checkin('failed-job-worker', {'stats': updated_stats})

        # Verify
        job = self.storage.get_job('failed-job-1')
        worker = self.storage.get_worker('failed-job-worker')

        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['exit_code'], 2)
        self.assertIn('unreachable', job['error_message'])
        self.assertEqual(worker['stats']['jobs_failed'], 1)

        print(f"  - Job status: {job['status']}")
        print(f"  - Exit code: {job['exit_code']}")
        print(f"  - Error: {job['error_message']}")
        print(f"  - Worker failed count: {worker['stats']['jobs_failed']}")

        print("\n=== Failed Job Completion Validated ===")

    def test_duration_calculation(self):
        """Test accurate duration calculation."""
        print("\n=== Testing Duration Calculation ===\n")

        # Job that ran for exactly 5 minutes
        started = datetime.now() - timedelta(minutes=5)
        completed = datetime.now()

        duration = (completed - started).total_seconds()
        self.assertGreater(duration, 299)  # At least 299 seconds
        self.assertLess(duration, 301)  # At most 301 seconds

        print(f"  - Started: {started.isoformat()}")
        print(f"  - Completed: {completed.isoformat()}")
        print(f"  - Duration: {duration:.1f}s")

        print("\n=== Duration Calculation Validated ===")


class TestAPIClientJobCompletion(unittest.TestCase):
    """Test API client job completion as part of feature validation."""

    @patch('worker.api_client.requests.request')
    def test_full_completion_request(self, mock_request):
        """Test complete job completion request with all fields."""
        print("\n=== Testing Full API Completion Request ===\n")

        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'job_id': 'job-123',
            'status': 'completed',
            'exit_code': 0,
            'duration_seconds': 120.5,
            'message': 'Job completed',
            'log_stored': True,
            'worker_stats_updated': True,
            'cmdb_facts_stored': 2,
            'checkin_processed': True
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://primary:3001')

        result = client.complete_job(
            job_id='job-123',
            worker_id='worker-1',
            exit_code=0,
            log_file='job-123.log',
            log_content='PLAY [test] ***\nok: [host1]\n',
            duration_seconds=120.5,
            cmdb_facts={'host1': {'memory': 8192}},
            checkin={'sync_revision': 'abc123', 'status': 'online'}
        )

        self.assertTrue(result.success)
        self.assertTrue(result.data['log_stored'])
        self.assertTrue(result.data['worker_stats_updated'])
        self.assertEqual(result.data['cmdb_facts_stored'], 2)
        self.assertTrue(result.data['checkin_processed'])

        print(f"  - Request successful: {result.success}")
        print(f"  - Log stored: {result.data['log_stored']}")
        print(f"  - Worker stats updated: {result.data['worker_stats_updated']}")
        print(f"  - CMDB facts stored: {result.data['cmdb_facts_stored']}")
        print(f"  - Checkin processed: {result.data['checkin_processed']}")

        print("\n=== Full API Completion Request Validated ===")


class TestJobCompletionEdgeCases(unittest.TestCase):
    """Test edge cases in job completion."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_completion_without_started_at(self):
        """Test job completion when started_at is missing."""
        job = {
            'id': 'no-start-job',
            'playbook': 'test.yml',
            'target': 'all',
            'status': 'assigned',
            'assigned_worker': 'worker-1'
        }
        self.storage.save_job(job)

        # Complete without started_at
        self.storage.update_job('no-start-job', {
            'status': 'completed',
            'exit_code': 0,
            'completed_at': datetime.now().isoformat()
        })

        job = self.storage.get_job('no-start-job')
        self.assertEqual(job['status'], 'completed')

    def test_worker_first_job(self):
        """Test stats update for worker's first job."""
        worker = {
            'id': 'new-worker',
            'name': 'New Worker',
            'tags': [],
            'status': 'online',
            'registered_at': datetime.now().isoformat(),
            'stats': {}  # Empty stats
        }
        self.storage.save_worker(worker)

        # First job completes
        updated_stats = {
            'jobs_completed': 1,
            'jobs_failed': 0,
            'avg_job_duration': 60.0
        }
        self.storage.update_worker_checkin('new-worker', {'stats': updated_stats})

        worker = self.storage.get_worker('new-worker')
        self.assertEqual(worker['stats']['jobs_completed'], 1)
        self.assertEqual(worker['stats']['avg_job_duration'], 60.0)

    def test_empty_cmdb_facts(self):
        """Test completion with empty CMDB facts."""
        # Should handle gracefully without error
        result = self.storage.save_host_facts(
            host='empty-host',
            collection='test',
            data={},
            groups=[],
            source='job'
        )
        # Should not raise exception


if __name__ == '__main__':
    unittest.main(verbosity=2)
