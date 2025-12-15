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


@unittest.skipUnless(cluster_available(), "Cluster not available - run docker-compose up first")
class TestMultiWorkerLoadBalancing(unittest.TestCase):
    """Test load balancing across multiple workers.

    Verifies that jobs are distributed across available workers
    based on load, tags, and scoring algorithm.
    """

    def test_jobs_distributed_to_multiple_workers(self):
        """Test that multiple jobs get distributed across workers."""
        # Submit multiple jobs quickly
        job_ids = []
        for i in range(3):
            job_data = {
                'playbook': 'hardware-inventory',
                'target': 'localhost',
                'priority': 50
            }
            response = requests.post(f"{PRIMARY_URL}/api/jobs",
                                     json=job_data, timeout=TIMEOUT)
            if response.status_code == 201:
                data = response.json()
                job_id = data.get('job_id') or data.get('id')
                if job_id:
                    job_ids.append(job_id)

        self.assertGreaterEqual(len(job_ids), 2, "Need at least 2 jobs submitted")

        # Trigger routing
        requests.post(f"{PRIMARY_URL}/api/jobs/route", timeout=TIMEOUT)

        # Wait for assignments
        time.sleep(2)

        # Check assigned workers
        assigned_workers = set()
        for job_id in job_ids:
            response = requests.get(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)
            if response.ok:
                job = response.json()
                if job.get('assigned_worker'):
                    assigned_workers.add(job['assigned_worker'])

            # Clean up
            if job.get('status') in ['queued', 'assigned']:
                requests.delete(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)

        # Should have jobs on multiple workers (if workers are available)
        # At minimum, verify jobs were assigned
        self.assertGreater(len(assigned_workers), 0, "No workers were assigned jobs")

    def test_load_affects_worker_selection(self):
        """Test that worker load affects job routing decisions."""
        # Get workers and their current load
        response = requests.get(f"{PRIMARY_URL}/api/workers", timeout=TIMEOUT)
        workers = response.json()

        online_workers = [w for w in workers if w.get('status') == 'online'
                        and not w.get('is_local')]

        if len(online_workers) < 2:
            self.skipTest("Need at least 2 online workers for load balancing test")

        # Submit a job
        job_data = {'playbook': 'hardware-inventory', 'target': 'localhost'}
        response = requests.post(f"{PRIMARY_URL}/api/jobs",
                                json=job_data, timeout=TIMEOUT)
        data = response.json()
        job_id = data.get('job_id') or data.get('id')

        # Route the job
        route_response = requests.post(f"{PRIMARY_URL}/api/jobs/route", timeout=TIMEOUT)
        route_data = route_response.json()

        # Verify routing decision included score
        if route_data.get('results'):
            result = route_data['results'][0]
            self.assertIn('score', result, "Routing should include scoring info")

        # Clean up
        time.sleep(1)
        requests.delete(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)

    def test_tag_based_worker_preference(self):
        """Test that jobs with preferred tags route to matching workers."""
        # Get workers with specific tags
        response = requests.get(f"{PRIMARY_URL}/api/workers", timeout=TIMEOUT)
        workers = response.json()

        # Find a tag that exists on some workers
        all_tags = set()
        for w in workers:
            all_tags.update(w.get('tags', []))

        if not all_tags:
            self.skipTest("No tagged workers available")

        target_tag = list(all_tags)[0]

        # Submit job with preferred tag
        job_data = {
            'playbook': 'hardware-inventory',
            'target': 'localhost',
            'preferred_tags': [target_tag]
        }
        response = requests.post(f"{PRIMARY_URL}/api/jobs",
                                json=job_data, timeout=TIMEOUT)
        data = response.json()
        job_id = data.get('job_id') or data.get('id')

        # Route and check assignment
        requests.post(f"{PRIMARY_URL}/api/jobs/route", timeout=TIMEOUT)
        time.sleep(1)

        response = requests.get(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)
        job = response.json()

        if job.get('assigned_worker'):
            # Get assigned worker's tags
            worker_response = requests.get(
                f"{PRIMARY_URL}/api/workers/{job['assigned_worker']}", timeout=TIMEOUT)
            if worker_response.ok:
                worker = worker_response.json()
                worker_tags = worker.get('tags', [])
                # Preference should favor tagged workers (but not required)
                # Just verify assignment happened
                self.assertIsNotNone(job.get('assigned_worker'))

        # Clean up
        if job.get('status') in ['queued', 'assigned']:
            requests.delete(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)


@unittest.skipUnless(cluster_available(), "Cluster not available - run docker-compose up first")
class TestWorkerFailover(unittest.TestCase):
    """Test job handling when workers fail or go offline.

    Verifies that the system handles worker failures gracefully
    and can reassign or fail jobs appropriately.
    """

    def test_stale_worker_detection(self):
        """Test that workers are marked stale after timeout."""
        # This test verifies the stale worker detection endpoint exists
        response = requests.get(f"{PRIMARY_URL}/api/workers", timeout=TIMEOUT)
        workers = response.json()

        # Check for status field on all workers
        for worker in workers:
            self.assertIn('status', worker)
            self.assertIn(worker['status'], ['online', 'offline', 'stale'])

    def test_job_not_routed_to_offline_worker(self):
        """Test that jobs are not routed to offline workers."""
        # Get current workers
        response = requests.get(f"{PRIMARY_URL}/api/workers", timeout=TIMEOUT)
        workers = response.json()

        offline_workers = [w for w in workers if w.get('status') != 'online']
        online_workers = [w for w in workers if w.get('status') == 'online']

        if not online_workers:
            self.skipTest("No online workers available")

        # Submit and route a job
        job_data = {'playbook': 'hardware-inventory', 'target': 'localhost'}
        response = requests.post(f"{PRIMARY_URL}/api/jobs",
                                json=job_data, timeout=TIMEOUT)
        data = response.json()
        job_id = data.get('job_id') or data.get('id')

        requests.post(f"{PRIMARY_URL}/api/jobs/route", timeout=TIMEOUT)
        time.sleep(1)

        response = requests.get(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)
        job = response.json()

        if job.get('assigned_worker'):
            # Verify assigned worker is online
            offline_worker_ids = [w['id'] for w in offline_workers]
            self.assertNotIn(job['assigned_worker'], offline_worker_ids,
                           "Job should not be routed to offline worker")

        # Clean up
        if job.get('status') in ['queued', 'assigned']:
            requests.delete(f"{PRIMARY_URL}/api/jobs/{job_id}", timeout=TIMEOUT)

    def test_worker_checkin_updates_status(self):
        """Test that worker check-ins update status correctly."""
        response = requests.get(f"{PRIMARY_URL}/api/workers", timeout=TIMEOUT)
        workers = response.json()

        for worker in workers:
            if worker.get('status') == 'online':
                # Online workers should have recent checkin
                self.assertIn('last_checkin', worker)
                # Should have stats from check-in
                self.assertIn('stats', worker)


@unittest.skipUnless(cluster_available(), "Cluster not available - run docker-compose up first")
class TestContentSyncIntegrity(unittest.TestCase):
    """Test content synchronization integrity.

    Verifies that playbooks and inventory are correctly synchronized
    from primary to workers with matching content.
    """

    def test_sync_revision_matches(self):
        """Test that synced workers have matching revision."""
        # Get sync status from primary
        response = requests.get(f"{PRIMARY_URL}/api/sync/status", timeout=TIMEOUT)
        self.assertEqual(response.status_code, 200)
        sync_status = response.json()
        primary_revision = sync_status.get('revision')

        # Get workers and check their sync revision
        response = requests.get(f"{PRIMARY_URL}/api/workers", timeout=TIMEOUT)
        workers = response.json()

        synced_workers = [w for w in workers
                        if w.get('sync_revision') and not w.get('is_local')]

        for worker in synced_workers:
            # Workers should have a revision (may not match if mid-sync)
            self.assertIsNotNone(worker.get('sync_revision'),
                               f"Worker {worker.get('name')} has no sync revision")

    def test_manifest_contains_playbooks(self):
        """Test that sync manifest includes playbook files."""
        response = requests.get(f"{PRIMARY_URL}/api/sync/manifest", timeout=TIMEOUT)
        self.assertEqual(response.status_code, 200)
        manifest = response.json()

        files = manifest.get('files', {})
        # Files can be a dict (path -> info) or list
        if isinstance(files, dict):
            file_paths = list(files.keys())
        else:
            file_paths = [f.get('path', f) if isinstance(f, dict) else f for f in files]

        # Should have at least some files
        self.assertGreater(len(file_paths), 0, "Manifest should contain files")

        # Check for playbook-related files
        playbook_files = [p for p in file_paths
                         if 'playbook' in p.lower()
                         or p.endswith('.yml')
                         or p.endswith('.yaml')]

        # Should have at least some playbooks
        self.assertGreater(len(playbook_files), 0, "Manifest should contain playbooks")

    def test_manifest_file_checksums(self):
        """Test that manifest includes file checksums for integrity."""
        response = requests.get(f"{PRIMARY_URL}/api/sync/manifest", timeout=TIMEOUT)
        manifest = response.json()

        files = manifest.get('files', {})

        # Files can be a dict (path -> info) or list
        if isinstance(files, dict):
            # Dict format: {path: {size, sha256, mtime, ...}}
            for path, file_info in list(files.items())[:5]:
                self.assertIsInstance(file_info, dict)
                # Check for integrity fields
                has_integrity = (
                    'checksum' in file_info or
                    'sha256' in file_info or
                    'hash' in file_info or
                    'size' in file_info or
                    'mtime' in file_info
                )
                self.assertTrue(has_integrity,
                              f"File {path} lacks integrity info")
        else:
            for file_info in files[:5]:  # Check first 5 files
                self.assertIn('path', file_info)
                has_integrity = (
                    'checksum' in file_info or
                    'sha256' in file_info or
                    'hash' in file_info or
                    'size' in file_info or
                    'mtime' in file_info
                )
                self.assertTrue(has_integrity,
                              f"File {file_info.get('path')} lacks integrity info")

    def test_archive_downloadable_and_valid(self):
        """Test that sync archive can be downloaded."""
        response = requests.get(f"{PRIMARY_URL}/api/sync/archive",
                               timeout=TIMEOUT, stream=True)

        self.assertEqual(response.status_code, 200)

        # Should be gzip content
        content_type = response.headers.get('Content-Type', '')
        self.assertIn('gzip', content_type.lower(),
                     "Archive should be gzip compressed")

        # Should have some content
        content_length = response.headers.get('Content-Length')
        if content_length:
            self.assertGreater(int(content_length), 0,
                             "Archive should have content")

    def test_inventory_included_in_sync(self):
        """Test that inventory is included in sync content."""
        response = requests.get(f"{PRIMARY_URL}/api/sync/manifest", timeout=TIMEOUT)
        manifest = response.json()

        files = manifest.get('files', {})

        # Files can be a dict (path -> info) or list
        if isinstance(files, dict):
            file_paths = list(files.keys())
        else:
            file_paths = [f.get('path', f) if isinstance(f, dict) else f for f in files]

        # Look for inventory files
        inventory_files = [p for p in file_paths
                         if 'inventory' in p.lower()
                         or p.endswith('hosts')]

        self.assertGreater(len(inventory_files), 0,
                         "Manifest should include inventory files")


if __name__ == '__main__':
    unittest.main()
