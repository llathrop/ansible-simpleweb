"""
API Client for Primary Server

Handles HTTP communication with the primary server for:
- Worker registration
- Job polling
- Status check-ins
- Content sync

Supports HTTPS with optional certificate verification.
"""

import os
import json
import requests
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass


@dataclass
class APIResponse:
    """Wrapper for API responses."""
    success: bool
    status_code: int
    data: Optional[Dict] = None
    error: Optional[str] = None


class PrimaryAPIClient:
    """HTTP client for primary server API."""

    def __init__(self, server_url: str, timeout: int = 30,
                 ssl_verify: Union[bool, str] = None):
        """
        Initialize API client.

        Args:
            server_url: Base URL of primary server (e.g., http://primary:3001 or https://primary:3443)
            timeout: Request timeout in seconds
            ssl_verify: SSL verification:
                - True: Verify SSL certificate (default for https)
                - False: Disable SSL verification (insecure, for self-signed certs)
                - str: Path to CA certificate file
                - None: Auto-detect from SSL_VERIFY env var
        """
        self.server_url = server_url.rstrip('/')
        self.timeout = timeout
        self.worker_id: Optional[str] = None

        # Configure SSL verification
        if ssl_verify is None:
            # Auto-detect from environment
            verify_env = os.environ.get('SSL_VERIFY', 'true').lower()
            if verify_env in ('false', '0', 'no', 'disable'):
                self.ssl_verify = False
            elif verify_env in ('true', '1', 'yes', 'enable'):
                self.ssl_verify = True
            else:
                # Treat as path to CA certificate
                self.ssl_verify = verify_env if os.path.exists(verify_env) else True
        else:
            self.ssl_verify = ssl_verify

    def _request(self, method: str, endpoint: str, **kwargs) -> APIResponse:
        """
        Make an HTTP request to the API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., /api/workers/register)
            **kwargs: Additional arguments for requests

        Returns:
            APIResponse with success status and data/error
        """
        url = f"{self.server_url}{endpoint}"
        kwargs.setdefault('timeout', self.timeout)
        kwargs.setdefault('verify', self.ssl_verify)

        try:
            response = requests.request(method, url, **kwargs)

            # Try to parse JSON response
            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError):
                data = None

            if response.ok:
                return APIResponse(
                    success=True,
                    status_code=response.status_code,
                    data=data
                )
            else:
                error_msg = data.get('error') if data else response.text
                return APIResponse(
                    success=False,
                    status_code=response.status_code,
                    data=data,
                    error=error_msg
                )

        except requests.exceptions.ConnectionError as e:
            return APIResponse(
                success=False,
                status_code=0,
                error=f"Connection error: {str(e)}"
            )
        except requests.exceptions.Timeout:
            return APIResponse(
                success=False,
                status_code=0,
                error="Request timed out"
            )
        except requests.exceptions.RequestException as e:
            return APIResponse(
                success=False,
                status_code=0,
                error=f"Request failed: {str(e)}"
            )

    # =========================================================================
    # Worker Registration
    # =========================================================================

    def register(self, name: str, tags: List[str], token: str) -> APIResponse:
        """
        Register this worker with the primary server.

        Args:
            name: Worker name
            tags: Worker capability tags
            token: Registration token

        Returns:
            APIResponse with worker_id and sync info on success
        """
        response = self._request(
            'POST',
            '/api/workers/register',
            json={
                'name': name,
                'tags': tags,
                'token': token
            }
        )

        if response.success and response.data:
            self.worker_id = response.data.get('worker_id')

        return response

    def checkin(self, worker_id: str, checkin_data: Dict) -> APIResponse:
        """
        Send check-in to primary server.

        Args:
            worker_id: This worker's ID
            checkin_data: Check-in payload with stats, active jobs, etc.

        Returns:
            APIResponse
        """
        return self._request(
            'POST',
            f'/api/workers/{worker_id}/checkin',
            json=checkin_data
        )

    def get_worker(self, worker_id: str) -> APIResponse:
        """Get worker details."""
        return self._request('GET', f'/api/workers/{worker_id}')

    # =========================================================================
    # Job Operations
    # =========================================================================

    def get_assigned_jobs(self, worker_id: str) -> APIResponse:
        """
        Get jobs assigned to this worker.

        Args:
            worker_id: This worker's ID

        Returns:
            APIResponse with list of assigned jobs
        """
        return self._request(
            'GET',
            '/api/jobs',
            params={'worker': worker_id, 'status': 'assigned'}
        )

    def start_job(self, job_id: str, worker_id: str, log_file: str = None) -> APIResponse:
        """
        Mark a job as started.

        Args:
            job_id: Job ID
            worker_id: This worker's ID
            log_file: Optional log file name

        Returns:
            APIResponse
        """
        data = {'worker_id': worker_id}
        if log_file:
            data['log_file'] = log_file
        return self._request('POST', f'/api/jobs/{job_id}/start', json=data)

    def update_job_status(self, job_id: str, status: str, **kwargs) -> APIResponse:
        """
        Update job status.

        Args:
            job_id: Job ID
            status: New status
            **kwargs: Additional fields to update

        Returns:
            APIResponse
        """
        data = {'status': status, **kwargs}
        return self._request(
            'POST',
            f'/api/jobs/{job_id}/status',
            json=data
        )

    def stream_log(self, job_id: str, worker_id: str, content: str,
                   append: bool = True) -> APIResponse:
        """
        Stream log content to primary during job execution.

        This enables live log viewing in the web UI for cluster jobs.
        Call periodically during playbook execution to send log chunks.

        Args:
            job_id: Job ID
            worker_id: This worker's ID
            content: Log content chunk to send
            append: True to append to existing log, False to replace

        Returns:
            APIResponse with bytes_written on success
        """
        return self._request(
            'POST',
            f'/api/jobs/{job_id}/log/stream',
            json={
                'worker_id': worker_id,
                'content': content,
                'append': append
            }
        )

    def complete_job(self, job_id: str, worker_id: str, exit_code: int,
                     log_file: str = None, log_content: str = None,
                     error_message: str = None, duration_seconds: float = None,
                     cmdb_facts: Dict = None, checkin: Dict = None) -> APIResponse:
        """
        Report job completion with full results.

        Args:
            job_id: Job ID
            worker_id: This worker's ID
            exit_code: Process exit code (0 = success)
            log_file: Log file name
            log_content: Full log content (optional - for log upload)
            error_message: Error message if failed
            duration_seconds: Job execution duration
            cmdb_facts: CMDB facts collected during execution
            checkin: Piggyback checkin data

        Returns:
            APIResponse with completion status and worker stats update info
        """
        data = {
            'worker_id': worker_id,
            'exit_code': exit_code
        }
        if log_file:
            data['log_file'] = log_file
        if log_content:
            data['log_content'] = log_content
        if error_message:
            data['error_message'] = error_message
        if duration_seconds is not None:
            data['duration_seconds'] = duration_seconds
        if cmdb_facts:
            data['cmdb_facts'] = cmdb_facts
        if checkin:
            data['checkin'] = checkin

        return self._request(
            'POST',
            f'/api/jobs/{job_id}/complete',
            json=data
        )

    # =========================================================================
    # Content Sync
    # =========================================================================

    def get_sync_revision(self) -> APIResponse:
        """Get current content revision from primary."""
        return self._request('GET', '/api/sync/revision')

    def get_sync_manifest(self) -> APIResponse:
        """Get content file manifest."""
        return self._request('GET', '/api/sync/manifest')

    def get_sync_status(self) -> APIResponse:
        """Get content repository status."""
        return self._request('GET', '/api/sync/status')

    def download_archive(self, output_path: str) -> Tuple[bool, str]:
        """
        Download content archive.

        Args:
            output_path: Path to save the archive

        Returns:
            Tuple of (success, error_message)
        """
        url = f"{self.server_url}/api/sync/archive"
        try:
            response = requests.get(url, timeout=120, stream=True, verify=self.ssl_verify)
            if response.ok:
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True, ''
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, str(e)

    def download_file(self, filepath: str, output_path: str) -> Tuple[bool, str]:
        """
        Download a single file.

        Args:
            filepath: Relative path in content repo
            output_path: Local path to save file

        Returns:
            Tuple of (success, error_message)
        """
        url = f"{self.server_url}/api/sync/file/{filepath}"
        try:
            response = requests.get(url, timeout=30, verify=self.ssl_verify)
            if response.ok:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True, ''
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            return False, str(e)

    # =========================================================================
    # Cluster Status
    # =========================================================================

    def get_cluster_status(self) -> APIResponse:
        """Get cluster status summary."""
        return self._request('GET', '/api/cluster/status')

    def health_check(self) -> bool:
        """
        Check if primary server is reachable.

        Returns:
            True if server responds, False otherwise
        """
        try:
            response = requests.get(
                f"{self.server_url}/api/sync/status",
                timeout=5,
                verify=self.ssl_verify
            )
            return response.ok
        except requests.exceptions.RequestException:
            return False
