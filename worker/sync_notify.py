"""
Sync Notification Client

Handles real-time sync notifications from the primary server via WebSocket.
When a sync_available event is received, triggers immediate content sync.
"""

import threading
from typing import Callable, Optional
from dataclasses import dataclass


@dataclass
class SyncNotification:
    """Sync notification data."""
    revision: str
    short_revision: str


class SyncNotificationClient:
    """
    WebSocket client for receiving sync notifications.

    Connects to the primary server and listens for sync_available events.
    When content changes are committed on the server, workers receive
    immediate notification to sync.
    """

    def __init__(self, server_url: str, on_sync_available: Callable[[SyncNotification], None]):
        """
        Initialize sync notification client.

        Args:
            server_url: Primary server URL (e.g., http://primary:3001)
            on_sync_available: Callback when sync notification received
        """
        self.server_url = server_url.rstrip('/')
        self._on_sync_available = on_sync_available
        self._sio = None
        self._connected = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        """Check if connected to server."""
        with self._lock:
            return self._connected

    def _setup_socketio(self):
        """Set up socketio client with event handlers."""
        try:
            import socketio
        except ImportError:
            print("Warning: python-socketio not installed, sync notifications disabled")
            return False

        self._sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=0,  # Infinite
            reconnection_delay=1,
            reconnection_delay_max=30
        )

        @self._sio.event
        def connect():
            with self._lock:
                self._connected = True
            print("Connected to sync notification server")
            # Join the workers room to receive sync notifications
            self._sio.emit('join_workers')

        @self._sio.event
        def disconnect():
            with self._lock:
                self._connected = False
            print("Disconnected from sync notification server")

        @self._sio.event
        def connect_error(data):
            print(f"Sync notification connection error: {data}")

        @self._sio.on('sync_available')
        def on_sync_available(data):
            """Handle sync_available event from server."""
            notification = SyncNotification(
                revision=data.get('revision', ''),
                short_revision=data.get('short_revision', '')
            )
            print(f"Sync notification received: revision {notification.short_revision}")

            # Call the callback
            try:
                self._on_sync_available(notification)
            except Exception as e:
                print(f"Error in sync notification handler: {e}")

        return True

    def _connect_loop(self):
        """Background connection loop."""
        if not self._setup_socketio():
            return

        while self._running:
            try:
                if not self._connected and self._sio:
                    print(f"Connecting to sync notification server at {self.server_url}")
                    self._sio.connect(self.server_url, wait_timeout=10)
                    # Wait while connected
                    self._sio.wait()
            except Exception as e:
                if self._running:  # Only log if we're still supposed to be running
                    print(f"Sync notification connection error: {e}")
                    import time
                    time.sleep(5)  # Wait before retry

    def start(self):
        """Start the notification client in background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._connect_loop,
            daemon=True,
            name="sync-notify"
        )
        self._thread.start()

    def stop(self):
        """Stop the notification client."""
        self._running = False

        if self._sio:
            try:
                self._sio.disconnect()
            except Exception:
                pass

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None


class PollingFallback:
    """
    Fallback polling-based sync checker.

    Used when WebSocket connection is unavailable.
    Checks for sync at regular intervals via HTTP.
    """

    def __init__(self, api_client, check_interval: float = 60.0):
        """
        Initialize polling fallback.

        Args:
            api_client: PrimaryAPIClient instance
            check_interval: Seconds between checks
        """
        self.api = api_client
        self.check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_revision: Optional[str] = None
        self._on_change: Optional[Callable[[str], None]] = None

    def set_callback(self, callback: Callable[[str], None]):
        """Set callback for when revision changes."""
        self._on_change = callback

    def _poll_loop(self):
        """Background polling loop."""
        import time

        while self._running:
            try:
                response = self.api.get_sync_revision()
                if response.success:
                    current_rev = response.data.get('revision')
                    if self._last_revision and current_rev != self._last_revision:
                        print(f"Revision change detected: {current_rev[:7] if current_rev else 'none'}")
                        if self._on_change:
                            self._on_change(current_rev)
                    self._last_revision = current_rev
            except Exception as e:
                print(f"Sync poll error: {e}")

            time.sleep(self.check_interval)

    def start(self, initial_revision: Optional[str] = None):
        """Start polling."""
        if self._running:
            return

        self._last_revision = initial_revision
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="sync-poll"
        )
        self._thread.start()

    def stop(self):
        """Stop polling."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
