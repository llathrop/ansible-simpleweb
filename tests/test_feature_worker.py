"""
Feature Validation Test for Worker Client Service (Feature 5)

This test validates the worker service components work together correctly,
simulating a realistic worker lifecycle without requiring a real server.
"""

import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.config import WorkerConfig
from worker.api_client import PrimaryAPIClient, APIResponse
from worker.sync import ContentSync, SyncResult
from worker.service import WorkerService, WorkerState


class TestFeatureWorkerLifecycle(unittest.TestCase):
    """
    Feature validation test for worker lifecycle.

    Simulates:
    1. Worker configuration loading
    2. Connection to primary server
    3. Worker registration
    4. Initial content sync
    5. Periodic operations (checkin, sync check)
    6. State transitions
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()

        # Create content directories
        for dir_name in ['playbooks', 'inventory', 'library', 'callback_plugins', 'logs']:
            os.makedirs(os.path.join(self.test_dir, dir_name))

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _mock_api_responses(self):
        """Create mock API client with realistic responses."""
        api = Mock(spec=PrimaryAPIClient)
        api.server_url = 'http://primary:3001'
        api.worker_id = None

        # Registration response
        def register_side_effect(name, tags, token):
            if token == 'valid-token':
                api.worker_id = 'worker-uuid-123'
                return APIResponse(
                    success=True,
                    status_code=201,
                    data={
                        'worker_id': 'worker-uuid-123',
                        'checkin_interval': 600,
                        'sync_url': 'http://primary:3001/api/sync'
                    }
                )
            return APIResponse(
                success=False,
                status_code=401,
                error='Invalid token'
            )

        api.register.side_effect = register_side_effect

        # Health check
        api.health_check.return_value = True

        # Sync revision
        api.get_sync_revision.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'revision': 'abc123def456', 'short_revision': 'abc123d'}
        )

        # Sync manifest
        api.get_sync_manifest.return_value = APIResponse(
            success=True,
            status_code=200,
            data={
                'revision': 'abc123def456',
                'files': {
                    'playbooks/test.yml': {'sha256': 'hash1', 'size': 100},
                    'inventory/hosts': {'sha256': 'hash2', 'size': 50}
                }
            }
        )

        # Checkin
        api.checkin.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'message': 'Checkin successful', 'next_checkin_seconds': 600}
        )

        # Download archive (simulate by creating files)
        def download_archive_side_effect(output_path):
            # Create a fake archive
            import tarfile
            with tarfile.open(output_path, 'w:gz') as tar:
                # Add a test playbook
                playbook_path = os.path.join(self.test_dir, 'test_playbook.yml')
                with open(playbook_path, 'w') as f:
                    f.write('---\n- name: Test\n  hosts: all\n')
                tar.add(playbook_path, arcname='playbooks/test.yml')
                os.remove(playbook_path)
            return True, ''

        api.download_archive.side_effect = download_archive_side_effect

        return api

    def test_complete_worker_lifecycle(self):
        """Test complete worker lifecycle from startup to operation."""
        print("\n=== Feature 5: Worker Lifecycle Validation ===\n")

        # =====================================================================
        # Step 1: Load configuration
        # =====================================================================
        print("Step 1: Load worker configuration...")

        config = WorkerConfig(
            worker_name='test-worker-01',
            server_url='http://primary:3001',
            registration_token='valid-token',
            tags=['network-a', 'gpu', 'high-memory'],
            checkin_interval=600,
            sync_interval=300,
            max_concurrent_jobs=2,
            content_dir=self.test_dir,
            logs_dir=os.path.join(self.test_dir, 'logs')
        )

        errors = config.validate()
        self.assertEqual(len(errors), 0)
        print(f"  - Worker name: {config.worker_name}")
        print(f"  - Server URL: {config.server_url}")
        print(f"  - Tags: {config.tags}")

        # =====================================================================
        # Step 2: Initialize service and check connectivity
        # =====================================================================
        print("\nStep 2: Initialize service...")

        service = WorkerService(config)
        self.assertEqual(service.state, WorkerState.STARTING)
        print(f"  - Initial state: {service.state.value}")

        # Replace API client with mock
        mock_api = self._mock_api_responses()
        service.api = mock_api
        service.sync = ContentSync(mock_api, self.test_dir)

        # Check health
        self.assertTrue(mock_api.health_check())
        print("  - Server connectivity: OK")

        # =====================================================================
        # Step 3: Register with primary server
        # =====================================================================
        print("\nStep 3: Register with primary server...")

        result = service._register()
        self.assertTrue(result)
        self.assertEqual(service.state, WorkerState.REGISTERING)
        self.assertIsNotNone(service.worker_id)
        print(f"  - Registration: Success")
        print(f"  - Worker ID: {service.worker_id}")

        # =====================================================================
        # Step 4: Initial content sync
        # =====================================================================
        print("\nStep 4: Initial content sync...")

        # Ensure directories exist
        service.sync.ensure_directories()

        # Check sync is needed (no local revision)
        needs_sync, server_rev = service.sync.check_sync_needed()
        self.assertTrue(needs_sync)
        print(f"  - Sync needed: {needs_sync}")
        print(f"  - Server revision: {server_rev[:7] if server_rev else 'unknown'}")

        # =====================================================================
        # Step 5: Verify state transitions
        # =====================================================================
        print("\nStep 5: State transitions...")

        # Transition to IDLE
        service._set_state(WorkerState.IDLE)
        self.assertEqual(service.state, WorkerState.IDLE)
        print(f"  - State after sync: {service.state.value}")

        # Transition to BUSY when jobs present
        service._set_state(WorkerState.BUSY)
        self.assertEqual(service.state, WorkerState.BUSY)
        print(f"  - State with jobs: {service.state.value}")

        # Back to IDLE
        service._set_state(WorkerState.IDLE)
        print(f"  - State after jobs complete: {service.state.value}")

        # =====================================================================
        # Step 6: Perform check-in
        # =====================================================================
        print("\nStep 6: Worker check-in...")

        # Mock system stats
        with patch('worker.service.psutil') as mock_psutil:
            mock_psutil.cpu_percent.return_value = 25.0
            mock_psutil.virtual_memory.return_value = Mock(
                percent=45.0,
                available=8 * 1024 * 1024 * 1024
            )
            mock_psutil.disk_usage.return_value = Mock(
                percent=30.0,
                free=200 * 1024 * 1024 * 1024
            )

            with patch('os.getloadavg', return_value=(0.3, 0.4, 0.5)):
                result = service._checkin()

        self.assertTrue(result)
        print("  - Checkin: Success")

        # Verify checkin was called with correct data
        mock_api.checkin.assert_called()
        call_args = mock_api.checkin.call_args
        checkin_data = call_args[0][1]
        self.assertIn('system_stats', checkin_data)
        self.assertIn('active_jobs', checkin_data)
        print(f"  - System stats included: Yes")
        print(f"  - Active jobs reported: {len(checkin_data['active_jobs'])}")

        # =====================================================================
        # Step 7: Check for content updates
        # =====================================================================
        print("\nStep 7: Check for content updates...")

        # Initially in sync
        service.sync._local_revision = 'abc123def456'
        needs_sync, _ = service.sync.check_sync_needed()
        self.assertFalse(needs_sync)
        print(f"  - Content in sync: Yes")

        # Simulate server update
        mock_api.get_sync_revision.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'revision': 'new_revision_789'}
        )
        needs_sync, new_rev = service.sync.check_sync_needed()
        self.assertTrue(needs_sync)
        print(f"  - New content detected: Yes")
        print(f"  - New revision: {new_rev[:7] if new_rev else 'unknown'}")

        # =====================================================================
        # Step 8: Graceful shutdown
        # =====================================================================
        print("\nStep 8: Graceful shutdown...")

        service._running = True
        service.stop()

        self.assertEqual(service.state, WorkerState.STOPPING)
        self.assertFalse(service._running)
        print(f"  - Final state: {service.state.value}")
        print("  - Shutdown: Complete")

        print("\n=== Feature 5 Validation Complete ===")
        print("Worker service components validated successfully!")

    def test_registration_failure_handling(self):
        """Test handling of registration failures."""
        config = WorkerConfig(
            worker_name='bad-worker',
            server_url='http://primary:3001',
            registration_token='invalid-token',
            tags=['test'],
            content_dir=self.test_dir
        )

        service = WorkerService(config)
        mock_api = self._mock_api_responses()
        service.api = mock_api

        # Should fail with invalid token
        result = service._register()

        self.assertFalse(result)
        self.assertEqual(service.state, WorkerState.ERROR)

    def test_configuration_from_environment(self):
        """Test loading configuration from environment variables."""
        env = {
            'WORKER_NAME': 'env-test-worker',
            'SERVER_URL': 'http://env-primary:3001',
            'REGISTRATION_TOKEN': 'env-secret-token',
            'WORKER_TAGS': 'env-tag1, env-tag2',
            'CHECKIN_INTERVAL': '300',
            'SYNC_INTERVAL': '150',
            'MAX_CONCURRENT_JOBS': '4',
            'CONTENT_DIR': self.test_dir,
            'LOGS_DIR': os.path.join(self.test_dir, 'logs')
        }

        with patch.dict(os.environ, env, clear=False):
            config = WorkerConfig.from_env()

        self.assertEqual(config.worker_name, 'env-test-worker')
        self.assertEqual(config.tags, ['env-tag1', 'env-tag2'])
        self.assertEqual(config.checkin_interval, 300)
        self.assertEqual(config.max_concurrent_jobs, 4)


class TestWorkerSyncScenarios(unittest.TestCase):
    """Test various sync scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        for dir_name in ['playbooks', 'inventory', 'library', 'callback_plugins']:
            os.makedirs(os.path.join(self.test_dir, dir_name))

        self.api = Mock(spec=PrimaryAPIClient)
        self.sync = ContentSync(self.api, self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_incremental_sync_detection(self):
        """Test detection of files needing sync."""
        # Create local file
        with open(os.path.join(self.test_dir, 'playbooks', 'local.yml'), 'w') as f:
            f.write('local content')

        # Mock server having different files
        self.api.get_sync_manifest.return_value = APIResponse(
            success=True,
            status_code=200,
            data={
                'files': {
                    'playbooks/local.yml': {'sha256': 'different_hash', 'size': 100},
                    'playbooks/new.yml': {'sha256': 'new_hash', 'size': 50},
                    'inventory/hosts': {'sha256': 'inv_hash', 'size': 30}
                }
            }
        )

        new_files, modified_files, deleted_files = self.sync.get_changed_files()

        self.assertIn('playbooks/new.yml', new_files)
        self.assertIn('inventory/hosts', new_files)
        self.assertIn('playbooks/local.yml', modified_files)

    def test_sync_state_tracking(self):
        """Test that sync state is tracked correctly."""
        self.assertIsNone(self.sync.local_revision)

        # After "syncing"
        self.sync._local_revision = 'abc123'

        self.assertEqual(self.sync.local_revision, 'abc123')


if __name__ == '__main__':
    unittest.main(verbosity=2)
