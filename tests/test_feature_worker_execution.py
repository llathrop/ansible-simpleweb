"""
Feature Validation Test for Worker Job Execution (Feature 8)

This test validates the worker-side job execution workflow,
simulating a realistic scenario from job assignment to completion.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.executor import JobExecutor, JobPoller, JobResult
from worker.api_client import PrimaryAPIClient, APIResponse


class TestFeatureWorkerJobExecution(unittest.TestCase):
    """
    Feature validation test for worker job execution.

    Simulates:
    1. Worker receives assigned jobs
    2. Executor starts playbook execution
    3. Logs are captured to file
    4. Completion is reported to primary
    5. Multiple jobs run concurrently
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.content_dir = os.path.join(self.test_dir, 'content')
        self.logs_dir = os.path.join(self.test_dir, 'logs')

        # Create directory structure
        os.makedirs(self.content_dir)
        os.makedirs(self.logs_dir)
        os.makedirs(os.path.join(self.content_dir, 'playbooks'))
        os.makedirs(os.path.join(self.content_dir, 'inventory'))

        # Create sample playbook
        with open(os.path.join(self.content_dir, 'playbooks', 'test.yml'), 'w') as f:
            f.write('---\n- name: Test Playbook\n  hosts: all\n')

        # Create sample inventory
        with open(os.path.join(self.content_dir, 'inventory', 'hosts'), 'w') as f:
            f.write('[all]\nlocalhost ansible_connection=local\n')

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_complete_job_execution_workflow(self):
        """Test complete job execution from poll to completion."""
        print("\n=== Feature 8: Worker Job Execution Validation ===\n")

        # =====================================================================
        # Step 1: Set up mock API client
        # =====================================================================
        print("Step 1: Set up worker with mock API...")

        api = Mock(spec=PrimaryAPIClient)
        api.server_url = 'http://primary:3001'
        api.worker_id = 'worker-test-01'

        # Mock API responses
        api.start_job.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'status': 'running'}
        )
        api.complete_job.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'status': 'completed'}
        )

        print(f"  - Worker ID: {api.worker_id}")
        print(f"  - Server URL: {api.server_url}")

        # =====================================================================
        # Step 2: Initialize executor
        # =====================================================================
        print("\nStep 2: Initialize job executor...")

        executor = JobExecutor(
            api_client=api,
            worker_id='worker-test-01',
            content_dir=self.content_dir,
            logs_dir=self.logs_dir
        )

        completed_jobs = []
        def on_complete(result):
            completed_jobs.append(result)

        executor.on_complete(on_complete)

        print(f"  - Content dir: {self.content_dir}")
        print(f"  - Logs dir: {self.logs_dir}")
        print(f"  - Completion callback: registered")

        # =====================================================================
        # Step 3: Build and verify ansible command
        # =====================================================================
        print("\nStep 3: Build ansible command...")

        job = {
            'id': 'job-test-001',
            'playbook': 'test.yml',
            'target': 'localhost',
            'extra_vars': {'test_var': 'test_value'}
        }

        cmd = executor._build_ansible_command(job)

        self.assertIn('ansible-playbook', cmd)
        self.assertIn('-i', cmd)
        self.assertIn('-l', cmd)
        self.assertIn('localhost', cmd)
        self.assertIn('-e', cmd)

        print(f"  - Command: {' '.join(cmd[:5])}...")
        print(f"  - Target limit: {job['target']}")
        print(f"  - Extra vars included: Yes")

        # =====================================================================
        # Step 4: Execute a job (mocked subprocess)
        # =====================================================================
        print("\nStep 4: Execute job with mocked ansible...")

        with patch('subprocess.Popen') as mock_popen:
            # Mock successful execution
            mock_process = Mock()
            mock_process.stdout = iter([
                b'PLAY [Test Playbook] ***\n',
                b'TASK [Gathering Facts] ***\n',
                b'ok: [localhost]\n',
                b'PLAY RECAP ***\n',
                b'localhost : ok=1 changed=0 failed=0\n'
            ])
            mock_process.returncode = 0
            mock_process.wait.return_value = None
            mock_popen.return_value = mock_process

            # Execute synchronously for testing
            executor._run_job(job)

        # Verify API was called
        api.start_job.assert_called_once()
        api.complete_job.assert_called_once()

        # Verify completion callback
        self.assertEqual(len(completed_jobs), 1)
        result = completed_jobs[0]
        self.assertEqual(result.job_id, 'job-test-001')
        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)

        print(f"  - Job ID: {result.job_id}")
        print(f"  - Success: {result.success}")
        print(f"  - Exit code: {result.exit_code}")
        print(f"  - Log file: {result.log_file}")

        # Verify log file was created
        log_path = os.path.join(self.logs_dir, result.log_file)
        self.assertTrue(os.path.exists(log_path))

        with open(log_path, 'r') as f:
            log_content = f.read()

        self.assertIn('PLAY [Test Playbook]', log_content)
        print(f"  - Log file exists: Yes")
        print(f"  - Log contains output: Yes")

        print("\n=== Feature 8 Validation Complete ===")
        print("Worker job execution validated successfully!")

    def test_job_poller_workflow(self):
        """Test job poller integration."""
        print("\n=== Testing Job Poller Workflow ===\n")

        api = Mock(spec=PrimaryAPIClient)
        api.get_assigned_jobs.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'jobs': [
                {'id': 'job-1', 'playbook': 'test.yml', 'target': 'all'},
                {'id': 'job-2', 'playbook': 'test.yml', 'target': 'all'}
            ]}
        )

        executor = Mock()
        executor.active_job_count = 0
        executor.execute_job = Mock()

        poller = JobPoller(
            api_client=api,
            worker_id='worker-01',
            executor=executor,
            max_concurrent=4
        )

        print("  Initial state:")
        print(f"  - Max concurrent jobs: {poller.max_concurrent}")
        print(f"  - Active jobs: {executor.active_job_count}")

        # Poll for jobs
        started = poller.poll_once()

        print(f"\n  After poll:")
        print(f"  - Jobs started: {len(started)}")
        print(f"  - Execute called: {executor.execute_job.call_count} times")

        self.assertEqual(len(started), 2)
        self.assertEqual(executor.execute_job.call_count, 2)

        # Poll again - should skip already processed jobs
        started = poller.poll_once()
        print(f"\n  Second poll (same jobs):")
        print(f"  - Jobs started: {len(started)}")

        self.assertEqual(len(started), 0)

        print("\n=== Job Poller Workflow Validated ===")

    def test_concurrent_job_execution(self):
        """Test multiple jobs running concurrently."""
        print("\n=== Testing Concurrent Job Execution ===\n")

        api = Mock(spec=PrimaryAPIClient)
        api.start_job.return_value = APIResponse(success=True, status_code=200)
        api.complete_job.return_value = APIResponse(success=True, status_code=200)

        executor = JobExecutor(
            api_client=api,
            worker_id='worker-01',
            content_dir=self.content_dir,
            logs_dir=self.logs_dir
        )

        jobs = [
            {'id': 'job-1', 'playbook': 'test.yml', 'target': 'all'},
            {'id': 'job-2', 'playbook': 'test.yml', 'target': 'all'},
        ]

        print(f"  Submitting {len(jobs)} jobs for async execution...")

        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.stdout = iter([b'ok\n'])
            mock_process.returncode = 0
            mock_process.wait.return_value = None
            mock_popen.return_value = mock_process

            # Start jobs async
            for job in jobs:
                executor.execute_job(job, async_exec=True)

            # Give threads time to start
            import time
            time.sleep(0.1)

        print(f"  Active jobs during execution: {executor.active_job_count}")

        # Wait for completion
        executor.wait_for_jobs(timeout=5)

        print(f"  Active jobs after wait: {executor.active_job_count}")
        self.assertEqual(executor.active_job_count, 0)

        print("\n=== Concurrent Execution Validated ===")

    def test_job_failure_handling(self):
        """Test handling of failed job execution."""
        print("\n=== Testing Job Failure Handling ===\n")

        api = Mock(spec=PrimaryAPIClient)
        api.start_job.return_value = APIResponse(success=True, status_code=200)
        api.complete_job.return_value = APIResponse(success=True, status_code=200)

        executor = JobExecutor(
            api_client=api,
            worker_id='worker-01',
            content_dir=self.content_dir,
            logs_dir=self.logs_dir
        )

        completed_results = []
        executor.on_complete(lambda r: completed_results.append(r))

        job = {'id': 'job-fail', 'playbook': 'test.yml', 'target': 'all'}

        with patch('subprocess.Popen') as mock_popen:
            # Simulate failed execution
            mock_process = Mock()
            mock_process.stdout = iter([
                b'PLAY [test] ***\n',
                b'fatal: [host1]: FAILED!\n'
            ])
            mock_process.returncode = 2  # Ansible failure code
            mock_process.wait.return_value = None
            mock_popen.return_value = mock_process

            executor._run_job(job)

        self.assertEqual(len(completed_results), 1)
        result = completed_results[0]

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 2)

        print(f"  - Job ID: {result.job_id}")
        print(f"  - Success: {result.success}")
        print(f"  - Exit code: {result.exit_code}")

        # Verify complete_job was called with failure info
        complete_call = api.complete_job.call_args
        self.assertEqual(complete_call[0][2], 2)  # exit_code

        print("\n=== Job Failure Handling Validated ===")


class TestWorkerJobExecutionEdgeCases(unittest.TestCase):
    """Test edge cases in job execution."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.content_dir = os.path.join(self.test_dir, 'content')
        self.logs_dir = os.path.join(self.test_dir, 'logs')

        os.makedirs(self.content_dir)
        os.makedirs(self.logs_dir)
        os.makedirs(os.path.join(self.content_dir, 'playbooks'))
        os.makedirs(os.path.join(self.content_dir, 'inventory'))

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_api_failure_on_start(self):
        """Test handling when API fails on job start notification."""
        api = Mock(spec=PrimaryAPIClient)
        api.start_job.return_value = APIResponse(
            success=False,
            status_code=500,
            error='Server error'
        )
        api.complete_job.return_value = APIResponse(success=True, status_code=200)

        executor = JobExecutor(
            api_client=api,
            worker_id='worker-01',
            content_dir=self.content_dir,
            logs_dir=self.logs_dir
        )

        job = {'id': 'job-1', 'playbook': 'test.yml', 'target': 'all'}

        with patch('subprocess.Popen') as mock_popen:
            mock_process = Mock()
            mock_process.stdout = iter([b'ok\n'])
            mock_process.returncode = 0
            mock_process.wait.return_value = None
            mock_popen.return_value = mock_process

            # Should still execute despite API failure
            executor._run_job(job)

        # Complete should still be called
        api.complete_job.assert_called_once()

    def test_capacity_limit_respected(self):
        """Test that poller respects capacity limits."""
        api = Mock(spec=PrimaryAPIClient)
        executor = Mock()
        executor.active_job_count = 2  # At capacity

        poller = JobPoller(
            api_client=api,
            worker_id='worker-01',
            executor=executor,
            max_concurrent=2
        )

        started = poller.poll_once()

        self.assertEqual(len(started), 0)
        api.get_assigned_jobs.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
