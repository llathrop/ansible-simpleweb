"""
Job Router

Automatic job routing and assignment based on:
- Tag requirements and preferences
- Worker current load
- Job type (normal vs long_running)
- Worker health statistics
- Priority scoring
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class WorkerScore:
    """Score for a worker candidate."""
    worker_id: str
    worker_name: str
    total_score: float
    tag_score: float
    load_score: float
    preference_score: float
    eligible: bool
    reason: str = ""


class JobRouter:
    """
    Routes jobs to workers based on various criteria.

    Scoring system:
    - Tag match score (0-100): Based on required and preferred tags
    - Load score (0-100): Based on current worker load (lower load = higher score)
    - Preference score (0-50): Bonus for preferred tags and job type compatibility

    Workers must have ALL required tags to be eligible.
    """

    # Weight factors for different scoring components
    TAG_WEIGHT = 0.4
    LOAD_WEIGHT = 0.35
    PREFERENCE_WEIGHT = 0.25

    # Load thresholds
    LOAD_HIGH_THRESHOLD = 80  # CPU or memory above this is considered high load
    LOAD_MEDIUM_THRESHOLD = 50

    def __init__(self, storage_backend):
        """
        Initialize job router.

        Args:
            storage_backend: Storage backend for workers and jobs
        """
        self.storage = storage_backend

    def get_available_workers(self) -> List[Dict]:
        """
        Get workers available for job assignment.

        Returns:
            List of worker dicts with status 'online' or 'busy' (but under capacity)
        """
        all_workers = self.storage.get_all_workers()
        available = []

        for worker in all_workers:
            status = worker.get('status', '')
            if status not in ('online', 'busy'):
                continue

            # Check if worker has capacity
            max_jobs = worker.get('max_concurrent_jobs', 2)
            active_jobs = self.storage.get_worker_jobs(
                worker['id'],
                statuses=['assigned', 'running']
            )

            if len(active_jobs) < max_jobs:
                available.append(worker)

        return available

    def check_tag_eligibility(self, worker: Dict, required_tags: List[str]) -> Tuple[bool, str]:
        """
        Check if worker has all required tags.

        Args:
            worker: Worker dict
            required_tags: Tags the job requires

        Returns:
            Tuple of (eligible, reason)
        """
        if not required_tags:
            return True, "No required tags"

        worker_tags = set(worker.get('tags', []))
        required_set = set(required_tags)

        missing = required_set - worker_tags
        if missing:
            return False, f"Missing required tags: {', '.join(missing)}"

        return True, "Has all required tags"

    def calculate_tag_score(self, worker: Dict, required_tags: List[str],
                           preferred_tags: List[str]) -> float:
        """
        Calculate tag matching score.

        Args:
            worker: Worker dict
            required_tags: Required tags (must all be present)
            preferred_tags: Preferred tags (bonus points)

        Returns:
            Score from 0-100
        """
        worker_tags = set(worker.get('tags', []))

        # Base score for having all required tags
        if required_tags:
            required_set = set(required_tags)
            if not required_set.issubset(worker_tags):
                return 0  # Ineligible
            score = 60  # Base score for meeting requirements
        else:
            score = 50  # No requirements, middle score

        # Bonus for preferred tags
        if preferred_tags:
            preferred_set = set(preferred_tags)
            matched = preferred_set & worker_tags
            if matched:
                bonus = (len(matched) / len(preferred_set)) * 40
                score += bonus

        return min(100, score)

    def calculate_load_score(self, worker: Dict) -> float:
        """
        Calculate worker load score (lower load = higher score).

        Args:
            worker: Worker dict with system_stats

        Returns:
            Score from 0-100
        """
        stats = worker.get('system_stats', {})

        # Get load metrics
        cpu_percent = stats.get('cpu_percent', 0)
        memory_percent = stats.get('memory_percent', 0)
        load_1m = stats.get('load_1m', 0)

        # Also consider active jobs
        active_jobs = self.storage.get_worker_jobs(
            worker['id'],
            statuses=['assigned', 'running']
        )
        max_jobs = worker.get('max_concurrent_jobs', 2)
        job_load_percent = (len(active_jobs) / max_jobs) * 100 if max_jobs > 0 else 100

        # Combined load metric (weighted average)
        combined_load = (
            cpu_percent * 0.3 +
            memory_percent * 0.3 +
            job_load_percent * 0.4
        )

        # Convert to score (inverted - lower load = higher score)
        score = max(0, 100 - combined_load)

        return score

    def calculate_preference_score(self, worker: Dict, job: Dict) -> float:
        """
        Calculate bonus preference score.

        Args:
            worker: Worker dict
            job: Job dict

        Returns:
            Score from 0-50
        """
        score = 0.0
        worker_tags = set(worker.get('tags', []))
        job_type = job.get('job_type', 'normal')

        # Bonus for local worker (lower latency)
        if worker.get('is_local'):
            score += 5

        # Bonus for matching job type capabilities
        if job_type == 'long_running':
            # Prefer workers with 'long-running' or 'batch' tags
            if 'long-running' in worker_tags or 'batch' in worker_tags:
                score += 15

        # Bonus for workers that recently checked in (more reliable)
        last_checkin = worker.get('last_checkin', '')
        if last_checkin:
            try:
                checkin_time = datetime.fromisoformat(last_checkin)
                age_seconds = (datetime.now() - checkin_time).total_seconds()
                if age_seconds < 60:  # Checked in last minute
                    score += 10
                elif age_seconds < 300:  # Last 5 minutes
                    score += 5
            except (ValueError, TypeError):
                pass

        # Bonus for workers with preferred tags (already partially covered in tag_score)
        preferred_tags = job.get('preferred_tags', [])
        if preferred_tags:
            matched = set(preferred_tags) & worker_tags
            if len(matched) == len(preferred_tags):  # All preferred tags
                score += 20

        return min(50, score)

    def score_worker(self, worker: Dict, job: Dict) -> WorkerScore:
        """
        Calculate overall score for a worker-job pair.

        Args:
            worker: Worker dict
            job: Job dict

        Returns:
            WorkerScore with detailed breakdown
        """
        required_tags = job.get('required_tags', [])
        preferred_tags = job.get('preferred_tags', [])

        # Check eligibility first
        eligible, reason = self.check_tag_eligibility(worker, required_tags)

        if not eligible:
            return WorkerScore(
                worker_id=worker['id'],
                worker_name=worker.get('name', 'Unknown'),
                total_score=0,
                tag_score=0,
                load_score=0,
                preference_score=0,
                eligible=False,
                reason=reason
            )

        # Calculate component scores
        tag_score = self.calculate_tag_score(worker, required_tags, preferred_tags)
        load_score = self.calculate_load_score(worker)
        preference_score = self.calculate_preference_score(worker, job)

        # Calculate weighted total
        total_score = (
            tag_score * self.TAG_WEIGHT +
            load_score * self.LOAD_WEIGHT +
            preference_score * self.PREFERENCE_WEIGHT
        )

        return WorkerScore(
            worker_id=worker['id'],
            worker_name=worker.get('name', 'Unknown'),
            total_score=total_score,
            tag_score=tag_score,
            load_score=load_score,
            preference_score=preference_score,
            eligible=True,
            reason="Eligible"
        )

    def find_best_worker(self, job: Dict) -> Optional[Tuple[Dict, WorkerScore]]:
        """
        Find the best worker for a job.

        Args:
            job: Job dict

        Returns:
            Tuple of (worker, score) or None if no eligible worker
        """
        available = self.get_available_workers()

        if not available:
            return None

        scores = []
        for worker in available:
            score = self.score_worker(worker, job)
            if score.eligible:
                scores.append((worker, score))

        if not scores:
            return None

        # Sort by total score (highest first)
        scores.sort(key=lambda x: x[1].total_score, reverse=True)

        return scores[0]

    def route_job(self, job_id: str) -> Optional[Dict]:
        """
        Route a specific job to a worker.

        Args:
            job_id: ID of job to route

        Returns:
            Assignment result dict or None if no assignment made
        """
        job = self.storage.get_job(job_id)
        if not job:
            return {'error': 'Job not found'}

        if job.get('status') != 'queued':
            return {'error': f'Job not in queued status (is {job.get("status")})'}

        result = self.find_best_worker(job)
        if not result:
            return {
                'job_id': job_id,
                'assigned': False,
                'reason': 'No eligible worker available'
            }

        worker, score = result

        # Update job assignment
        updates = {
            'status': 'assigned',
            'assigned_worker': worker['id'],
            'assigned_at': datetime.now().isoformat()
        }

        if not self.storage.update_job(job_id, updates):
            return {'error': 'Failed to update job'}

        return {
            'job_id': job_id,
            'assigned': True,
            'worker_id': worker['id'],
            'worker_name': worker.get('name'),
            'score': {
                'total': round(score.total_score, 2),
                'tag': round(score.tag_score, 2),
                'load': round(score.load_score, 2),
                'preference': round(score.preference_score, 2)
            }
        }

    def route_pending_jobs(self, limit: int = 10) -> List[Dict]:
        """
        Route multiple pending jobs.

        Routes jobs in priority order until no more assignments can be made.

        Args:
            limit: Maximum number of jobs to route

        Returns:
            List of assignment results
        """
        results = []
        pending = self.storage.get_pending_jobs()[:limit]

        for job in pending:
            result = self.route_job(job['id'])
            results.append(result)

            # Stop if we hit capacity
            if result and not result.get('assigned') and 'No eligible worker' in result.get('reason', ''):
                break

        return results

    def get_worker_recommendations(self, job_id: str) -> List[Dict]:
        """
        Get ranked list of worker recommendations for a job.

        Args:
            job_id: Job ID

        Returns:
            List of worker recommendations with scores
        """
        job = self.storage.get_job(job_id)
        if not job:
            return []

        available = self.get_available_workers()
        recommendations = []

        for worker in available:
            score = self.score_worker(worker, job)
            recommendations.append({
                'worker_id': worker['id'],
                'worker_name': worker.get('name'),
                'eligible': score.eligible,
                'reason': score.reason,
                'scores': {
                    'total': round(score.total_score, 2),
                    'tag': round(score.tag_score, 2),
                    'load': round(score.load_score, 2),
                    'preference': round(score.preference_score, 2)
                }
            })

        # Sort by total score
        recommendations.sort(key=lambda x: x['scores']['total'], reverse=True)

        return recommendations
