"""
Unit tests for Job Queue API (Feature 6).

Tests the job submission, listing, cancellation, and lifecycle endpoints.
Uses mock storage backend to test logic without Flask dependencies.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch
from datetime import datetime
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockStorageBackend:
    """Mock storage backend for testing job queue logic."""

    def __init__(self):
        self.jobs = {}
        self.workers = {}

    def get_all_jobs(self, filters=None):
        """Get all jobs with optional filters."""
        jobs = list(self.jobs.values())

        if filters:
            if 'status' in filters:
                statuses = filters['status'] if isinstance(filters['status'], list) else [filters['status']]
                jobs = [j for j in jobs if j.get('status') in statuses]
            if 'playbook' in filters:
                jobs = [j for j in jobs if j.get('playbook') == filters['playbook']]
            if 'assigned_worker' in filters:
                jobs = [j for j in jobs if j.get('assigned_worker') == filters['assigned_worker']]

        # Sort by submitted_at descending
        jobs.sort(key=lambda x: x.get('submitted_at', ''), reverse=True)
        return jobs

    def get_job(self, job_id):
        """Get a single job by ID."""
        return self.jobs.get(job_id)

    def save_job(self, job):
        """Save a job."""
        job_id = job.get('id')
        if not job_id:
            return False
        self.jobs[job_id] = job.copy()
        return True

    def update_job(self, job_id, updates):
        """Update a job."""
        if job_id not in self.jobs:
            return False
        self.jobs[job_id].update(updates)
        return True

    def delete_job(self, job_id):
        """Delete a job."""
        if job_id not in self.jobs:
            return False
        del self.jobs[job_id]
        return True

    def get_pending_jobs(self):
        """Get pending jobs sorted by priority."""
        jobs = [j for j in self.jobs.values() if j.get('status') == 'queued']
        jobs.sort(key=lambda x: (-x.get('priority', 50), x.get('submitted_at', '')))
        return jobs

    def get_worker_jobs(self, worker_id, statuses=None):
        """Get jobs for a worker."""
        jobs = [j for j in self.jobs.values() if j.get('assigned_worker') == worker_id]
        if statuses:
            jobs = [j for j in jobs if j.get('status') in statuses]
        return jobs

    def get_worker(self, worker_id):
        """Get a worker by ID."""
        return self.workers.get(worker_id)

    def get_all_workers(self):
        """Get all workers."""
        return list(self.workers.values())


class TestJobSubmission(unittest.TestCase):
    """Test job submission logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.storage = MockStorageBackend()
        self.available_playbooks = ['test.yml', 'deploy.yml', 'backup.yml']

    def _submit_job(self, data):
        """Simulate job submission logic."""
        playbook = data.get('playbook')
        if not playbook:
            return {'error': 'playbook is required'}, 400

        if playbook not in self.available_playbooks:
            return {'error': f'Playbook not found: {playbook}'}, 400

        import uuid
        job_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        job = {
            'id': job_id,
            'playbook': playbook,
            'target': data.get('target', 'all'),
            'required_tags': data.get('required_tags', []),
            'preferred_tags': data.get('preferred_tags', []),
            'priority': min(100, max(1, data.get('priority', 50))),
            'job_type': data.get('job_type', 'normal'),
            'extra_vars': data.get('extra_vars', {}),
            'status': 'queued',
            'assigned_worker': None,
            'submitted_by': data.get('submitted_by', 'api'),
            'submitted_at': now,
            'assigned_at': None,
            'started_at': None,
            'completed_at': None,
            'log_file': None,
            'exit_code': None,
            'error_message': None
        }

        if job['job_type'] not in ('normal', 'long_running'):
            return {'error': 'job_type must be "normal" or "long_running"'}, 400

        if not self.storage.save_job(job):
            return {'error': 'Failed to save job'}, 500

        return {
            'job_id': job_id,
            'status': 'queued',
            'message': 'Job submitted successfully'
        }, 201

    def test_submit_job_success(self):
        """Test successful job submission."""
        result, status = self._submit_job({
            'playbook': 'test.yml',
            'target': 'webservers',
            'priority': 75
        })

        self.assertEqual(status, 201)
        self.assertIn('job_id', result)
        self.assertEqual(result['status'], 'queued')

        # Verify job was saved
        job = self.storage.get_job(result['job_id'])
        self.assertIsNotNone(job)
        self.assertEqual(job['playbook'], 'test.yml')
        self.assertEqual(job['target'], 'webservers')
        self.assertEqual(job['priority'], 75)

    def test_submit_job_missing_playbook(self):
        """Test submission without playbook."""
        result, status = self._submit_job({})

        self.assertEqual(status, 400)
        self.assertEqual(result['error'], 'playbook is required')

    def test_submit_job_invalid_playbook(self):
        """Test submission with non-existent playbook."""
        result, status = self._submit_job({'playbook': 'nonexistent.yml'})

        self.assertEqual(status, 400)
        self.assertIn('not found', result['error'])

    def test_submit_job_default_values(self):
        """Test that default values are applied."""
        result, status = self._submit_job({'playbook': 'test.yml'})

        self.assertEqual(status, 201)
        job = self.storage.get_job(result['job_id'])

        self.assertEqual(job['target'], 'all')
        self.assertEqual(job['priority'], 50)
        self.assertEqual(job['job_type'], 'normal')
        self.assertEqual(job['required_tags'], [])
        self.assertEqual(job['submitted_by'], 'api')

    def test_submit_job_with_tags(self):
        """Test submission with tag requirements."""
        result, status = self._submit_job({
            'playbook': 'deploy.yml',
            'required_tags': ['gpu', 'high-memory'],
            'preferred_tags': ['network-a']
        })

        self.assertEqual(status, 201)
        job = self.storage.get_job(result['job_id'])

        self.assertEqual(job['required_tags'], ['gpu', 'high-memory'])
        self.assertEqual(job['preferred_tags'], ['network-a'])

    def test_submit_job_priority_clamping(self):
        """Test that priority is clamped to valid range."""
        result, status = self._submit_job({
            'playbook': 'test.yml',
            'priority': 150
        })
        job = self.storage.get_job(result['job_id'])
        self.assertEqual(job['priority'], 100)

        result, status = self._submit_job({
            'playbook': 'test.yml',
            'priority': -10
        })
        job = self.storage.get_job(result['job_id'])
        self.assertEqual(job['priority'], 1)

    def test_submit_job_invalid_type(self):
        """Test submission with invalid job type."""
        result, status = self._submit_job({
            'playbook': 'test.yml',
            'job_type': 'invalid'
        })

        self.assertEqual(status, 400)
        self.assertIn('job_type', result['error'])


class TestJobListing(unittest.TestCase):
    """Test job listing and filtering."""

    def setUp(self):
        """Set up test fixtures with sample jobs."""
        self.storage = MockStorageBackend()

        # Add sample jobs
        jobs = [
            {'id': 'job-1', 'playbook': 'test.yml', 'status': 'queued', 'priority': 50,
             'submitted_at': '2024-01-01T10:00:00', 'assigned_worker': None},
            {'id': 'job-2', 'playbook': 'test.yml', 'status': 'running', 'priority': 75,
             'submitted_at': '2024-01-01T11:00:00', 'assigned_worker': 'worker-1'},
            {'id': 'job-3', 'playbook': 'deploy.yml', 'status': 'completed', 'priority': 50,
             'submitted_at': '2024-01-01T09:00:00', 'assigned_worker': 'worker-2'},
            {'id': 'job-4', 'playbook': 'backup.yml', 'status': 'queued', 'priority': 90,
             'submitted_at': '2024-01-01T12:00:00', 'assigned_worker': None},
        ]
        for job in jobs:
            self.storage.save_job(job)

    def test_list_all_jobs(self):
        """Test listing all jobs."""
        jobs = self.storage.get_all_jobs()

        self.assertEqual(len(jobs), 4)
        # Should be sorted by submitted_at descending
        self.assertEqual(jobs[0]['id'], 'job-4')

    def test_filter_by_status(self):
        """Test filtering by status."""
        jobs = self.storage.get_all_jobs({'status': ['queued']})

        self.assertEqual(len(jobs), 2)
        for job in jobs:
            self.assertEqual(job['status'], 'queued')

    def test_filter_by_multiple_statuses(self):
        """Test filtering by multiple statuses."""
        jobs = self.storage.get_all_jobs({'status': ['queued', 'running']})

        self.assertEqual(len(jobs), 3)

    def test_filter_by_playbook(self):
        """Test filtering by playbook."""
        jobs = self.storage.get_all_jobs({'playbook': 'test.yml'})

        self.assertEqual(len(jobs), 2)
        for job in jobs:
            self.assertEqual(job['playbook'], 'test.yml')

    def test_filter_by_worker(self):
        """Test filtering by assigned worker."""
        jobs = self.storage.get_all_jobs({'assigned_worker': 'worker-1'})

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['id'], 'job-2')

    def test_pending_jobs_sorted_by_priority(self):
        """Test that pending jobs are sorted by priority."""
        jobs = self.storage.get_pending_jobs()

        self.assertEqual(len(jobs), 2)
        # Higher priority first
        self.assertEqual(jobs[0]['id'], 'job-4')  # priority 90
        self.assertEqual(jobs[1]['id'], 'job-1')  # priority 50


class TestJobCancellation(unittest.TestCase):
    """Test job cancellation logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.storage = MockStorageBackend()

    def _cancel_job(self, job_id):
        """Simulate job cancellation logic."""
        job = self.storage.get_job(job_id)
        if not job:
            return {'error': 'Job not found'}, 404

        current_status = job.get('status', '')

        if current_status in ('completed', 'failed', 'cancelled'):
            return {'error': f'Cannot cancel job with status: {current_status}'}, 400

        updates = {
            'status': 'cancelled',
            'completed_at': datetime.now().isoformat(),
            'error_message': 'Job cancelled by user'
        }

        if not self.storage.update_job(job_id, updates):
            return {'error': 'Failed to update job'}, 500

        return {
            'job_id': job_id,
            'status': 'cancelled',
            'message': 'Job cancelled successfully'
        }, 200

    def test_cancel_queued_job(self):
        """Test cancelling a queued job."""
        self.storage.save_job({'id': 'job-1', 'status': 'queued'})

        result, status = self._cancel_job('job-1')

        self.assertEqual(status, 200)
        self.assertEqual(result['status'], 'cancelled')

        job = self.storage.get_job('job-1')
        self.assertEqual(job['status'], 'cancelled')

    def test_cancel_running_job(self):
        """Test cancelling a running job."""
        self.storage.save_job({'id': 'job-1', 'status': 'running'})

        result, status = self._cancel_job('job-1')

        self.assertEqual(status, 200)
        job = self.storage.get_job('job-1')
        self.assertEqual(job['status'], 'cancelled')

    def test_cancel_completed_job_fails(self):
        """Test that completed jobs cannot be cancelled."""
        self.storage.save_job({'id': 'job-1', 'status': 'completed'})

        result, status = self._cancel_job('job-1')

        self.assertEqual(status, 400)
        self.assertIn('Cannot cancel', result['error'])

    def test_cancel_nonexistent_job(self):
        """Test cancelling a non-existent job."""
        result, status = self._cancel_job('nonexistent')

        self.assertEqual(status, 404)


class TestJobLifecycle(unittest.TestCase):
    """Test job lifecycle operations (assign, start, complete)."""

    def setUp(self):
        """Set up test fixtures."""
        self.storage = MockStorageBackend()

        # Add a worker
        self.storage.workers['worker-1'] = {
            'id': 'worker-1',
            'name': 'test-worker',
            'status': 'online'
        }

        # Add a queued job
        self.storage.save_job({
            'id': 'job-1',
            'playbook': 'test.yml',
            'status': 'queued',
            'assigned_worker': None
        })

    def _assign_job(self, job_id, worker_id):
        """Simulate job assignment logic."""
        worker = self.storage.get_worker(worker_id)
        if not worker:
            return {'error': 'Worker not found'}, 404

        worker_status = worker.get('status', '')
        if worker_status not in ('online', 'busy'):
            return {'error': f'Worker not available (status: {worker_status})'}, 400

        job = self.storage.get_job(job_id)
        if not job:
            return {'error': 'Job not found'}, 404

        if job.get('status') != 'queued':
            return {'error': f'Job cannot be assigned (status: {job.get("status")})'}, 400

        updates = {
            'status': 'assigned',
            'assigned_worker': worker_id,
            'assigned_at': datetime.now().isoformat()
        }

        if not self.storage.update_job(job_id, updates):
            return {'error': 'Failed to assign job'}, 500

        return {
            'job_id': job_id,
            'worker_id': worker_id,
            'status': 'assigned',
            'message': 'Job assigned successfully'
        }, 200

    def _start_job(self, job_id, worker_id, log_file=None):
        """Simulate job start logic."""
        job = self.storage.get_job(job_id)
        if not job:
            return {'error': 'Job not found'}, 404

        if job.get('assigned_worker') != worker_id:
            return {'error': 'Job not assigned to this worker'}, 403

        if job.get('status') not in ('assigned', 'running'):
            return {'error': f'Job cannot be started (status: {job.get("status")})'}, 400

        updates = {
            'status': 'running',
            'started_at': datetime.now().isoformat()
        }
        if log_file:
            updates['log_file'] = log_file

        if not self.storage.update_job(job_id, updates):
            return {'error': 'Failed to update job'}, 500

        return {'job_id': job_id, 'status': 'running', 'message': 'Job started'}, 200

    def _complete_job(self, job_id, worker_id, exit_code, log_file=None, error_message=None):
        """Simulate job completion logic."""
        job = self.storage.get_job(job_id)
        if not job:
            return {'error': 'Job not found'}, 404

        if job.get('assigned_worker') != worker_id:
            return {'error': 'Job not assigned to this worker'}, 403

        status = 'completed' if exit_code == 0 else 'failed'

        updates = {
            'status': status,
            'exit_code': exit_code,
            'completed_at': datetime.now().isoformat()
        }
        if log_file:
            updates['log_file'] = log_file
        if error_message:
            updates['error_message'] = error_message

        if not self.storage.update_job(job_id, updates):
            return {'error': 'Failed to update job'}, 500

        return {
            'job_id': job_id,
            'status': status,
            'exit_code': exit_code,
            'message': f'Job {status}'
        }, 200

    def test_assign_job_success(self):
        """Test successful job assignment."""
        result, status = self._assign_job('job-1', 'worker-1')

        self.assertEqual(status, 200)
        self.assertEqual(result['status'], 'assigned')

        job = self.storage.get_job('job-1')
        self.assertEqual(job['status'], 'assigned')
        self.assertEqual(job['assigned_worker'], 'worker-1')

    def test_assign_job_offline_worker(self):
        """Test assigning to offline worker fails."""
        self.storage.workers['worker-1']['status'] = 'offline'

        result, status = self._assign_job('job-1', 'worker-1')

        self.assertEqual(status, 400)
        self.assertIn('not available', result['error'])

    def test_assign_job_nonexistent_worker(self):
        """Test assigning to non-existent worker."""
        result, status = self._assign_job('job-1', 'nonexistent')

        self.assertEqual(status, 404)

    def test_assign_already_assigned_job(self):
        """Test assigning an already assigned job fails."""
        self._assign_job('job-1', 'worker-1')

        result, status = self._assign_job('job-1', 'worker-1')

        self.assertEqual(status, 400)
        self.assertIn('cannot be assigned', result['error'])

    def test_start_job_success(self):
        """Test starting an assigned job."""
        self._assign_job('job-1', 'worker-1')

        result, status = self._start_job('job-1', 'worker-1', 'job-1.log')

        self.assertEqual(status, 200)
        self.assertEqual(result['status'], 'running')

        job = self.storage.get_job('job-1')
        self.assertEqual(job['status'], 'running')
        self.assertEqual(job['log_file'], 'job-1.log')
        self.assertIsNotNone(job['started_at'])

    def test_start_job_wrong_worker(self):
        """Test starting a job by wrong worker."""
        self._assign_job('job-1', 'worker-1')

        result, status = self._start_job('job-1', 'worker-2')

        self.assertEqual(status, 403)

    def test_complete_job_success(self):
        """Test successful job completion."""
        self._assign_job('job-1', 'worker-1')
        self._start_job('job-1', 'worker-1')

        result, status = self._complete_job('job-1', 'worker-1', exit_code=0)

        self.assertEqual(status, 200)
        self.assertEqual(result['status'], 'completed')

        job = self.storage.get_job('job-1')
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['exit_code'], 0)

    def test_complete_job_failure(self):
        """Test job completion with failure."""
        self._assign_job('job-1', 'worker-1')
        self._start_job('job-1', 'worker-1')

        result, status = self._complete_job(
            'job-1', 'worker-1',
            exit_code=1,
            error_message='Playbook failed'
        )

        self.assertEqual(status, 200)
        self.assertEqual(result['status'], 'failed')

        job = self.storage.get_job('job-1')
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['exit_code'], 1)
        self.assertEqual(job['error_message'], 'Playbook failed')

    def test_complete_job_wrong_worker(self):
        """Test completing job by wrong worker."""
        self._assign_job('job-1', 'worker-1')
        self._start_job('job-1', 'worker-1')

        result, status = self._complete_job('job-1', 'worker-2', exit_code=0)

        self.assertEqual(status, 403)


class TestJobLogRetrieval(unittest.TestCase):
    """Test job log retrieval."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = MockStorageBackend()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _get_job_log(self, job_id, lines=None, format='text'):
        """Simulate job log retrieval logic."""
        job = self.storage.get_job(job_id)
        if not job:
            return {'error': 'Job not found'}, 404

        log_file = job.get('log_file')
        if not log_file:
            return {
                'job_id': job_id,
                'status': job.get('status'),
                'log': None,
                'message': 'No log file available (job may not have started)'
            }, 200

        log_path = os.path.join(self.test_dir, log_file)

        if not os.path.exists(log_path):
            return {
                'job_id': job_id,
                'status': job.get('status'),
                'log': None,
                'message': 'Log file not found'
            }, 200

        try:
            with open(log_path, 'r') as f:
                log_content = f.read()
        except IOError as e:
            return {'error': f'Failed to read log: {str(e)}'}, 500

        if lines:
            log_lines = log_content.splitlines()
            if lines < 0:
                log_lines = log_lines[lines:]
            else:
                log_lines = log_lines[:lines]
            log_content = '\n'.join(log_lines)

        if format == 'json':
            return {
                'job_id': job_id,
                'status': job.get('status'),
                'log_file': log_file,
                'log': log_content,
                'lines': len(log_content.splitlines())
            }, 200
        else:
            return log_content, 200

    def test_get_log_success(self):
        """Test successful log retrieval."""
        # Create log file
        log_content = "Line 1\nLine 2\nLine 3\n"
        with open(os.path.join(self.test_dir, 'test.log'), 'w') as f:
            f.write(log_content)

        self.storage.save_job({
            'id': 'job-1',
            'status': 'completed',
            'log_file': 'test.log'
        })

        result, status = self._get_job_log('job-1', format='json')

        self.assertEqual(status, 200)
        self.assertIn('log', result)
        self.assertIn('Line 1', result['log'])

    def test_get_log_tail(self):
        """Test getting last N lines."""
        log_content = "\n".join([f"Line {i}" for i in range(1, 11)])
        with open(os.path.join(self.test_dir, 'test.log'), 'w') as f:
            f.write(log_content)

        self.storage.save_job({
            'id': 'job-1',
            'status': 'completed',
            'log_file': 'test.log'
        })

        result, status = self._get_job_log('job-1', lines=-3, format='json')

        self.assertEqual(status, 200)
        lines = result['log'].splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], 'Line 8')

    def test_get_log_no_file(self):
        """Test log retrieval when no log file."""
        self.storage.save_job({
            'id': 'job-1',
            'status': 'queued',
            'log_file': None
        })

        result, status = self._get_job_log('job-1', format='json')

        self.assertEqual(status, 200)
        self.assertIsNone(result['log'])
        self.assertIn('not have started', result['message'])

    def test_get_log_not_found(self):
        """Test log retrieval for non-existent job."""
        result, status = self._get_job_log('nonexistent')

        self.assertEqual(status, 404)


class TestWorkerJobsQuery(unittest.TestCase):
    """Test querying jobs by worker."""

    def setUp(self):
        """Set up test fixtures."""
        self.storage = MockStorageBackend()

        # Add jobs for different workers
        jobs = [
            {'id': 'job-1', 'assigned_worker': 'worker-1', 'status': 'running'},
            {'id': 'job-2', 'assigned_worker': 'worker-1', 'status': 'completed'},
            {'id': 'job-3', 'assigned_worker': 'worker-2', 'status': 'running'},
            {'id': 'job-4', 'assigned_worker': None, 'status': 'queued'},
        ]
        for job in jobs:
            self.storage.save_job(job)

    def test_get_worker_jobs(self):
        """Test getting all jobs for a worker."""
        jobs = self.storage.get_worker_jobs('worker-1')

        self.assertEqual(len(jobs), 2)
        for job in jobs:
            self.assertEqual(job['assigned_worker'], 'worker-1')

    def test_get_worker_jobs_with_status_filter(self):
        """Test getting worker jobs filtered by status."""
        jobs = self.storage.get_worker_jobs('worker-1', statuses=['running'])

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['id'], 'job-1')

    def test_get_worker_jobs_no_jobs(self):
        """Test getting jobs for worker with no assignments."""
        jobs = self.storage.get_worker_jobs('worker-3')

        self.assertEqual(len(jobs), 0)


if __name__ == '__main__':
    unittest.main()
