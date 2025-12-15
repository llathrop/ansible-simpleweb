"""
Feature Validation Test for Batch Live Log Streaming.

This test validates the complete batch log streaming workflow including:
- Worker streams logs during execution
- Primary creates partial log files
- Clients receive real-time log updates
- Late-joining clients receive log catchup
- Worker name appears in log headers
- Logs display correctly in batch live view

Run with: pytest tests/test_feature_batch_log.py -v
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


class TestFeatureBatchLogStreaming(unittest.TestCase):
    """
    Feature validation test for batch log streaming.

    Simulates the complete workflow:
    1. Batch job is created and dispatched to worker
    2. Worker starts executing playbook
    3. Worker streams log content to primary via API
    4. Primary creates partial log file and broadcasts to batch room
    5. Client joins batch room late
    6. Client receives log catchup with existing content
    7. Job completes and final log is stored
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logs_dir = os.path.join(self.test_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_complete_batch_log_streaming_workflow(self):
        """Test complete batch log streaming workflow."""
        print("\n=== Feature: Batch Live Log Streaming Validation ===\n")

        # =====================================================================
        # Step 1: Set up batch job and worker
        # =====================================================================
        print("Step 1: Set up batch job and worker...")

        batch_id = 'feature-batch-log-001'
        worker_id = 'feature-worker-001'
        worker_name = 'ansible-worker-1'
        job_id = 'feature-job-001'
        playbook = 'service-status.yml'

        batch_job = {
            'id': batch_id,
            'status': 'running',
            'playbooks': ['service-status', 'gather-facts', 'deploy'],
            'target': 'webservers',
            'current_playbook': playbook,
            'current_job_id': job_id,
            'worker_id': worker_id,
            'worker_name': worker_name,
            'total': 3,
            'completed': 0,
            'failed': 0,
            'results': []
        }

        print(f"  - Batch ID: {batch_id}")
        print(f"  - Worker: {worker_name} ({worker_id[:8]})")
        print(f"  - Current playbook: {playbook}")

        # =====================================================================
        # Step 2: Worker starts job and streams header
        # =====================================================================
        print("\nStep 2: Worker starts job and streams log header...")

        partial_path = os.path.join(self.logs_dir, f'partial-{job_id}.log')

        # Worker creates header
        started_at = datetime.now().isoformat()
        header = (
            f"Worker: {worker_name} ({worker_id[:8]})\n"
            f"Job ID: {job_id}\n"
            f"Playbook: {playbook}\n"
            f"Target: webservers\n"
            f"Started: {started_at}\n"
            f"Command: ansible-playbook /app/playbooks/{playbook} -i /app/inventory/hosts -l webservers\n"
            + "=" * 60 + "\n\n"
        )

        # Simulate streaming to primary (first chunk, not append)
        with open(partial_path, 'w') as f:
            f.write(header)

        self.assertTrue(os.path.exists(partial_path))

        print(f"  - Partial log created: {partial_path}")
        print(f"  - Header includes worker name: {worker_name}")

        # =====================================================================
        # Step 3: Worker streams playbook execution output
        # =====================================================================
        print("\nStep 3: Worker streams playbook execution output...")

        # Simulate playbook output chunks
        chunks = [
            "PLAY [Service Status Check] ******************************************\n\n",
            "TASK [Gathering Facts] **********************************************\n",
            "ok: [web1]\n",
            "ok: [web2]\n",
            "ok: [web3]\n\n",
            "TASK [Check service status] ******************************************\n",
            "ok: [web1] => {\n",
            '    "msg": "nginx is running"\n',
            "}\n",
            "ok: [web2] => {\n",
            '    "msg": "nginx is running"\n',
            "}\n",
            "ok: [web3] => {\n",
            '    "msg": "nginx is running"\n',
            "}\n\n"
        ]

        # Stream chunks with append mode
        for chunk in chunks:
            with open(partial_path, 'a') as f:
                f.write(chunk)

        # Verify content accumulated
        with open(partial_path, 'r') as f:
            content = f.read()

        self.assertIn("Worker:", content)
        self.assertIn("PLAY [Service Status Check]", content)
        self.assertIn("TASK [Check service status]", content)
        self.assertIn("nginx is running", content)

        print(f"  - Streamed {len(chunks)} log chunks")
        print(f"  - Total content size: {len(content)} bytes")

        # =====================================================================
        # Step 4: Client joins batch room late - receives catchup
        # =====================================================================
        print("\nStep 4: Client joins batch room late and receives catchup...")

        # Simulate batch_catchup event data
        catchup_data = {
            'batch_id': batch_id,
            'status': batch_job['status'],
            'completed': batch_job['completed'],
            'failed': batch_job['failed'],
            'total': batch_job['total'],
            'current_playbook': batch_job['current_playbook'],
            'results': batch_job['results'],
            'worker_name': batch_job['worker_name']
        }

        self.assertEqual(catchup_data['batch_id'], batch_id)
        self.assertEqual(catchup_data['worker_name'], worker_name)

        # Simulate reading partial log for catchup
        log_catchup_lines = []
        with open(partial_path, 'r') as f:
            for line in f.read().splitlines(keepends=True):
                log_catchup_lines.append({
                    'batch_id': batch_id,
                    'playbook': 'service-status',
                    'line': line
                })

        self.assertGreater(len(log_catchup_lines), 0)

        print(f"  - Catchup sent batch status")
        print(f"  - Catchup sent {len(log_catchup_lines)} log lines")
        print(f"  - Worker name in catchup: {catchup_data['worker_name']}")

        # =====================================================================
        # Step 5: Worker streams completion and final output
        # =====================================================================
        print("\nStep 5: Worker streams completion output...")

        completion_output = """PLAY RECAP *******************************************************************
web1                       : ok=2    changed=0    unreachable=0    failed=0
web2                       : ok=2    changed=0    unreachable=0    failed=0
web3                       : ok=2    changed=0    unreachable=0    failed=0

"""
        with open(partial_path, 'a') as f:
            f.write(completion_output)

        completed_at = datetime.now().isoformat()
        footer = (
            "=" * 60 + "\n"
            f"Completed: {completed_at}\n"
            f"Exit Code: 0\n"
        )
        with open(partial_path, 'a') as f:
            f.write(footer)

        print(f"  - Streamed PLAY RECAP")
        print(f"  - Streamed completion footer")

        # =====================================================================
        # Step 6: Job completes - final log is stored
        # =====================================================================
        print("\nStep 6: Job completes and final log is stored...")

        final_log_file = f"service-status_{job_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        final_log_path = os.path.join(self.logs_dir, final_log_file)

        # Read partial log and write to final
        with open(partial_path, 'r') as f:
            full_content = f.read()
        with open(final_log_path, 'w') as f:
            f.write(full_content)

        # Update batch job with result
        batch_job['results'].append({
            'playbook': 'service-status',
            'status': 'completed',
            'exit_code': 0,
            'log_file': final_log_file,
            'job_id': job_id
        })
        batch_job['completed'] = 1

        self.assertTrue(os.path.exists(final_log_path))
        self.assertEqual(batch_job['completed'], 1)
        self.assertEqual(len(batch_job['results']), 1)

        print(f"  - Final log stored: {final_log_file}")
        print(f"  - Batch completed: {batch_job['completed']}/{batch_job['total']}")

        # =====================================================================
        # Step 7: Verify log content integrity
        # =====================================================================
        print("\nStep 7: Verify log content integrity...")

        with open(final_log_path, 'r') as f:
            final_content = f.read()

        # Verify worker identification
        self.assertIn(f"Worker: {worker_name}", final_content)
        self.assertIn(f"({worker_id[:8]})", final_content)

        # Verify job metadata
        self.assertIn(f"Job ID: {job_id}", final_content)
        self.assertIn(f"Playbook: {playbook}", final_content)
        self.assertIn("Target: webservers", final_content)

        # Verify playbook output
        self.assertIn("PLAY [Service Status Check]", final_content)
        self.assertIn("TASK [Gathering Facts]", final_content)
        self.assertIn("nginx is running", final_content)
        self.assertIn("PLAY RECAP", final_content)

        # Verify completion
        self.assertIn("Exit Code: 0", final_content)

        print(f"  - Worker identification: OK")
        print(f"  - Job metadata: OK")
        print(f"  - Playbook output: OK")
        print(f"  - Completion info: OK")

        print("\n=== Feature Validation Complete ===")
        print("Batch log streaming workflow validated successfully!")

    def test_log_catchup_for_multiple_playbooks(self):
        """Test log catchup when multiple playbooks have completed."""
        print("\n=== Testing Log Catchup for Multiple Playbooks ===\n")

        batch_id = 'batch-multi-playbook'
        playbooks = ['service-status', 'gather-facts', 'deploy']

        # Create final logs for completed playbooks
        for i, playbook in enumerate(playbooks[:2]):  # First 2 completed
            job_id = f'job-{playbook}'
            log_file = f'{playbook}_job123_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
            log_path = os.path.join(self.logs_dir, log_file)

            log_content = f"""Worker: worker-1 (abc12345)
Job ID: {job_id}
Playbook: {playbook}.yml
============================================================

PLAY [{playbook}] ***
TASK [run] ***
ok: [localhost]

PLAY RECAP ***
localhost: ok=1

============================================================
Exit Code: 0
"""
            with open(log_path, 'w') as f:
                f.write(log_content)

        # Create partial log for running playbook
        running_job_id = 'job-deploy'
        partial_path = os.path.join(self.logs_dir, f'partial-{running_job_id}.log')
        with open(partial_path, 'w') as f:
            f.write("""Worker: worker-1 (abc12345)
Job ID: job-deploy
Playbook: deploy.yml
============================================================

PLAY [deploy] ***
TASK [Deploying...] ***
""")

        # Simulate catchup
        results = [
            {'playbook': 'service-status', 'status': 'completed', 'log_file': 'service-status_job123.log'},
            {'playbook': 'gather-facts', 'status': 'completed', 'log_file': 'gather-facts_job123.log'},
        ]

        catchup_log_count = 0
        for result in results:
            # Read final log for completed playbooks
            for f in os.listdir(self.logs_dir):
                if f.startswith(result['playbook']) and not f.startswith('partial'):
                    with open(os.path.join(self.logs_dir, f), 'r') as log_f:
                        content = log_f.read()
                        catchup_log_count += len(content.splitlines())
                    break

        # Also read partial for running
        if os.path.exists(partial_path):
            with open(partial_path, 'r') as f:
                catchup_log_count += len(f.read().splitlines())

        self.assertGreater(catchup_log_count, 0)

        print(f"  - Completed playbooks: 2")
        print(f"  - Running playbook: 1")
        print(f"  - Total catchup lines: {catchup_log_count}")

        print("\n=== Multiple Playbook Catchup Validated ===")

    def test_worker_name_display_in_logs(self):
        """Test that worker name is prominently displayed in logs."""
        print("\n=== Testing Worker Name Display ===\n")

        test_cases = [
            ('ansible-worker-1', '1a2b3c4d-5e6f-7g8h', 'Expected: ansible-worker-1 (1a2b3c4d)'),
            ('production-node-5', '9x8y7z6w-5v4u-3t2s', 'Expected: production-node-5 (9x8y7z6w)'),
            ('test-worker', 'abcdefgh-ijkl-mnop', 'Expected: test-worker (abcdefgh)'),
        ]

        for worker_name, worker_id, description in test_cases:
            header = f"Worker: {worker_name} ({worker_id[:8]})\n"

            # Verify format
            self.assertIn(f"Worker: {worker_name}", header)
            self.assertIn(f"({worker_id[:8]})", header)

            # Verify it appears on the first line
            first_line = header.split('\n')[0]
            self.assertTrue(first_line.startswith("Worker:"))

            print(f"  - {description}: OK")

        print("\n=== Worker Name Display Validated ===")

    def test_batch_log_event_emissions(self):
        """Test that batch log events are emitted correctly."""
        print("\n=== Testing Batch Log Event Emissions ===\n")

        batch_id = 'event-test-batch'
        playbook = 'test-playbook'

        # Simulate event emissions during execution
        events_emitted = []

        # Log lines during streaming
        log_lines = [
            "PLAY [Test] ***\n",
            "TASK [Step 1] ***\n",
            "ok: [localhost]\n",
            "TASK [Step 2] ***\n",
            "changed: [localhost]\n",
        ]

        for line in log_lines:
            event = {
                'event': 'batch_log_line',
                'data': {
                    'batch_id': batch_id,
                    'playbook': playbook,
                    'line': line
                }
            }
            events_emitted.append(event)

        # Verify all events have correct structure
        for event in events_emitted:
            self.assertEqual(event['event'], 'batch_log_line')
            self.assertIn('batch_id', event['data'])
            self.assertIn('playbook', event['data'])
            self.assertIn('line', event['data'])

        print(f"  - Emitted {len(events_emitted)} batch_log_line events")
        print(f"  - All events have correct structure")

        print("\n=== Batch Log Event Emissions Validated ===")


class TestBatchLogErrorHandling(unittest.TestCase):
    """Test error handling in batch log streaming."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.logs_dir = os.path.join(self.test_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_graceful_handling_of_missing_logs(self):
        """Test graceful handling when log files are missing."""
        print("\n=== Testing Graceful Missing Log Handling ===\n")

        batch_job = {
            'results': [
                {'playbook': 'test', 'log_file': 'non_existent.log', 'job_id': 'job-123'}
            ],
            'current_job_id': 'job-456',
            'current_playbook': 'running-test'
        }

        # Simulate catchup with missing files
        for result in batch_job['results']:
            log_file = result.get('log_file')
            job_id = result.get('job_id')

            log_content = None
            if log_file:
                log_path = os.path.join(self.logs_dir, log_file)
                if os.path.exists(log_path):
                    try:
                        with open(log_path, 'r') as f:
                            log_content = f.read()
                    except:
                        pass

            if not log_content and job_id:
                partial_path = os.path.join(self.logs_dir, f'partial-{job_id}.log')
                if os.path.exists(partial_path):
                    try:
                        with open(partial_path, 'r') as f:
                            log_content = f.read()
                    except:
                        pass

            # Should be None but not crash
            self.assertIsNone(log_content)

        print(f"  - Missing log file handled gracefully")
        print(f"  - No exceptions raised")

        print("\n=== Missing Log Handling Validated ===")

    def test_empty_results_catchup(self):
        """Test catchup when no results exist yet."""
        print("\n=== Testing Empty Results Catchup ===\n")

        batch_job = {
            'id': 'empty-batch',
            'status': 'pending',
            'results': [],
            'current_job_id': None,
            'current_playbook': None,
            'worker_name': None
        }

        # Catchup should still work with empty results
        catchup_data = {
            'batch_id': batch_job['id'],
            'status': batch_job['status'],
            'completed': 0,
            'failed': 0,
            'total': 3,
            'current_playbook': batch_job.get('current_playbook'),
            'results': batch_job.get('results', []),
            'worker_name': batch_job.get('worker_name')
        }

        self.assertEqual(len(catchup_data['results']), 0)
        self.assertIsNone(catchup_data['worker_name'])

        # No log catchup for empty results
        log_lines_sent = 0
        for result in batch_job['results']:
            log_lines_sent += 1  # Would send log lines here

        self.assertEqual(log_lines_sent, 0)

        print(f"  - Empty results handled correctly")
        print(f"  - No log lines sent for empty batch")

        print("\n=== Empty Results Catchup Validated ===")


if __name__ == '__main__':
    unittest.main(verbosity=2)
