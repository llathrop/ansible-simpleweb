"""
Job Executor

Handles execution of Ansible playbooks for assigned jobs:
- Polls for assigned jobs
- Executes ansible-playbook command
- Captures stdout/stderr to log file
- Reports completion status to primary
"""

import os
import subprocess
import threading
import json
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from queue import Queue, Empty

from .api_client import PrimaryAPIClient


@dataclass
class JobResult:
    """Result of job execution."""
    job_id: str
    success: bool
    exit_code: int
    log_file: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class JobExecutor:
    """
    Executes Ansible playbooks for assigned jobs.

    Handles the full lifecycle:
    1. Receive job from service
    2. Notify primary that job started
    3. Execute ansible-playbook
    4. Capture output to log file
    5. Report completion to primary
    """

    def __init__(self, api_client: PrimaryAPIClient, worker_id: str,
                 content_dir: str, logs_dir: str, worker_name: str = None):
        """
        Initialize job executor.

        Args:
            api_client: API client for primary server
            worker_id: This worker's ID
            content_dir: Directory containing playbooks/inventory
            logs_dir: Directory for job logs
            worker_name: Human-readable worker name for logs
        """
        self.api = api_client
        self.worker_id = worker_id
        self.worker_name = worker_name or worker_id[:8]
        self.content_dir = content_dir
        self.logs_dir = logs_dir

        # Active jobs being executed
        self._active_jobs: Dict[str, Dict] = {}
        self._lock = threading.Lock()

        # Job completion callbacks
        self._on_complete_callbacks: List[Callable[[JobResult], None]] = []

    @property
    def active_job_count(self) -> int:
        """Get number of active jobs."""
        with self._lock:
            return len(self._active_jobs)

    @property
    def active_jobs(self) -> List[Dict]:
        """Get list of active job info."""
        with self._lock:
            return [
                {
                    'job_id': job_id,
                    'status': info.get('status', 'running'),
                    'started': info.get('started_at')
                }
                for job_id, info in self._active_jobs.items()
            ]

    def on_complete(self, callback: Callable[[JobResult], None]):
        """Register a callback for job completion."""
        self._on_complete_callbacks.append(callback)

    def _generate_log_filename(self, job_id: str, playbook: str) -> str:
        """Generate unique log filename for a job."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        playbook_name = os.path.splitext(os.path.basename(playbook))[0]
        return f"{playbook_name}_{job_id[:8]}_{timestamp}.log"

    def _resolve_playbook_path(self, playbook: str) -> str:
        """
        Resolve playbook name to full path, handling extension normalization.

        The web UI stores playbook names without extensions (e.g., 'service-status'),
        but the actual files have .yml or .yaml extensions. This method:
        1. If playbook already has .yml/.yaml extension, uses it as-is
        2. Otherwise, checks for .yml first, then .yaml
        3. Falls back to the original name if no file found (will error at runtime)

        Args:
            playbook: Playbook name (with or without extension)

        Returns:
            Full path to the playbook file
        """
        playbooks_dir = os.path.join(self.content_dir, 'playbooks')

        # If already has a YAML extension, use as-is
        if playbook.endswith('.yml') or playbook.endswith('.yaml'):
            return os.path.join(playbooks_dir, playbook)

        # Try .yml extension first (most common)
        yml_path = os.path.join(playbooks_dir, f"{playbook}.yml")
        if os.path.exists(yml_path):
            return yml_path

        # Try .yaml extension
        yaml_path = os.path.join(playbooks_dir, f"{playbook}.yaml")
        if os.path.exists(yaml_path):
            return yaml_path

        # Fall back to original (will fail at runtime with clear error)
        return os.path.join(playbooks_dir, playbook)

    def _build_ansible_command(self, job: Dict) -> List[str]:
        """
        Build ansible-playbook command for a job.

        Args:
            job: Job dict with playbook, target, extra_vars, etc.

        Returns:
            Command as list of arguments
        """
        playbook = job.get('playbook')
        target = job.get('target', 'all')
        extra_vars = job.get('extra_vars', {})

        # Resolve playbook path with extension handling
        playbook_path = self._resolve_playbook_path(playbook)
        inventory_path = os.path.join(self.content_dir, 'inventory', 'hosts')

        cmd = [
            'ansible-playbook',
            playbook_path,
            '-i', inventory_path,
        ]

        # Add target limit
        if target and target != 'all':
            cmd.extend(['-l', target])

        # Add extra variables
        if extra_vars:
            extra_vars_json = json.dumps(extra_vars)
            cmd.extend(['-e', extra_vars_json])

        return cmd

    def _execute_playbook(self, job: Dict, log_path: str) -> tuple:
        """
        Execute ansible-playbook and capture output.

        Streams log output to both a local file and to the primary server
        for live viewing in the web UI.

        Args:
            job: Job dict
            log_path: Path to write log output

        Returns:
            Tuple of (exit_code, error_message)
        """
        cmd = self._build_ansible_command(job)
        job_id = job.get('id')

        # Configuration for log streaming
        # Stream buffer to primary every N lines or N seconds
        STREAM_BUFFER_LINES = 10
        STREAM_INTERVAL_SECONDS = 2.0

        try:
            with open(log_path, 'w') as log_file:
                # Write header with worker identification
                header = (
                    f"Worker: {self.worker_name} ({self.worker_id[:8]})\n"
                    f"Job ID: {job.get('id')}\n"
                    f"Playbook: {job.get('playbook')}\n"
                    f"Target: {job.get('target', 'all')}\n"
                    f"Started: {datetime.now().isoformat()}\n"
                    f"Command: {' '.join(cmd)}\n"
                    + "=" * 60 + "\n\n"
                )
                log_file.write(header)
                log_file.flush()

                # Stream header to primary (first chunk, not append)
                self._stream_log_chunk(job_id, header, append=False)

                # Execute playbook
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=self.content_dir,
                    env={**os.environ, 'ANSIBLE_FORCE_COLOR': 'false'}
                )

                # Buffer for streaming to primary
                import time
                stream_buffer = []
                last_stream_time = time.time()

                # Stream output to log file and primary
                for line in process.stdout:
                    decoded_line = line.decode('utf-8', errors='replace')
                    log_file.write(decoded_line)
                    log_file.flush()

                    # Add to stream buffer
                    stream_buffer.append(decoded_line)

                    # Stream to primary when buffer is full or time elapsed
                    current_time = time.time()
                    should_stream = (
                        len(stream_buffer) >= STREAM_BUFFER_LINES or
                        (current_time - last_stream_time) >= STREAM_INTERVAL_SECONDS
                    )

                    if should_stream and stream_buffer:
                        content = ''.join(stream_buffer)
                        self._stream_log_chunk(job_id, content, append=True)
                        stream_buffer = []
                        last_stream_time = current_time

                process.wait()

                # Stream any remaining buffer content
                if stream_buffer:
                    content = ''.join(stream_buffer)
                    self._stream_log_chunk(job_id, content, append=True)

                # Write footer
                footer = (
                    "\n" + "=" * 60 + "\n"
                    f"Completed: {datetime.now().isoformat()}\n"
                    f"Exit Code: {process.returncode}\n"
                )
                log_file.write(footer)

                # Stream footer
                self._stream_log_chunk(job_id, footer, append=True)

                return process.returncode, None

        except FileNotFoundError:
            error_msg = "ansible-playbook command not found"
            return 127, error_msg
        except PermissionError as e:
            error_msg = f"Permission denied: {str(e)}"
            return 126, error_msg
        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            return 1, error_msg

    def _stream_log_chunk(self, job_id: str, content: str, append: bool = True):
        """
        Stream a log chunk to the primary server for live viewing.

        Failures are logged but don't interrupt job execution.

        Args:
            job_id: Job ID
            content: Log content to stream
            append: True to append, False to replace
        """
        try:
            response = self.api.stream_log(job_id, self.worker_id, content, append)
            if not response.success:
                # Log failure but don't interrupt job
                print(f"Warning: Log stream failed for job {job_id}: {response.error}")
        except Exception as e:
            print(f"Warning: Log stream error for job {job_id}: {e}")

    def _run_job(self, job: Dict):
        """
        Run a job (called in worker thread).

        Args:
            job: Job dict to execute
        """
        job_id = job.get('id')
        start_time = datetime.now()
        started_at = start_time.isoformat()

        # Track as active
        with self._lock:
            self._active_jobs[job_id] = {
                'status': 'running',
                'started_at': started_at,
                'job': job
            }

        # Generate log filename
        log_filename = self._generate_log_filename(job_id, job.get('playbook', 'unknown'))
        log_path = os.path.join(self.logs_dir, log_filename)

        # Notify primary that job started
        start_response = self.api.start_job(job_id, self.worker_id, log_filename)
        if not start_response.success:
            print(f"Warning: Failed to notify job start: {start_response.error}")

        # Execute the playbook
        exit_code, error_message = self._execute_playbook(job, log_path)

        end_time = datetime.now()
        completed_at = end_time.isoformat()

        # Calculate duration
        duration_seconds = (end_time - start_time).total_seconds()

        # Remove from active jobs
        with self._lock:
            self._active_jobs.pop(job_id, None)

        # Read log content for upload to primary
        log_content = None
        try:
            if os.path.exists(log_path):
                with open(log_path, 'r') as f:
                    log_content = f.read()
        except Exception as e:
            print(f"Warning: Could not read log file for upload: {e}")

        # Create result
        result = JobResult(
            job_id=job_id,
            success=(exit_code == 0),
            exit_code=exit_code,
            log_file=log_filename,
            error_message=error_message,
            started_at=started_at,
            completed_at=completed_at
        )

        # Report completion to primary with full details
        complete_response = self.api.complete_job(
            job_id,
            self.worker_id,
            exit_code,
            log_file=log_filename,
            log_content=log_content,
            error_message=error_message,
            duration_seconds=duration_seconds
        )

        if not complete_response.success:
            print(f"Warning: Failed to report job completion: {complete_response.error}")

        # Notify callbacks
        for callback in self._on_complete_callbacks:
            try:
                callback(result)
            except Exception as e:
                print(f"Error in completion callback: {e}")

        print(f"Job {job_id} completed with exit code {exit_code} (duration: {duration_seconds:.1f}s)")

    def execute_job(self, job: Dict, async_exec: bool = True) -> Optional[JobResult]:
        """
        Execute a job.

        Args:
            job: Job dict to execute
            async_exec: If True, run in background thread

        Returns:
            JobResult if sync execution, None if async
        """
        job_id = job.get('id')
        print(f"Executing job {job_id}: {job.get('playbook')}")

        if async_exec:
            thread = threading.Thread(
                target=self._run_job,
                args=(job,),
                daemon=True,
                name=f"job-{job_id[:8]}"
            )
            thread.start()
            return None
        else:
            self._run_job(job)
            return None

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a running job.

        Note: This only removes tracking - actual process termination
        would require storing process handles.

        Args:
            job_id: Job ID to cancel

        Returns:
            True if job was being tracked
        """
        with self._lock:
            if job_id in self._active_jobs:
                self._active_jobs.pop(job_id)
                return True
        return False

    def wait_for_jobs(self, timeout: float = None) -> bool:
        """
        Wait for all active jobs to complete.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            True if all jobs completed, False if timeout
        """
        import time
        start = time.time()

        while self.active_job_count > 0:
            if timeout and (time.time() - start) > timeout:
                return False
            time.sleep(0.5)

        return True


class JobPoller:
    """
    Polls for assigned jobs and dispatches them to executor.
    """

    def __init__(self, api_client: PrimaryAPIClient, worker_id: str,
                 executor: JobExecutor, max_concurrent: int = 2):
        """
        Initialize job poller.

        Args:
            api_client: API client for primary server
            worker_id: This worker's ID
            executor: Job executor instance
            max_concurrent: Maximum concurrent jobs
        """
        self.api = api_client
        self.worker_id = worker_id
        self.executor = executor
        self.max_concurrent = max_concurrent

        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._processed_jobs: set = set()

    def poll_once(self) -> List[Dict]:
        """
        Poll for assigned jobs once and execute any found.

        Returns:
            List of jobs that were started
        """
        # Check capacity
        available_slots = self.max_concurrent - self.executor.active_job_count
        if available_slots <= 0:
            return []

        # Get assigned jobs
        response = self.api.get_assigned_jobs(self.worker_id)
        if not response.success:
            return []

        jobs_data = response.data
        if isinstance(jobs_data, dict):
            jobs = jobs_data.get('jobs', [])
        elif isinstance(jobs_data, list):
            jobs = jobs_data
        else:
            jobs = []

        started_jobs = []
        for job in jobs[:available_slots]:
            job_id = job.get('id')

            # Skip already processed jobs
            if job_id in self._processed_jobs:
                continue

            self._processed_jobs.add(job_id)
            self.executor.execute_job(job, async_exec=True)
            started_jobs.append(job)

        return started_jobs

    def _poll_loop(self, interval: float):
        """Background polling loop."""
        import time

        while self._running:
            try:
                self.poll_once()
            except Exception as e:
                print(f"Error in job poll: {e}")

            time.sleep(interval)

    def start(self, poll_interval: float = 5.0):
        """
        Start background job polling.

        Args:
            poll_interval: Seconds between polls
        """
        if self._running:
            return

        self._running = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            args=(poll_interval,),
            daemon=True,
            name="job-poller"
        )
        self._poll_thread.start()

    def stop(self):
        """Stop background polling."""
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
            self._poll_thread = None
