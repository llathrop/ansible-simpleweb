"""
Unit tests for Job Router (Feature 7).

Tests the job routing and assignment logic.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.job_router import JobRouter, WorkerScore


class MockStorageBackend:
    """Mock storage backend for testing job routing."""

    def __init__(self):
        self.workers = {}
        self.jobs = {}

    def get_all_workers(self):
        return list(self.workers.values())

    def get_worker(self, worker_id):
        return self.workers.get(worker_id)

    def get_worker_jobs(self, worker_id, statuses=None):
        jobs = [j for j in self.jobs.values() if j.get('assigned_worker') == worker_id]
        if statuses:
            jobs = [j for j in jobs if j.get('status') in statuses]
        return jobs

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def update_job(self, job_id, updates):
        if job_id not in self.jobs:
            return False
        self.jobs[job_id].update(updates)
        return True

    def get_pending_jobs(self):
        jobs = [j for j in self.jobs.values() if j.get('status') == 'queued']
        jobs.sort(key=lambda x: (-x.get('priority', 50), x.get('submitted_at', '')))
        return jobs


class TestTagEligibility(unittest.TestCase):
    """Test tag eligibility checking."""

    def setUp(self):
        self.storage = MockStorageBackend()
        self.router = JobRouter(self.storage)

    def test_no_required_tags(self):
        """Test that workers are eligible when no tags required."""
        worker = {'id': 'w1', 'tags': ['cpu']}
        eligible, reason = self.router.check_tag_eligibility(worker, [])

        self.assertTrue(eligible)
        self.assertIn('No required', reason)

    def test_has_all_required_tags(self):
        """Test eligibility when worker has all required tags."""
        worker = {'id': 'w1', 'tags': ['gpu', 'high-memory', 'network-a']}
        eligible, reason = self.router.check_tag_eligibility(worker, ['gpu', 'high-memory'])

        self.assertTrue(eligible)
        self.assertIn('all required', reason)

    def test_missing_required_tags(self):
        """Test ineligibility when worker missing required tags."""
        worker = {'id': 'w1', 'tags': ['cpu']}
        eligible, reason = self.router.check_tag_eligibility(worker, ['gpu'])

        self.assertFalse(eligible)
        self.assertIn('Missing', reason)
        self.assertIn('gpu', reason)

    def test_partial_required_tags(self):
        """Test ineligibility when worker has only some required tags."""
        worker = {'id': 'w1', 'tags': ['gpu', 'network-a']}
        eligible, reason = self.router.check_tag_eligibility(worker, ['gpu', 'high-memory'])

        self.assertFalse(eligible)
        self.assertIn('high-memory', reason)


class TestTagScoring(unittest.TestCase):
    """Test tag matching score calculation."""

    def setUp(self):
        self.storage = MockStorageBackend()
        self.router = JobRouter(self.storage)

    def test_score_with_no_requirements(self):
        """Test score when no tags required."""
        worker = {'id': 'w1', 'tags': ['cpu']}
        score = self.router.calculate_tag_score(worker, [], [])

        self.assertEqual(score, 50)  # Base score with no requirements

    def test_score_with_required_tags_met(self):
        """Test score when required tags are met."""
        worker = {'id': 'w1', 'tags': ['gpu', 'high-memory']}
        score = self.router.calculate_tag_score(worker, ['gpu'], [])

        self.assertEqual(score, 60)  # Base score for meeting requirements

    def test_score_with_preferred_tags(self):
        """Test bonus score for preferred tags."""
        worker = {'id': 'w1', 'tags': ['gpu', 'high-memory']}
        score = self.router.calculate_tag_score(worker, ['gpu'], ['high-memory'])

        self.assertGreater(score, 60)  # Should get bonus for preferred

    def test_score_with_all_preferred_tags(self):
        """Test max bonus when all preferred tags present."""
        worker = {'id': 'w1', 'tags': ['gpu', 'tag1', 'tag2']}
        score = self.router.calculate_tag_score(worker, ['gpu'], ['tag1', 'tag2'])

        self.assertEqual(score, 100)  # 60 base + 40 max preferred bonus

    def test_score_zero_when_missing_required(self):
        """Test zero score when required tags not met."""
        worker = {'id': 'w1', 'tags': ['cpu']}
        score = self.router.calculate_tag_score(worker, ['gpu'], ['high-memory'])

        self.assertEqual(score, 0)


class TestLoadScoring(unittest.TestCase):
    """Test worker load score calculation."""

    def setUp(self):
        self.storage = MockStorageBackend()
        self.router = JobRouter(self.storage)

    def test_score_with_low_load(self):
        """Test high score for low load worker."""
        self.storage.workers['w1'] = {
            'id': 'w1',
            'max_concurrent_jobs': 4,
            'system_stats': {
                'cpu_percent': 10,
                'memory_percent': 20
            }
        }

        score = self.router.calculate_load_score(self.storage.workers['w1'])

        self.assertGreater(score, 80)  # Low load should give high score

    def test_score_with_high_load(self):
        """Test low score for high load worker."""
        self.storage.workers['w1'] = {
            'id': 'w1',
            'max_concurrent_jobs': 2,
            'system_stats': {
                'cpu_percent': 90,
                'memory_percent': 85
            }
        }

        score = self.router.calculate_load_score(self.storage.workers['w1'])

        self.assertLess(score, 50)  # High load should give lower score

    def test_score_considers_active_jobs(self):
        """Test that active job count affects load score."""
        self.storage.workers['w1'] = {
            'id': 'w1',
            'max_concurrent_jobs': 2,
            'system_stats': {
                'cpu_percent': 20,
                'memory_percent': 30
            }
        }

        # No active jobs - should have good score
        score_empty = self.router.calculate_load_score(self.storage.workers['w1'])

        # Add an active job
        self.storage.jobs['j1'] = {
            'id': 'j1',
            'assigned_worker': 'w1',
            'status': 'running'
        }

        score_with_job = self.router.calculate_load_score(self.storage.workers['w1'])

        self.assertGreater(score_empty, score_with_job)


class TestPreferenceScoring(unittest.TestCase):
    """Test preference bonus score calculation."""

    def setUp(self):
        self.storage = MockStorageBackend()
        self.router = JobRouter(self.storage)

    def test_local_worker_bonus(self):
        """Test bonus for local worker."""
        local_worker = {'id': '__local__', 'is_local': True, 'tags': []}
        remote_worker = {'id': 'w1', 'is_local': False, 'tags': []}

        job = {'job_type': 'normal', 'preferred_tags': []}

        local_score = self.router.calculate_preference_score(local_worker, job)
        remote_score = self.router.calculate_preference_score(remote_worker, job)

        self.assertGreater(local_score, remote_score)

    def test_long_running_tag_bonus(self):
        """Test bonus for workers with long-running capability."""
        batch_worker = {'id': 'w1', 'tags': ['batch', 'long-running']}
        regular_worker = {'id': 'w2', 'tags': ['cpu']}

        job = {'job_type': 'long_running', 'preferred_tags': []}

        batch_score = self.router.calculate_preference_score(batch_worker, job)
        regular_score = self.router.calculate_preference_score(regular_worker, job)

        self.assertGreater(batch_score, regular_score)

    def test_recent_checkin_bonus(self):
        """Test bonus for workers with recent checkin."""
        now = datetime.now()
        recent_worker = {
            'id': 'w1',
            'tags': [],
            'last_checkin': now.isoformat()
        }
        old_worker = {
            'id': 'w2',
            'tags': [],
            'last_checkin': (now - timedelta(hours=1)).isoformat()
        }

        job = {'job_type': 'normal', 'preferred_tags': []}

        recent_score = self.router.calculate_preference_score(recent_worker, job)
        old_score = self.router.calculate_preference_score(old_worker, job)

        self.assertGreater(recent_score, old_score)


class TestWorkerScoring(unittest.TestCase):
    """Test overall worker scoring."""

    def setUp(self):
        self.storage = MockStorageBackend()
        self.router = JobRouter(self.storage)

        # Set up workers
        self.storage.workers = {
            'w1': {
                'id': 'w1',
                'name': 'GPU Worker',
                'tags': ['gpu', 'high-memory'],
                'status': 'online',
                'max_concurrent_jobs': 4,
                'system_stats': {'cpu_percent': 20, 'memory_percent': 30},
                'last_checkin': datetime.now().isoformat()
            },
            'w2': {
                'id': 'w2',
                'name': 'CPU Worker',
                'tags': ['cpu'],
                'status': 'online',
                'max_concurrent_jobs': 2,
                'system_stats': {'cpu_percent': 50, 'memory_percent': 60},
                'last_checkin': datetime.now().isoformat()
            }
        }

    def test_score_eligible_worker(self):
        """Test scoring an eligible worker."""
        job = {
            'playbook': 'test.yml',
            'required_tags': ['gpu'],
            'preferred_tags': ['high-memory'],
            'job_type': 'normal'
        }

        score = self.router.score_worker(self.storage.workers['w1'], job)

        self.assertTrue(score.eligible)
        self.assertGreater(score.total_score, 0)
        self.assertGreater(score.tag_score, 0)
        self.assertGreater(score.load_score, 0)

    def test_score_ineligible_worker(self):
        """Test scoring an ineligible worker."""
        job = {
            'playbook': 'test.yml',
            'required_tags': ['gpu'],
            'preferred_tags': [],
            'job_type': 'normal'
        }

        score = self.router.score_worker(self.storage.workers['w2'], job)

        self.assertFalse(score.eligible)
        self.assertEqual(score.total_score, 0)
        self.assertIn('Missing', score.reason)


class TestFindBestWorker(unittest.TestCase):
    """Test finding best worker for a job."""

    def setUp(self):
        self.storage = MockStorageBackend()
        self.router = JobRouter(self.storage)

        # Set up workers
        self.storage.workers = {
            'w1': {
                'id': 'w1',
                'name': 'GPU Worker 1',
                'tags': ['gpu', 'high-memory'],
                'status': 'online',
                'max_concurrent_jobs': 4,
                'system_stats': {'cpu_percent': 20, 'memory_percent': 30},
                'last_checkin': datetime.now().isoformat()
            },
            'w2': {
                'id': 'w2',
                'name': 'GPU Worker 2',
                'tags': ['gpu'],
                'status': 'online',
                'max_concurrent_jobs': 2,
                'system_stats': {'cpu_percent': 70, 'memory_percent': 80},
                'last_checkin': datetime.now().isoformat()
            },
            'w3': {
                'id': 'w3',
                'name': 'CPU Worker',
                'tags': ['cpu'],
                'status': 'online',
                'max_concurrent_jobs': 2,
                'system_stats': {'cpu_percent': 10, 'memory_percent': 20}
            }
        }

    def test_find_best_worker_with_tags(self):
        """Test finding best worker based on tags."""
        job = {
            'playbook': 'test.yml',
            'required_tags': ['gpu'],
            'preferred_tags': ['high-memory'],
            'job_type': 'normal'
        }

        result = self.router.find_best_worker(job)

        self.assertIsNotNone(result)
        worker, score = result

        # W1 should win - has all tags and lower load
        self.assertEqual(worker['id'], 'w1')
        self.assertTrue(score.eligible)

    def test_find_best_worker_by_load(self):
        """Test finding best worker when tags equal, load differs."""
        job = {
            'playbook': 'test.yml',
            'required_tags': [],
            'preferred_tags': [],
            'job_type': 'normal'
        }

        result = self.router.find_best_worker(job)

        self.assertIsNotNone(result)
        worker, score = result

        # W3 or W1 should win - lowest load
        self.assertIn(worker['id'], ['w1', 'w3'])

    def test_find_best_worker_no_eligible(self):
        """Test when no worker is eligible."""
        job = {
            'playbook': 'test.yml',
            'required_tags': ['special-tag'],
            'preferred_tags': [],
            'job_type': 'normal'
        }

        result = self.router.find_best_worker(job)

        self.assertIsNone(result)

    def test_find_best_worker_excludes_offline(self):
        """Test that offline workers are excluded."""
        self.storage.workers['w1']['status'] = 'offline'

        job = {
            'playbook': 'test.yml',
            'required_tags': ['gpu'],
            'preferred_tags': ['high-memory'],
            'job_type': 'normal'
        }

        result = self.router.find_best_worker(job)

        self.assertIsNotNone(result)
        worker, score = result

        # W2 should win since W1 is offline
        self.assertEqual(worker['id'], 'w2')

    def test_find_best_worker_respects_capacity(self):
        """Test that workers at capacity are excluded."""
        # Fill w1 to capacity
        self.storage.workers['w1']['max_concurrent_jobs'] = 1
        self.storage.jobs['j1'] = {
            'id': 'j1',
            'assigned_worker': 'w1',
            'status': 'running'
        }

        job = {
            'playbook': 'test.yml',
            'required_tags': ['gpu'],
            'preferred_tags': ['high-memory'],
            'job_type': 'normal'
        }

        result = self.router.find_best_worker(job)

        self.assertIsNotNone(result)
        worker, score = result

        # W2 should win since W1 is at capacity
        self.assertEqual(worker['id'], 'w2')


class TestRouteJob(unittest.TestCase):
    """Test job routing."""

    def setUp(self):
        self.storage = MockStorageBackend()
        self.router = JobRouter(self.storage)

        self.storage.workers = {
            'w1': {
                'id': 'w1',
                'name': 'GPU Worker',
                'tags': ['gpu'],
                'status': 'online',
                'max_concurrent_jobs': 4,
                'system_stats': {'cpu_percent': 20, 'memory_percent': 30}
            }
        }

        self.storage.jobs = {
            'j1': {
                'id': 'j1',
                'playbook': 'test.yml',
                'status': 'queued',
                'required_tags': ['gpu'],
                'preferred_tags': [],
                'priority': 50
            }
        }

    def test_route_job_success(self):
        """Test successful job routing."""
        result = self.router.route_job('j1')

        self.assertTrue(result.get('assigned'))
        self.assertEqual(result['worker_id'], 'w1')
        self.assertIn('score', result)

        # Verify job was updated
        job = self.storage.get_job('j1')
        self.assertEqual(job['status'], 'assigned')
        self.assertEqual(job['assigned_worker'], 'w1')

    def test_route_job_not_found(self):
        """Test routing non-existent job."""
        result = self.router.route_job('nonexistent')

        self.assertIn('error', result)

    def test_route_job_not_queued(self):
        """Test routing already assigned job."""
        self.storage.jobs['j1']['status'] = 'running'

        result = self.router.route_job('j1')

        self.assertIn('error', result)
        self.assertIn('not in queued', result['error'])

    def test_route_job_no_eligible_worker(self):
        """Test routing when no worker eligible."""
        self.storage.jobs['j1']['required_tags'] = ['special']

        result = self.router.route_job('j1')

        self.assertFalse(result.get('assigned'))
        self.assertIn('No eligible', result.get('reason', ''))


class TestRoutePendingJobs(unittest.TestCase):
    """Test bulk job routing."""

    def setUp(self):
        self.storage = MockStorageBackend()
        self.router = JobRouter(self.storage)

        self.storage.workers = {
            'w1': {
                'id': 'w1',
                'name': 'Worker 1',
                'tags': ['gpu'],
                'status': 'online',
                'max_concurrent_jobs': 2,
                'system_stats': {'cpu_percent': 20, 'memory_percent': 30}
            },
            'w2': {
                'id': 'w2',
                'name': 'Worker 2',
                'tags': ['cpu'],
                'status': 'online',
                'max_concurrent_jobs': 2,
                'system_stats': {'cpu_percent': 30, 'memory_percent': 40}
            }
        }

        # Add pending jobs with different priorities
        self.storage.jobs = {
            'j1': {
                'id': 'j1',
                'playbook': 'test.yml',
                'status': 'queued',
                'required_tags': [],
                'preferred_tags': [],
                'priority': 50,
                'submitted_at': '2024-01-01T10:00:00'
            },
            'j2': {
                'id': 'j2',
                'playbook': 'test.yml',
                'status': 'queued',
                'required_tags': [],
                'preferred_tags': [],
                'priority': 75,
                'submitted_at': '2024-01-01T11:00:00'
            },
            'j3': {
                'id': 'j3',
                'playbook': 'test.yml',
                'status': 'queued',
                'required_tags': ['gpu'],
                'preferred_tags': [],
                'priority': 25,
                'submitted_at': '2024-01-01T12:00:00'
            }
        }

    def test_route_pending_respects_priority(self):
        """Test that high priority jobs are routed first."""
        results = self.router.route_pending_jobs(limit=10)

        self.assertEqual(len(results), 3)

        # First result should be j2 (highest priority)
        self.assertEqual(results[0]['job_id'], 'j2')
        self.assertTrue(results[0]['assigned'])

    def test_route_pending_limited(self):
        """Test limit on number of jobs routed."""
        results = self.router.route_pending_jobs(limit=1)

        self.assertEqual(len(results), 1)


class TestWorkerRecommendations(unittest.TestCase):
    """Test worker recommendations."""

    def setUp(self):
        self.storage = MockStorageBackend()
        self.router = JobRouter(self.storage)

        self.storage.workers = {
            'w1': {
                'id': 'w1',
                'name': 'GPU Worker',
                'tags': ['gpu', 'high-memory'],
                'status': 'online',
                'max_concurrent_jobs': 4,
                'system_stats': {'cpu_percent': 20, 'memory_percent': 30}
            },
            'w2': {
                'id': 'w2',
                'name': 'CPU Worker',
                'tags': ['cpu'],
                'status': 'online',
                'max_concurrent_jobs': 2,
                'system_stats': {'cpu_percent': 50, 'memory_percent': 60}
            }
        }

        self.storage.jobs = {
            'j1': {
                'id': 'j1',
                'playbook': 'test.yml',
                'status': 'queued',
                'required_tags': ['gpu'],
                'preferred_tags': ['high-memory'],
                'priority': 50
            }
        }

    def test_get_recommendations(self):
        """Test getting worker recommendations."""
        recommendations = self.router.get_worker_recommendations('j1')

        self.assertEqual(len(recommendations), 2)

        # W1 should be first (eligible with GPU)
        self.assertEqual(recommendations[0]['worker_id'], 'w1')
        self.assertTrue(recommendations[0]['eligible'])

        # W2 should be second (ineligible - no GPU)
        self.assertEqual(recommendations[1]['worker_id'], 'w2')
        self.assertFalse(recommendations[1]['eligible'])

    def test_recommendations_include_scores(self):
        """Test that recommendations include score breakdown."""
        recommendations = self.router.get_worker_recommendations('j1')

        eligible_rec = recommendations[0]
        self.assertIn('scores', eligible_rec)
        self.assertIn('total', eligible_rec['scores'])
        self.assertIn('tag', eligible_rec['scores'])
        self.assertIn('load', eligible_rec['scores'])

    def test_recommendations_sorted_by_score(self):
        """Test that recommendations are sorted by score."""
        # Add another GPU worker with worse load
        self.storage.workers['w3'] = {
            'id': 'w3',
            'name': 'GPU Worker 2',
            'tags': ['gpu'],
            'status': 'online',
            'max_concurrent_jobs': 2,
            'system_stats': {'cpu_percent': 80, 'memory_percent': 90}
        }

        recommendations = self.router.get_worker_recommendations('j1')

        # W1 should still be first (better load and preferred tags)
        self.assertEqual(recommendations[0]['worker_id'], 'w1')

        # Scores should be descending
        scores = [r['scores']['total'] for r in recommendations]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == '__main__':
    unittest.main()
