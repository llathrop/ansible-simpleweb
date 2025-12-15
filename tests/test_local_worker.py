"""
Unit tests for Local Executor as Lowest-Priority Worker (Feature 12).

Tests the local worker functionality including:
- Local worker initialization
- Priority boost application
- Job routing prefers remote workers
- Local worker fallback when no remote workers available
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.storage.flatfile import FlatFileStorage
from web.job_router import JobRouter, WorkerScore


class TestLocalWorkerInitialization(unittest.TestCase):
    """Test local worker initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_local_worker_has_correct_id(self):
        """Test local worker ID is __local__."""
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True
        }
        self.storage.save_worker(local_worker)

        worker = self.storage.get_worker('__local__')
        self.assertEqual(worker['id'], '__local__')

    def test_local_worker_has_negative_priority_boost(self):
        """Test local worker has large negative priority boost."""
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True
        }
        self.storage.save_worker(local_worker)

        worker = self.storage.get_worker('__local__')
        self.assertEqual(worker['priority_boost'], -1000)

    def test_local_worker_is_local_flag(self):
        """Test local worker has is_local flag."""
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True
        }
        self.storage.save_worker(local_worker)

        worker = self.storage.get_worker('__local__')
        self.assertTrue(worker['is_local'])

    def test_remote_worker_no_priority_penalty(self):
        """Test remote workers have no priority penalty."""
        remote_worker = {
            'id': 'remote-1',
            'name': 'remote-worker',
            'tags': ['web'],
            'priority_boost': 0,
            'status': 'online',
            'is_local': False
        }
        self.storage.save_worker(remote_worker)

        worker = self.storage.get_worker('remote-1')
        self.assertEqual(worker['priority_boost'], 0)
        self.assertFalse(worker['is_local'])


class TestLocalWorkerPriorityScoring(unittest.TestCase):
    """Test local worker priority in job routing."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)
        self.router = JobRouter(self.storage)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_priority_boost_applied_to_score(self):
        """Test priority boost is applied to total score."""
        # Local worker with -1000 boost
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['web'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        job = {
            'id': 'test-job',
            'playbook': 'test.yml',
            'target': 'all',
            'required_tags': [],
            'preferred_tags': []
        }

        score = self.router.score_worker(local_worker, job)

        # Score should be negative due to -1000 boost
        self.assertLess(score.total_score, 0)
        self.assertEqual(score.priority_boost, -1000)

    def test_remote_worker_scores_higher_than_local(self):
        """Test remote worker always scores higher than local."""
        # Local worker
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['web'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        # Remote worker
        remote_worker = {
            'id': 'remote-1',
            'name': 'remote-worker',
            'tags': ['web'],
            'priority_boost': 0,
            'status': 'online',
            'is_local': False,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(remote_worker)

        job = {
            'id': 'test-job',
            'playbook': 'test.yml',
            'target': 'all',
            'required_tags': [],
            'preferred_tags': []
        }

        local_score = self.router.score_worker(local_worker, job)
        remote_score = self.router.score_worker(remote_worker, job)

        self.assertGreater(remote_score.total_score, local_score.total_score)

    def test_best_worker_prefers_remote(self):
        """Test find_best_worker prefers remote over local."""
        # Local worker
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['web'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        # Remote worker
        remote_worker = {
            'id': 'remote-1',
            'name': 'remote-worker',
            'tags': ['web'],
            'priority_boost': 0,
            'status': 'online',
            'is_local': False,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(remote_worker)

        job = {
            'id': 'test-job',
            'playbook': 'test.yml',
            'target': 'all',
            'status': 'queued',
            'required_tags': [],
            'preferred_tags': []
        }
        self.storage.save_job(job)

        result = self.router.find_best_worker(job)
        self.assertIsNotNone(result)
        worker, score = result

        self.assertEqual(worker['id'], 'remote-1')
        self.assertFalse(worker.get('is_local'))

    def test_local_worker_used_when_only_option(self):
        """Test local worker is used when it's the only available worker."""
        # Only local worker
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['web'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        job = {
            'id': 'test-job',
            'playbook': 'test.yml',
            'target': 'all',
            'status': 'queued',
            'required_tags': [],
            'preferred_tags': []
        }
        self.storage.save_job(job)

        result = self.router.find_best_worker(job)
        self.assertIsNotNone(result)
        worker, score = result

        self.assertEqual(worker['id'], '__local__')
        self.assertTrue(worker.get('is_local'))


class TestLocalWorkerTagFiltering(unittest.TestCase):
    """Test local worker respects tag requirements."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)
        self.router = JobRouter(self.storage)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_local_worker_respects_required_tags(self):
        """Test local worker is ineligible if missing required tags."""
        # Local worker without required tag
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        job = {
            'id': 'test-job',
            'playbook': 'test.yml',
            'target': 'all',
            'required_tags': ['special-capability'],
            'preferred_tags': []
        }

        score = self.router.score_worker(local_worker, job)

        self.assertFalse(score.eligible)
        self.assertIn('Missing required tags', score.reason)

    def test_local_worker_eligible_with_matching_tags(self):
        """Test local worker eligible when has required tags."""
        # Local worker with required tag
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['local', 'gpu'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        job = {
            'id': 'test-job',
            'playbook': 'test.yml',
            'target': 'all',
            'required_tags': ['gpu'],
            'preferred_tags': []
        }

        score = self.router.score_worker(local_worker, job)

        self.assertTrue(score.eligible)


class TestWorkerScoreDataclass(unittest.TestCase):
    """Test WorkerScore dataclass includes priority_boost."""

    def test_worker_score_has_priority_boost(self):
        """Test WorkerScore includes priority_boost field."""
        score = WorkerScore(
            worker_id='test',
            worker_name='Test Worker',
            total_score=50.0,
            tag_score=60.0,
            load_score=80.0,
            preference_score=20.0,
            priority_boost=-1000,
            eligible=True,
            reason="Eligible"
        )

        self.assertEqual(score.priority_boost, -1000)
        self.assertEqual(score.total_score, 50.0)


class TestJobRecommendations(unittest.TestCase):
    """Test job recommendations include local worker info."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = FlatFileStorage(self.test_dir)
        self.router = JobRouter(self.storage)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_recommendations_include_is_local(self):
        """Test recommendations show is_local flag."""
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['web'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        job = {
            'id': 'test-job',
            'playbook': 'test.yml',
            'target': 'all',
            'status': 'queued',
            'required_tags': [],
            'preferred_tags': []
        }
        self.storage.save_job(job)

        recommendations = self.router.get_worker_recommendations('test-job')

        self.assertEqual(len(recommendations), 1)
        self.assertTrue(recommendations[0]['is_local'])
        self.assertIn('priority_boost', recommendations[0]['scores'])

    def test_recommendations_sorted_by_score(self):
        """Test recommendations sorted with remote workers first."""
        # Local worker
        local_worker = {
            'id': '__local__',
            'name': 'local-executor',
            'tags': ['web'],
            'priority_boost': -1000,
            'status': 'online',
            'is_local': True,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(local_worker)

        # Remote worker
        remote_worker = {
            'id': 'remote-1',
            'name': 'remote-worker',
            'tags': ['web'],
            'priority_boost': 0,
            'status': 'online',
            'is_local': False,
            'max_concurrent_jobs': 2,
            'system_stats': {}
        }
        self.storage.save_worker(remote_worker)

        job = {
            'id': 'test-job',
            'playbook': 'test.yml',
            'target': 'all',
            'status': 'queued',
            'required_tags': [],
            'preferred_tags': []
        }
        self.storage.save_job(job)

        recommendations = self.router.get_worker_recommendations('test-job')

        self.assertEqual(len(recommendations), 2)
        # Remote should be first (higher score)
        self.assertFalse(recommendations[0]['is_local'])
        self.assertTrue(recommendations[1]['is_local'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
