"""
API Client for Primary Server

Handles HTTP communication with the primary server for:
- Worker registration
- Job polling
- Status check-ins
- Content sync
"""

import json
import requests
from typing import Dict, List, Optional, Tuple
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

    def __init__(self, server_url: str, timeout: int = 30):
        """
        Initialize API client.

        Args:
            server_url: Base URL of primary server (e.g., http://primary:3001)
            timeout: Request timeout in seconds
        """
        self.server_url = server_url.rstrip('/')
        self.timeout = timeout
        self.worker_id: Optional[str] = None

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
            f'/api/workers/{worker_id}/jobs',
            params={'status': 'assigned'}
        )

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

    def complete_job(self, job_id: str, result: Dict) -> APIResponse:
        """
        Report job completion.

        Args:
            job_id: Job ID
            result: Completion data (status, exit_code, log, etc.)

        Returns:
            APIResponse
        """
        return self._request(
            'POST',
            f'/api/jobs/{job_id}/complete',
            json=result
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
            response = requests.get(url, timeout=120, stream=True)
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
            response = requests.get(url, timeout=30)
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
                timeout=5
            )
            return response.ok
        except requests.exceptions.RequestException:
            return False
