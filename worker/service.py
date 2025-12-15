"""
Worker Service

Main worker service that manages the lifecycle of a worker node:
- Registration with primary server
- Content synchronization
- Job polling and status reporting
- Periodic check-ins
"""

import os
import sys
import time
import signal
import threading
import psutil
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum

from .config import WorkerConfig
from .api_client import PrimaryAPIClient
from .sync import ContentSync, SyncResult
from .executor import JobExecutor, JobPoller, JobResult


class WorkerState(Enum):
    """Worker state machine states."""
    STARTING = 'starting'
    REGISTERING = 'registering'
    SYNCING = 'syncing'
    IDLE = 'idle'
    BUSY = 'busy'
    STOPPING = 'stopping'
    ERROR = 'error'


class WorkerService:
    """
    Main worker service.

    Manages worker lifecycle including registration, sync, and job execution.
    """

    def __init__(self, config: WorkerConfig):
        """
        Initialize worker service.

        Args:
            config: Worker configuration
        """
        self.config = config
        self.api = PrimaryAPIClient(config.server_url)
        self.sync = ContentSync(self.api, config.content_dir)

        # Job execution components (initialized after registration)
        self.executor: Optional[JobExecutor] = None
        self.poller: Optional[JobPoller] = None

        self._state = WorkerState.STARTING
        self._running = False
        self._worker_id: Optional[str] = None
        self._active_jobs: Dict[str, Dict] = {}
        self._lock = threading.Lock()

        # Timing
        self._last_checkin = 0.0
        self._last_sync_check = 0.0
        self._last_job_poll = 0.0

        # Signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    @property
    def state(self) -> WorkerState:
        """Get current worker state."""
        return self._state

    @property
    def worker_id(self) -> Optional[str]:
        """Get worker ID (assigned after registration)."""
        return self._worker_id

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals."""
        print(f"\nReceived signal {signum}, initiating shutdown...")
        self.stop()

    def _set_state(self, state: WorkerState):
        """Set worker state and log transition."""
        old_state = self._state
        self._state = state
        print(f"State: {old_state.value} -> {state.value}")

    def _get_system_stats(self) -> Dict:
        """Get current system statistics."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(self.config.content_dir)

            return {
                'load_1m': os.getloadavg()[0] if hasattr(os, 'getloadavg') else cpu_percent / 100,
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_available_mb': memory.available // (1024 * 1024),
                'disk_percent': disk.percent,
                'disk_free_gb': disk.free // (1024 * 1024 * 1024)
            }
        except Exception as e:
            print(f"Error getting system stats: {e}")
            return {}

    def _register(self) -> bool:
        """
        Register with the primary server.

        Returns:
            True if registration successful
        """
        self._set_state(WorkerState.REGISTERING)

        print(f"Registering worker '{self.config.worker_name}' with {self.config.server_url}")
        print(f"Tags: {self.config.tags}")

        response = self.api.register(
            name=self.config.worker_name,
            tags=self.config.tags,
            token=self.config.registration_token
        )

        if not response.success:
            print(f"Registration failed: {response.error}")
            self._set_state(WorkerState.ERROR)
            return False

        self._worker_id = response.data.get('worker_id')
        self.config.worker_id = self._worker_id

        print(f"Registered successfully with ID: {self._worker_id}")
        print(f"Checkin interval: {response.data.get('checkin_interval')}s")

        return True

    def _initial_sync(self) -> bool:
        """
        Perform initial content sync.

        Returns:
            True if sync successful
        """
        self._set_state(WorkerState.SYNCING)

        print("Performing initial content sync...")

        # Ensure directories exist
        self.sync.ensure_directories()

        # Full sync for initial
        result = self.sync.full_sync()

        if not result.success:
            print(f"Initial sync failed: {result.error}")
            self._set_state(WorkerState.ERROR)
            return False

        print(f"Sync complete: {result.files_synced} files, revision {result.revision[:7] if result.revision else 'unknown'}")
        return True

    def _checkin(self) -> bool:
        """
        Send check-in to primary server.

        Returns:
            True if checkin successful
        """
        if not self._worker_id:
            return False

        # Build active jobs info
        with self._lock:
            active_jobs = []
            for job_id, job_info in self._active_jobs.items():
                active_jobs.append({
                    'job_id': job_id,
                    'status': job_info.get('status', 'running'),
                    'progress': job_info.get('progress', 0),
                    'started': job_info.get('started')
                })

        checkin_data = {
            'sync_revision': self.sync.local_revision,
            'active_jobs': active_jobs,
            'system_stats': self._get_system_stats(),
            'status': 'busy' if active_jobs else 'online'
        }

        response = self.api.checkin(self._worker_id, checkin_data)

        if not response.success:
            print(f"Checkin failed: {response.error}")
            return False

        self._last_checkin = time.time()
        return True

    def _check_sync(self) -> bool:
        """
        Check if content sync is needed and sync if so.

        Returns:
            True if sync check successful (sync may or may not have occurred)
        """
        needs_sync, server_rev = self.sync.check_sync_needed()

        if not needs_sync:
            return True

        print(f"Content update detected (server: {server_rev[:7] if server_rev else 'unknown'})")

        old_state = self._state
        self._set_state(WorkerState.SYNCING)

        result = self.sync.sync()

        if result.success:
            print(f"Sync complete: {result.files_synced} files updated")
            self._set_state(old_state)
            return True
        else:
            print(f"Sync failed: {result.error}")
            self._set_state(old_state)
            return False

    def _poll_jobs(self) -> List[Dict]:
        """
        Poll for assigned jobs and execute them.

        Returns:
            List of jobs that were started
        """
        if not self._worker_id or not self.poller:
            return []

        return self.poller.poll_once()

    def _on_job_complete(self, result: JobResult):
        """Callback for job completion."""
        print(f"Job completed: {result.job_id} (exit: {result.exit_code})")

        # Update active jobs tracking
        with self._lock:
            self._active_jobs.pop(result.job_id, None)

    def _init_executor(self):
        """Initialize job executor and poller after registration."""
        if not self._worker_id:
            return

        # Ensure logs directory exists
        os.makedirs(self.config.logs_dir, exist_ok=True)

        self.executor = JobExecutor(
            api_client=self.api,
            worker_id=self._worker_id,
            content_dir=self.config.content_dir,
            logs_dir=self.config.logs_dir
        )

        # Register completion callback
        self.executor.on_complete(self._on_job_complete)

        self.poller = JobPoller(
            api_client=self.api,
            worker_id=self._worker_id,
            executor=self.executor,
            max_concurrent=self.config.max_concurrent_jobs
        )

        print(f"Job executor initialized (max concurrent: {self.config.max_concurrent_jobs})")

    def _main_loop(self):
        """Main service loop."""
        self._set_state(WorkerState.IDLE)

        while self._running:
            try:
                current_time = time.time()

                # Check-in at configured interval
                if current_time - self._last_checkin >= self.config.checkin_interval:
                    self._checkin()

                # Check for content updates at configured interval
                if current_time - self._last_sync_check >= self.config.sync_interval:
                    self._check_sync()
                    self._last_sync_check = current_time

                # Poll for jobs at poll interval
                if current_time - self._last_job_poll >= self.config.poll_interval:
                    started = self._poll_jobs()
                    self._last_job_poll = current_time
                    if started:
                        for job in started:
                            with self._lock:
                                self._active_jobs[job.get('id')] = {
                                    'status': 'running',
                                    'started': datetime.now().isoformat()
                                }

                # Update state based on executor's active jobs
                if self.executor:
                    active_count = self.executor.active_job_count
                    if active_count > 0:
                        if self._state != WorkerState.BUSY:
                            self._set_state(WorkerState.BUSY)
                    else:
                        if self._state != WorkerState.IDLE:
                            self._set_state(WorkerState.IDLE)

                # Sleep a bit between iterations
                time.sleep(1)

            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(5)  # Back off on error

    def start(self) -> bool:
        """
        Start the worker service.

        Returns:
            True if startup successful
        """
        print(f"Starting worker service...")
        print(f"Worker name: {self.config.worker_name}")
        print(f"Server URL: {self.config.server_url}")
        print(f"Content dir: {self.config.content_dir}")

        # Validate config
        errors = self.config.validate()
        if errors:
            print(f"Configuration errors: {errors}")
            return False

        # Check server connectivity
        print("Checking server connectivity...")
        if not self.api.health_check():
            print("Cannot connect to primary server")
            return False
        print("Server is reachable")

        # Register
        if not self._register():
            return False

        # Initial sync
        if not self._initial_sync():
            return False

        # Initialize job executor
        self._init_executor()

        # Start main loop
        self._running = True
        self._last_checkin = 0  # Force immediate checkin
        self._last_sync_check = time.time()
        self._last_job_poll = 0  # Force immediate job poll

        print("Worker service started successfully")
        self._main_loop()

        return True

    def stop(self):
        """Stop the worker service."""
        print("Stopping worker service...")
        self._set_state(WorkerState.STOPPING)
        self._running = False

        # Wait for running jobs to complete (with timeout)
        if self.executor and self.executor.active_job_count > 0:
            print(f"Waiting for {self.executor.active_job_count} active jobs to complete...")
            if self.executor.wait_for_jobs(timeout=60):
                print("All jobs completed")
            else:
                print("Timeout waiting for jobs - some may still be running")

        # Final checkin
        if self._worker_id:
            checkin_data = {
                'sync_revision': self.sync.local_revision,
                'active_jobs': [],
                'system_stats': self._get_system_stats(),
                'status': 'offline'
            }
            self.api.checkin(self._worker_id, checkin_data)

        print("Worker service stopped")

    def run(self):
        """Run the worker service (blocking)."""
        try:
            if not self.start():
                sys.exit(1)
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            print(f"Fatal error: {e}")
            self.stop()
            sys.exit(1)


def main():
    """Entry point for worker service."""
    print("=" * 60)
    print("Ansible SimpleWeb Worker Service")
    print("=" * 60)

    try:
        config = WorkerConfig.from_env()
    except ValueError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    service = WorkerService(config)
    service.run()


if __name__ == '__main__':
    main()
