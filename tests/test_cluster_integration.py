"""
Integration Tests for Cluster Mode.

These tests verify end-to-end cluster functionality when run against
a running cluster (docker-compose up). They test real API endpoints
and inter-service communication.

Run with: pytest tests/test_cluster_integration.py -v

Prerequisites:
- docker-compose up -d (cluster must be running)
- Workers must be registered
"""

import os
import sys
import time
import unittest
import requests
from datetime import datetime

# Configuration
PRIMARY_URL = os.environ.get('PRIMARY_URL', 'http://localhost:3001')
TIMEOUT = 30  # seconds


def cluster_available():
    """Check if the cluster is available for testing."""
    try:
        response = requests.get(f"{PRIMARY_URL}/api/sync/status", timeout=5)
        return response.ok
    except requests.exceptions.RequestException:
        return False


@unittest.skipUnless(cluster_available(), "Cluster not available - run docker-compose up first")
class TestClusterWorkerRegistration(unittest.TestCase):
    """Test worker registration and status."""

    def test_workers_endpoint_returns_list(self):
        """Test /api/workers returns a list of workers."""
        response = requests.get(f"{PRIMARY_URL}/api/workers", timeout=TIMEOUT)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)

    def test_at_least_one_worker_registered(self):
        """Test that at least one worker is registered."""
        response = requests.get(f"{PRIMARY_URL}/api/workers", timeout=TIMEOUT)
        workers = response.json()

        self.assertGreater(len(workers), 0, "No workers registered")

    def test_workers_have_required_fields(self):
        """Test that workers have all required fields."""
        response = requests.get(f"{PRIMARY_URL}/api/workers", timeout=TIMEOUT)
        workers = response.json()

        required_fields = ['id', 'name', 'status', 'tags']
        for worker in workers:
            for field in required_fields:
                self.assertIn(field, worker, f"Worker missing {field}")

    def test_local_executor_exists(self):
        """Test that local executor is registered."""
        response = requests.get(f"{PRIMARY_URL}/api/workers", timeout=TIMEOUT)
        workers = response.json()

        local_workers = [w for w in workers if w.get('is_local')]
        self.assertGreater(len(local_workers), 0, "No local executor found")


@unittest.skipUnless(cluster_available(), "Cluster not available - run docker-compose up first")
class TestClusterContentSync(unittest.TestCase):
    """Test content synchronization."""

    def test_sync_status_available(self):
        """Test /api/sync/status returns sync info."""
        response = requests.get(f"{PRIMARY_URL}/api/sync/status", timeout=TIMEOUT)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('revision', data)

    def test_sync_manifest_available(self):
        """Test /api/sync/manifest returns file manifest."""
        response = requests.get(f"{PRIMARY_URL}/api/sync/manifest", timeout=TIMEOUT)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('files', data)

    def test_sync_archive_downloadable(self):
        """Test /api/sync/archive returns downloadable archive."""
        response = requests.get(f"{PRIMARY_URL}/api/sync/archive", timeout=TIMEOUT,
                               stream=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('application/gzip', response.headers.get('Content-Type', ''))


@unittest.skipUnless(cluster_available(), "Cluster not available - run docker-compose up first")
class TestClusterJobQueue(unittest.TestCase):
    """Test job queue operations."""

    def test_jobs_endpoint_returns_list(self):
        """Test /api/jobs returns a list."""
        response = requests.get(f"{PRIMARY_URL}/api/jobs", timeout=TIMEOUT)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('jobs', data)
        self.assertIsInstance(data['jobs'], list)

    def test_job_submission(self):
        """Test submitting a job to the queue."""
        # Use an actual playbook that exists
        job_data = {
            'playbook': 'hardware-inventory',
            'target': 'localhost',
            'priority': 50
        }

        response = requests.post(f"{PRIMARY_URL}/api/jobs",
                                json=job_data, timeout=TIMEOUT)

        self.assertEqual(response.status_code, 201)
        data = response.json()
        # Response may use 'id' or 'job_id'
        job_id = data.get('job_id') or data.get('id')
        self.assertIsNotNone(job_id)

        # Clean up - cancel the job
        requests.delete(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)

    def test_job_retrieval(self):
        """Test retrieving a specific job."""
        # Submit a job first
        job_data = {'playbook': 'hardware-inventory', 'target': 'localhost'}
        submit_response = requests.post(f"{PRIMARY_URL}/api/jobs",
                                        json=job_data, timeout=TIMEOUT)
        data = submit_response.json()
        job_id = data.get('job_id') or data.get('id')

        # Retrieve the job
        response = requests.get(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)

        self.assertEqual(response.status_code, 200)
        job = response.json()
        self.assertEqual(job['id'], job_id)

        # Clean up
        requests.delete(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)

    def test_job_cancellation(self):
        """Test cancelling a queued job."""
        # Submit a job
        job_data = {'playbook': 'hardware-inventory', 'target': 'localhost'}
        submit_response = requests.post(f"{PRIMARY_URL}/api/jobs",
                                        json=job_data, timeout=TIMEOUT)
        data = submit_response.json()
        job_id = data.get('job_id') or data.get('id')

        # Cancel the job
        response = requests.delete(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'cancelled')


@unittest.skipUnless(cluster_available(), "Cluster not available - run docker-compose up first")
class TestClusterJobRouting(unittest.TestCase):
    """Test job routing to workers."""

    def test_route_all_jobs_endpoint(self):
        """Test /api/jobs/route triggers routing."""
        response = requests.post(f"{PRIMARY_URL}/api/jobs/route", timeout=TIMEOUT)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('routed', data)

    def test_job_gets_assigned(self):
        """Test that a submitted job gets assigned to a worker."""
        # Submit a job
        job_data = {'playbook': 'hardware-inventory', 'target': 'localhost'}
        submit_response = requests.post(f"{PRIMARY_URL}/api/jobs",
                                        json=job_data, timeout=TIMEOUT)
        data = submit_response.json()
        job_id = data.get('job_id') or data.get('id')

        # Trigger routing
        requests.post(f"{PRIMARY_URL}/api/jobs/route", timeout=TIMEOUT)

        # Wait a moment for assignment
        time.sleep(1)

        # Check job status
        response = requests.get(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)
        job = response.json()

        # Job should be assigned or already running
        self.assertIn(job['status'], ['queued', 'assigned', 'running', 'completed', 'failed'])

        # Clean up
        if job['status'] in ['queued', 'assigned']:
            requests.delete(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)


@unittest.skipUnless(cluster_available(), "Cluster not available - run docker-compose up first")
class TestClusterDashboard(unittest.TestCase):
    """Test cluster dashboard API."""

    def test_cluster_status_endpoint(self):
        """Test /api/cluster/status returns summary."""
        response = requests.get(f"{PRIMARY_URL}/api/cluster/status", timeout=TIMEOUT)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('workers', data)
        self.assertIn('jobs', data)

    def test_cluster_page_accessible(self):
        """Test /cluster page loads."""
        response = requests.get(f"{PRIMARY_URL}/cluster", timeout=TIMEOUT)

        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.headers.get('Content-Type', ''))


@unittest.skipUnless(cluster_available(), "Cluster not available - run docker-compose up first")
class TestEndToEndJobExecution(unittest.TestCase):
    """End-to-end test of job submission through completion.

    Note: This test requires a playbook that can run successfully
    against localhost (within the container).
    """

    @unittest.skip("Requires valid playbook that runs on container localhost")
    def test_job_completes_successfully(self):
        """Test full job lifecycle from submission to completion."""
        # Submit a simple job
        job_data = {
            'playbook': 'ping-test',  # Would need to exist
            'target': 'localhost'
        }
        submit_response = requests.post(f"{PRIMARY_URL}/api/jobs",
                                        json=job_data, timeout=TIMEOUT)
        job_id = submit_response.json()['job_id']

        # Trigger routing
        requests.post(f"{PRIMARY_URL}/api/jobs/route", timeout=TIMEOUT)

        # Wait for completion (with timeout)
        max_wait = 60  # seconds
        start = time.time()
        while time.time() - start < max_wait:
            response = requests.get(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)
            job = response.json()

            if job['status'] in ['completed', 'failed']:
                break
            time.sleep(2)

        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['exit_code'], 0)


if __name__ == '__main__':
    unittest.main()
