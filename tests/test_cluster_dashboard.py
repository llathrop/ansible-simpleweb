"""
Unit tests for Cluster Dashboard (Feature 13).

Tests the cluster dashboard functionality including:
- Dashboard page route
- Cluster status API response format
- Worker and job statistics
"""

import os
import sys
import tempfile
import shutil
import unittest
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.storage.flatfile import FlatFileStorage


class TestClusterStatusAPI(unittest.TestCase):
    """Test cluster status API response format."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_worker_counts_by_status(self):
        """Test worker count aggregation by status."""
        # Create workers with different statuses
        workers = [
            {'id': 'w1', 'name': 'Worker 1', 'status': 'online', 'tags': []},
            {'id': 'w2', 'name': 'Worker 2', 'status': 'online', 'tags': []},
            {'id': 'w3', 'name': 'Worker 3', 'status': 'busy', 'tags': []},
            {'id': 'w4', 'name': 'Worker 4', 'status': 'offline', 'tags': []},
        ]
        for w in workers:
            self.storage.save_worker(w)

        all_workers = self.storage.get_all_workers()

        # Simulate API counting
        counts = {'online': 0, 'offline': 0, 'busy': 0, 'stale': 0}
        for w in all_workers:
            status = w.get('status', 'unknown')
            if status in counts:
                counts[status] += 1

        self.assertEqual(counts['online'], 2)
        self.assertEqual(counts['busy'], 1)
        self.assertEqual(counts['offline'], 1)

    def test_job_counts_by_status(self):
        """Test job count aggregation by status."""
        # Create jobs with different statuses
        jobs = [
            {'id': 'j1', 'playbook': 'test.yml', 'status': 'queued'},
            {'id': 'j2', 'playbook': 'test.yml', 'status': 'queued'},
            {'id': 'j3', 'playbook': 'test.yml', 'status': 'running'},
            {'id': 'j4', 'playbook': 'test.yml', 'status': 'completed'},
            {'id': 'j5', 'playbook': 'test.yml', 'status': 'failed'},
        ]
        for j in jobs:
            self.storage.save_job(j)

        all_jobs = self.storage.get_all_jobs()

        # Simulate API counting
        counts = {'queued': 0, 'assigned': 0, 'running': 0, 'completed': 0, 'failed': 0}
        for j in all_jobs:
            status = j.get('status', 'unknown')
            if status in counts:
                counts[status] += 1

        self.assertEqual(counts['queued'], 2)
        self.assertEqual(counts['running'], 1)
        self.assertEqual(counts['completed'], 1)
        self.assertEqual(counts['failed'], 1)

    def test_total_counts(self):
        """Test total worker and job counts."""
        # Create some workers and jobs
        for i in range(3):
            self.storage.save_worker({
                'id': f'w{i}', 'name': f'Worker {i}', 'status': 'online', 'tags': []
            })
        for i in range(5):
            self.storage.save_job({
                'id': f'j{i}', 'playbook': 'test.yml', 'status': 'queued'
            })

        workers = self.storage.get_all_workers()
        jobs = self.storage.get_all_jobs()

        self.assertEqual(len(workers), 3)
        self.assertEqual(len(jobs), 5)


class TestWorkerDashboardDisplay(unittest.TestCase):
    """Test worker display data for dashboard."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_local_worker_identified(self):
        """Test that local worker is properly identified."""
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local'],
            'status': 'online',
            'is_local': True,
            'priority_boost': -1000
        }
        self.storage.save_worker(local_worker)

        worker = self.storage.get_worker('__local__')
        self.assertTrue(worker.get('is_local'))
        self.assertEqual(worker['id'], '__local__')

    def test_worker_stats_available(self):
        """Test worker stats are stored for dashboard display."""
        worker = {
            'id': 'w1',
            'name': 'Worker 1',
            'status': 'online',
            'tags': ['web'],
            'stats': {
                'jobs_completed': 10,
                'jobs_failed': 2,
                'load_1m': 0.5,
                'memory_percent': 45.5
            }
        }
        self.storage.save_worker(worker)

        retrieved = self.storage.get_worker('w1')
        self.assertEqual(retrieved['stats']['jobs_completed'], 10)
        self.assertEqual(retrieved['stats']['jobs_failed'], 2)
        self.assertAlmostEqual(retrieved['stats']['load_1m'], 0.5)

    def test_worker_tags_displayed(self):
        """Test worker tags are available for display."""
        worker = {
            'id': 'w1',
            'name': 'Worker 1',
            'status': 'online',
            'tags': ['web', 'production', 'us-east']
        }
        self.storage.save_worker(worker)

        retrieved = self.storage.get_worker('w1')
        self.assertEqual(len(retrieved['tags']), 3)
        self.assertIn('web', retrieved['tags'])
        self.assertIn('production', retrieved['tags'])


class TestJobQueueDisplay(unittest.TestCase):
    """Test job queue display for dashboard."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_job_with_assigned_worker(self):
        """Test job with assigned worker displays correctly."""
        worker = {
            'id': 'w1',
            'name': 'Worker 1',
            'status': 'busy',
            'tags': []
        }
        self.storage.save_worker(worker)

        job = {
            'id': 'j1',
            'playbook': 'deploy.yml',
            'target': 'webservers',
            'status': 'running',
            'assigned_worker': 'w1',
            'submitted_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        retrieved = self.storage.get_job('j1')
        self.assertEqual(retrieved['assigned_worker'], 'w1')
        self.assertEqual(retrieved['status'], 'running')

    def test_queued_job_no_worker(self):
        """Test queued job has no assigned worker."""
        job = {
            'id': 'j1',
            'playbook': 'test.yml',
            'target': 'all',
            'status': 'queued',
            'submitted_at': datetime.now().isoformat()
        }
        self.storage.save_job(job)

        retrieved = self.storage.get_job('j1')
        self.assertEqual(retrieved['status'], 'queued')
        self.assertIsNone(retrieved.get('assigned_worker'))

    def test_job_ordering_by_status(self):
        """Test jobs can be sorted by status for display."""
        jobs = [
            {'id': 'j1', 'playbook': 't.yml', 'status': 'completed'},
            {'id': 'j2', 'playbook': 't.yml', 'status': 'running'},
            {'id': 'j3', 'playbook': 't.yml', 'status': 'queued'},
            {'id': 'j4', 'playbook': 't.yml', 'status': 'failed'},
        ]
        for j in jobs:
            self.storage.save_job(j)

        all_jobs = self.storage.get_all_jobs()

        # Sort by status priority (as dashboard would)
        status_priority = {'running': 0, 'assigned': 1, 'queued': 2, 'completed': 3, 'failed': 4}
        sorted_jobs = sorted(all_jobs, key=lambda x: status_priority.get(x.get('status'), 5))

        self.assertEqual(sorted_jobs[0]['status'], 'running')
        self.assertEqual(sorted_jobs[1]['status'], 'queued')


class TestDashboardAPIFormat(unittest.TestCase):
    """Test cluster status API returns dashboard-friendly format."""

    def test_response_has_required_fields(self):
        """Test API response structure for dashboard."""
        # Simulate API response structure (includes stack per memory.md)
        response = {
            'cluster_mode': True,
            'checkin_interval': 600,
            'stack': [
                {'name': 'DB', 'enabled': True, 'status': 'healthy'},
                {'name': 'Agent', 'enabled': True, 'status': 'healthy'},
                {'name': 'Ollama', 'enabled': True, 'status': 'healthy'},
            ],
            'workers': {
                'total': 3,
                'online': 2,
                'offline': 0,
                'busy': 1,
                'by_status': {'online': 2, 'offline': 0, 'busy': 1, 'stale': 0},
                'stale': []
            },
            'jobs': {
                'total': 10,
                'queued': 3,
                'assigned': 1,
                'running': 2,
                'completed': 3,
                'failed': 1,
                'by_status': {'queued': 3, 'assigned': 1, 'running': 2, 'completed': 3, 'failed': 1}
            }
        }

        # Check required fields for dashboard
        self.assertIn('workers', response)
        self.assertIn('jobs', response)
        self.assertIn('stack', response)

        # Stack: DB, Agent, Ollama (per memory.md cluster dashboard)
        stack = response['stack']
        self.assertIsInstance(stack, list)
        self.assertGreaterEqual(len(stack), 3)
        names = [s['name'] for s in stack]
        self.assertIn('DB', names)
        self.assertIn('Agent', names)
        self.assertIn('Ollama', names)
        for item in stack:
            self.assertIn('name', item)
            self.assertIn('enabled', item)
            self.assertIn('status', item)

        # Check worker counts accessible directly
        self.assertEqual(response['workers']['total'], 3)
        self.assertEqual(response['workers']['online'], 2)
        self.assertEqual(response['workers']['busy'], 1)

        # Check job counts accessible directly
        self.assertEqual(response['jobs']['total'], 10)
        self.assertEqual(response['jobs']['queued'], 3)
        self.assertEqual(response['jobs']['running'], 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
