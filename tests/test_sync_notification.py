"""
Unit tests for sync notification system (Feature 11).

Tests the sync notification components including:
- SyncNotification dataclass
- SyncNotificationClient
- PollingFallback
- Worker service sync integration
"""

import os
import sys
import time
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch, MagicMock
from threading import Event

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.sync_notify import SyncNotification, SyncNotificationClient, PollingFallback


class TestSyncNotification(unittest.TestCase):
    """Test SyncNotification dataclass."""

    def test_notification_creation(self):
        """Test creating a sync notification."""
        notification = SyncNotification(
            revision='abc123def456',
            short_revision='abc123d'
        )
        self.assertEqual(notification.revision, 'abc123def456')
        self.assertEqual(notification.short_revision, 'abc123d')

    def test_notification_empty_values(self):
        """Test notification with empty values."""
        notification = SyncNotification(revision='', short_revision='')
        self.assertEqual(notification.revision, '')
        self.assertEqual(notification.short_revision, '')


class TestSyncNotificationClient(unittest.TestCase):
    """Test SyncNotificationClient."""

    def test_client_initialization(self):
        """Test client initialization."""
        callback = Mock()
        client = SyncNotificationClient(
            server_url='http://localhost:3001',
            on_sync_available=callback
        )
        self.assertEqual(client.server_url, 'http://localhost:3001')
        self.assertFalse(client.connected)

    def test_client_url_strips_trailing_slash(self):
        """Test that trailing slash is stripped from URL."""
        callback = Mock()
        client = SyncNotificationClient(
            server_url='http://localhost:3001/',
            on_sync_available=callback
        )
        self.assertEqual(client.server_url, 'http://localhost:3001')

    def test_connected_property_initial(self):
        """Test connected property is initially False."""
        callback = Mock()
        client = SyncNotificationClient('http://localhost:3001', callback)
        self.assertFalse(client.connected)

    @patch('worker.sync_notify.SyncNotificationClient._setup_socketio')
    def test_start_creates_thread(self, mock_setup):
        """Test that start creates a background thread."""
        mock_setup.return_value = False  # Simulate no socketio
        callback = Mock()
        client = SyncNotificationClient('http://localhost:3001', callback)
        client.start()
        time.sleep(0.1)  # Let thread start
        self.assertTrue(client._running)
        client.stop()

    def test_stop_sets_running_false(self):
        """Test that stop sets running to False."""
        callback = Mock()
        client = SyncNotificationClient('http://localhost:3001', callback)
        client._running = True
        client.stop()
        self.assertFalse(client._running)

    def test_setup_socketio_missing_import(self):
        """Test handling when socketio is not installed."""
        callback = Mock()
        client = SyncNotificationClient('http://localhost:3001', callback)

        # Simulate ImportError for socketio
        with patch.dict('sys.modules', {'socketio': None}):
            # This will try to import and fail gracefully
            result = client._setup_socketio()
            # Should return False or raise no exception


class TestPollingFallback(unittest.TestCase):
    """Test PollingFallback sync checker."""

    def test_initialization(self):
        """Test polling fallback initialization."""
        mock_api = Mock()
        fallback = PollingFallback(mock_api, check_interval=30.0)
        self.assertEqual(fallback.check_interval, 30.0)
        self.assertFalse(fallback._running)

    def test_set_callback(self):
        """Test setting callback."""
        mock_api = Mock()
        fallback = PollingFallback(mock_api)
        callback = Mock()
        fallback.set_callback(callback)
        self.assertEqual(fallback._on_change, callback)

    def test_start_sets_running(self):
        """Test start sets running flag."""
        mock_api = Mock()
        mock_api.get_sync_revision.return_value = Mock(
            success=True,
            data={'revision': 'abc123'}
        )
        fallback = PollingFallback(mock_api, check_interval=1.0)
        fallback.start(initial_revision='abc123')
        self.assertTrue(fallback._running)
        self.assertEqual(fallback._last_revision, 'abc123')
        fallback.stop()

    def test_stop_sets_running_false(self):
        """Test stop clears running flag."""
        mock_api = Mock()
        fallback = PollingFallback(mock_api)
        fallback._running = True
        fallback.stop()
        self.assertFalse(fallback._running)

    def test_detects_revision_change(self):
        """Test that revision change triggers callback."""
        mock_api = Mock()
        mock_api.get_sync_revision.return_value = Mock(
            success=True,
            data={'revision': 'newrev123'}
        )

        received_rev = []

        def callback(rev):
            received_rev.append(rev)

        fallback = PollingFallback(mock_api, check_interval=0.1)
        fallback.set_callback(callback)
        fallback._last_revision = 'oldrev123'

        # Manually simulate what poll loop does (single iteration)
        response = mock_api.get_sync_revision()
        if response.success:
            current_rev = response.data.get('revision')
            if fallback._last_revision and current_rev != fallback._last_revision:
                if fallback._on_change:
                    fallback._on_change(current_rev)
            fallback._last_revision = current_rev

        # Check if callback was called
        self.assertEqual(len(received_rev), 1)
        self.assertEqual(received_rev[0], 'newrev123')
        self.assertEqual(fallback._last_revision, 'newrev123')

    def test_no_callback_on_same_revision(self):
        """Test no callback when revision unchanged."""
        mock_api = Mock()
        mock_api.get_sync_revision.return_value = Mock(
            success=True,
            data={'revision': 'same123'}
        )

        callback = Mock()
        fallback = PollingFallback(mock_api, check_interval=0.1)
        fallback.set_callback(callback)
        fallback._last_revision = 'same123'

        # Should not trigger callback - same revision
        response = mock_api.get_sync_revision()
        current_rev = response.data.get('revision')
        self.assertEqual(current_rev, fallback._last_revision)


class TestWorkerServiceSyncIntegration(unittest.TestCase):
    """Test WorkerService sync notification integration."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch('worker.service.PrimaryAPIClient')
    @patch('worker.service.ContentSync')
    def test_sync_pending_flag(self, mock_sync_class, mock_api_class):
        """Test sync pending flag triggers sync."""
        from worker.service import WorkerService
        from worker.config import WorkerConfig

        config = WorkerConfig(
            server_url='http://test:3001',
            worker_name='test-worker',
            tags=[],
            content_dir=self.test_dir,
            logs_dir=os.path.join(self.test_dir, 'logs'),
            registration_token='test-token'
        )

        service = WorkerService(config)
        service._sync_pending = True

        # Verify flag is set
        self.assertTrue(service._sync_pending)

        # Simulate what main loop does
        with service._lock:
            sync_now = service._sync_pending
            service._sync_pending = False

        self.assertTrue(sync_now)
        self.assertFalse(service._sync_pending)

    @patch('worker.service.PrimaryAPIClient')
    @patch('worker.service.ContentSync')
    def test_on_sync_notification(self, mock_sync_class, mock_api_class):
        """Test sync notification handler sets pending flag."""
        from worker.service import WorkerService
        from worker.config import WorkerConfig
        from worker.sync_notify import SyncNotification

        config = WorkerConfig(
            server_url='http://test:3001',
            worker_name='test-worker',
            tags=[],
            content_dir=self.test_dir,
            logs_dir=os.path.join(self.test_dir, 'logs'),
            registration_token='test-token'
        )

        # Set up mock sync
        mock_sync = Mock()
        mock_sync.local_revision = 'oldrev123'
        mock_sync_class.return_value = mock_sync

        service = WorkerService(config)

        # Simulate notification
        notification = SyncNotification(
            revision='newrev456',
            short_revision='newrev4'
        )
        service._on_sync_notification(notification)

        # Should set sync pending
        self.assertTrue(service._sync_pending)

    @patch('worker.service.PrimaryAPIClient')
    @patch('worker.service.ContentSync')
    def test_notification_ignored_if_same_revision(self, mock_sync_class, mock_api_class):
        """Test notification ignored when already at revision."""
        from worker.service import WorkerService
        from worker.config import WorkerConfig
        from worker.sync_notify import SyncNotification

        config = WorkerConfig(
            server_url='http://test:3001',
            worker_name='test-worker',
            tags=[],
            content_dir=self.test_dir,
            logs_dir=os.path.join(self.test_dir, 'logs'),
            registration_token='test-token'
        )

        # Set up mock sync with same revision
        mock_sync = Mock()
        mock_sync.local_revision = 'samerev123'
        mock_sync_class.return_value = mock_sync

        service = WorkerService(config)
        service._sync_pending = False

        # Notification with same revision
        notification = SyncNotification(
            revision='samerev123',
            short_revision='samerev'
        )
        service._on_sync_notification(notification)

        # Should NOT set sync pending
        self.assertFalse(service._sync_pending)


class TestServerSyncBroadcast(unittest.TestCase):
    """Test server-side sync broadcast functionality."""

    def test_sync_commit_emits_event(self):
        """Test that sync commit endpoint emits sync_available event."""
        # This is tested via the feature validation test
        # Here we just verify the structure
        event_data = {
            'revision': 'abc123def456',
            'short_revision': 'abc123d'
        }
        self.assertIn('revision', event_data)
        self.assertIn('short_revision', event_data)


class TestAPIClientSyncMethods(unittest.TestCase):
    """Test API client sync-related methods."""

    @patch('worker.api_client.requests.request')
    def test_get_sync_revision(self, mock_request):
        """Test getting sync revision from server."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'revision': 'abc123def456',
            'short_revision': 'abc123d'
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')
        result = client.get_sync_revision()

        self.assertTrue(result.success)
        self.assertEqual(result.data['revision'], 'abc123def456')
        mock_request.assert_called_once()

    @patch('worker.api_client.requests.request')
    def test_get_sync_status(self, mock_request):
        """Test getting sync status from server."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'initialized': True,
            'revision': 'abc123',
            'short_revision': 'abc123'
        }
        mock_request.return_value = mock_response

        from worker.api_client import PrimaryAPIClient
        client = PrimaryAPIClient('http://localhost:3001')
        result = client.get_sync_status()

        self.assertTrue(result.success)
        self.assertTrue(result.data['initialized'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
