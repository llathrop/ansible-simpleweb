"""
Unit tests for Worker Client Service (Feature 5).

Tests the worker configuration, API client, and sync modules.
"""

import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.config import WorkerConfig
from worker.api_client import PrimaryAPIClient, APIResponse
from worker.sync import ContentSync, SyncResult
from worker.service import WorkerService, WorkerState


class TestWorkerConfig(unittest.TestCase):
    """Test worker configuration."""

    def test_config_creation(self):
        """Test creating config directly."""
        config = WorkerConfig(
            worker_name='test-worker',
            server_url='http://localhost:3001',
            registration_token='secret',
            tags=['test', 'gpu']
        )

        self.assertEqual(config.worker_name, 'test-worker')
        self.assertEqual(config.server_url, 'http://localhost:3001')
        self.assertEqual(config.tags, ['test', 'gpu'])
        self.assertEqual(config.checkin_interval, 600)

    def test_config_from_env(self):
        """Test loading config from environment."""
        env = {
            'WORKER_NAME': 'env-worker',
            'SERVER_URL': 'http://primary:3001',
            'REGISTRATION_TOKEN': 'token123',
            'WORKER_TAGS': 'tag1, tag2, tag3',
            'CHECKIN_INTERVAL': '300',
            'MAX_CONCURRENT_JOBS': '4'
        }

        with patch.dict(os.environ, env, clear=False):
            config = WorkerConfig.from_env()

        self.assertEqual(config.worker_name, 'env-worker')
        self.assertEqual(config.server_url, 'http://primary:3001')
        self.assertEqual(config.tags, ['tag1', 'tag2', 'tag3'])
        self.assertEqual(config.checkin_interval, 300)
        self.assertEqual(config.max_concurrent_jobs, 4)

    def test_config_missing_required(self):
        """Test that missing required fields raise error."""
        env = {
            'WORKER_NAME': '',
            'SERVER_URL': 'http://primary:3001',
            'REGISTRATION_TOKEN': 'token'
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                WorkerConfig.from_env()

    def test_config_validation(self):
        """Test config validation."""
        config = WorkerConfig(
            worker_name='',
            server_url='',
            registration_token='',
            checkin_interval=5,
            max_concurrent_jobs=0
        )

        errors = config.validate()

        self.assertIn('worker_name is required', errors)
        self.assertIn('server_url is required', errors)
        self.assertIn('checkin_interval must be at least 10 seconds', errors)
        self.assertIn('max_concurrent_jobs must be at least 1', errors)

    def test_config_to_dict(self):
        """Test config to dict conversion."""
        config = WorkerConfig(
            worker_name='test',
            server_url='http://localhost:3001',
            registration_token='secret',
            tags=['a', 'b']
        )

        d = config.to_dict()

        self.assertEqual(d['worker_name'], 'test')
        self.assertNotIn('registration_token', d)  # Should not expose token


class TestAPIClient(unittest.TestCase):
    """Test API client."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = PrimaryAPIClient('http://localhost:3001')

    def test_client_initialization(self):
        """Test client initialization."""
        self.assertEqual(self.client.server_url, 'http://localhost:3001')
        self.assertIsNone(self.client.worker_id)

    def test_url_normalization(self):
        """Test URL trailing slash handling."""
        client = PrimaryAPIClient('http://localhost:3001/')
        self.assertEqual(client.server_url, 'http://localhost:3001')

    @patch('worker.api_client.requests.request')
    def test_register_success(self, mock_request):
        """Test successful registration."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {
            'worker_id': 'test-uuid',
            'checkin_interval': 600
        }
        mock_request.return_value = mock_response

        result = self.client.register('worker-1', ['tag1'], 'token')

        self.assertTrue(result.success)
        self.assertEqual(result.data['worker_id'], 'test-uuid')
        self.assertEqual(self.client.worker_id, 'test-uuid')

    @patch('worker.api_client.requests.request')
    def test_register_failure(self, mock_request):
        """Test failed registration."""
        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.json.return_value = {'error': 'Invalid token'}
        mock_request.return_value = mock_response

        result = self.client.register('worker-1', ['tag1'], 'bad-token')

        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 401)

    @patch('worker.api_client.requests.request')
    def test_connection_error(self, mock_request):
        """Test handling of connection errors."""
        import requests
        mock_request.side_effect = requests.exceptions.ConnectionError('Connection refused')

        result = self.client.register('worker-1', ['tag1'], 'token')

        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 0)
        self.assertIn('Connection error', result.error)

    @patch('worker.api_client.requests.request')
    def test_checkin(self, mock_request):
        """Test worker check-in."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {'message': 'Checkin successful'}
        mock_request.return_value = mock_response

        result = self.client.checkin('worker-id', {
            'sync_revision': 'abc123',
            'system_stats': {'load_1m': 0.5}
        })

        self.assertTrue(result.success)

    @patch('worker.api_client.requests.request')
    def test_get_sync_revision(self, mock_request):
        """Test getting sync revision."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'revision': 'abc123def456',
            'short_revision': 'abc123d'
        }
        mock_request.return_value = mock_response

        result = self.client.get_sync_revision()

        self.assertTrue(result.success)
        self.assertEqual(result.data['revision'], 'abc123def456')

    @patch('worker.api_client.requests.get')
    def test_health_check_success(self, mock_get):
        """Test successful health check."""
        mock_response = Mock()
        mock_response.ok = True
        mock_get.return_value = mock_response

        self.assertTrue(self.client.health_check())

    @patch('worker.api_client.requests.get')
    def test_health_check_failure(self, mock_get):
        """Test failed health check."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError()

        self.assertFalse(self.client.health_check())


class TestContentSync(unittest.TestCase):
    """Test content synchronization."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.api = Mock(spec=PrimaryAPIClient)
        self.sync = ContentSync(self.api, self.test_dir)

        # Create directory structure
        for dir_name in ContentSync.SYNC_DIRS:
            os.makedirs(os.path.join(self.test_dir, dir_name))

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_ensure_directories(self):
        """Test directory creation."""
        new_dir = tempfile.mkdtemp()
        try:
            sync = ContentSync(self.api, new_dir)
            sync.ensure_directories()

            for dir_name in ContentSync.SYNC_DIRS:
                self.assertTrue(os.path.isdir(os.path.join(new_dir, dir_name)))
        finally:
            shutil.rmtree(new_dir, ignore_errors=True)

    def test_check_sync_needed_no_local(self):
        """Test sync check when no local revision."""
        self.api.get_sync_revision.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'revision': 'abc123'}
        )

        needs_sync, server_rev = self.sync.check_sync_needed()

        self.assertTrue(needs_sync)
        self.assertEqual(server_rev, 'abc123')

    def test_check_sync_needed_same_revision(self):
        """Test sync check when revisions match."""
        self.sync._local_revision = 'abc123'
        self.api.get_sync_revision.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'revision': 'abc123'}
        )

        needs_sync, server_rev = self.sync.check_sync_needed()

        self.assertFalse(needs_sync)

    def test_check_sync_needed_different_revision(self):
        """Test sync check when revisions differ."""
        self.sync._local_revision = 'abc123'
        self.api.get_sync_revision.return_value = APIResponse(
            success=True,
            status_code=200,
            data={'revision': 'def456'}
        )

        needs_sync, server_rev = self.sync.check_sync_needed()

        self.assertTrue(needs_sync)

    def test_build_local_manifest(self):
        """Test building local file manifest."""
        # Create test files
        with open(os.path.join(self.test_dir, 'playbooks', 'test.yml'), 'w') as f:
            f.write('test content')

        manifest = self.sync._build_local_manifest()

        self.assertIn('playbooks/test.yml', manifest)
        self.assertIn('sha256', manifest['playbooks/test.yml'])

    def test_build_local_manifest_excludes_hidden(self):
        """Test that manifest excludes hidden files."""
        with open(os.path.join(self.test_dir, 'playbooks', '.hidden'), 'w') as f:
            f.write('hidden')

        manifest = self.sync._build_local_manifest()

        self.assertNotIn('playbooks/.hidden', manifest)

    def test_get_changed_files(self):
        """Test detecting changed files."""
        # Create local file
        with open(os.path.join(self.test_dir, 'playbooks', 'existing.yml'), 'w') as f:
            f.write('original content')

        # Mock server manifest with modifications
        self.api.get_sync_manifest.return_value = APIResponse(
            success=True,
            status_code=200,
            data={
                'files': {
                    'playbooks/existing.yml': {
                        'sha256': 'different_hash',
                        'size': 100
                    },
                    'playbooks/new.yml': {
                        'sha256': 'new_hash',
                        'size': 50
                    }
                }
            }
        )

        new_files, modified_files, deleted_files = self.sync.get_changed_files()

        self.assertIn('playbooks/new.yml', new_files)
        self.assertIn('playbooks/existing.yml', modified_files)


class TestWorkerService(unittest.TestCase):
    """Test worker service."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.config = WorkerConfig(
            worker_name='test-worker',
            server_url='http://localhost:3001',
            registration_token='secret',
            tags=['test'],
            content_dir=self.test_dir
        )

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_service_initialization(self):
        """Test service initialization."""
        service = WorkerService(self.config)

        self.assertEqual(service.state, WorkerState.STARTING)
        self.assertIsNone(service.worker_id)

    def test_state_transitions(self):
        """Test state machine transitions."""
        service = WorkerService(self.config)

        service._set_state(WorkerState.REGISTERING)
        self.assertEqual(service.state, WorkerState.REGISTERING)

        service._set_state(WorkerState.SYNCING)
        self.assertEqual(service.state, WorkerState.SYNCING)

        service._set_state(WorkerState.IDLE)
        self.assertEqual(service.state, WorkerState.IDLE)

    @patch('worker.service.psutil')
    def test_get_system_stats(self, mock_psutil):
        """Test system stats collection."""
        mock_psutil.cpu_percent.return_value = 50.0
        mock_psutil.virtual_memory.return_value = Mock(
            percent=60.0,
            available=4 * 1024 * 1024 * 1024
        )
        mock_psutil.disk_usage.return_value = Mock(
            percent=70.0,
            free=100 * 1024 * 1024 * 1024
        )

        service = WorkerService(self.config)

        with patch('os.getloadavg', return_value=(0.5, 0.6, 0.7)):
            stats = service._get_system_stats()

        self.assertIn('cpu_percent', stats)
        self.assertIn('memory_percent', stats)
        self.assertIn('disk_percent', stats)

    def test_config_validation_on_start(self):
        """Test that start validates config."""
        bad_config = WorkerConfig(
            worker_name='',
            server_url='',
            registration_token='',
        )
        service = WorkerService(bad_config)

        result = service.start()

        self.assertFalse(result)


class TestSyncResult(unittest.TestCase):
    """Test SyncResult dataclass."""

    def test_success_result(self):
        """Test successful sync result."""
        result = SyncResult(
            success=True,
            revision='abc123',
            files_synced=10
        )

        self.assertTrue(result.success)
        self.assertEqual(result.revision, 'abc123')
        self.assertEqual(result.files_synced, 10)
        self.assertIsNone(result.error)

    def test_failure_result(self):
        """Test failed sync result."""
        result = SyncResult(
            success=False,
            error='Connection refused'
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, 'Connection refused')


if __name__ == '__main__':
    unittest.main()
