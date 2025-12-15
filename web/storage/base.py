"""
Storage Backend Base Class

Defines the interface that all storage backends must implement.
This ensures consistent behavior whether using flat files or MongoDB.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Any


class StorageBackend(ABC):
    """
    Abstract base class for storage backends.

    All storage implementations (flat file, MongoDB) must implement
    these methods to ensure consistent data access patterns.
    """

    # =========================================================================
    # Schedule Operations
    # =========================================================================

    @abstractmethod
    def get_all_schedules(self) -> Dict[str, Dict]:
        """
        Get all schedules.

        Returns:
            Dict mapping schedule_id to schedule data
        """
        pass

    @abstractmethod
    def get_schedule(self, schedule_id: str) -> Optional[Dict]:
        """
        Get a single schedule by ID.

        Args:
            schedule_id: UUID of the schedule

        Returns:
            Schedule dict or None if not found
        """
        pass

    @abstractmethod
    def save_schedule(self, schedule_id: str, schedule: Dict) -> bool:
        """
        Save or update a schedule.

        Args:
            schedule_id: UUID of the schedule
            schedule: Schedule data dict

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def delete_schedule(self, schedule_id: str) -> bool:
        """
        Delete a schedule.

        Args:
            schedule_id: UUID of the schedule

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def save_all_schedules(self, schedules: Dict[str, Dict]) -> bool:
        """
        Save all schedules (bulk operation).

        Args:
            schedules: Dict mapping schedule_id to schedule data

        Returns:
            True if successful
        """
        pass

    # =========================================================================
    # History Operations
    # =========================================================================

    @abstractmethod
    def get_history(self, schedule_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """
        Get execution history.

        Args:
            schedule_id: Filter by schedule (None for all)
            limit: Max entries to return

        Returns:
            List of history entries (newest first)
        """
        pass

    @abstractmethod
    def add_history_entry(self, entry: Dict) -> bool:
        """
        Add a new history entry.

        Args:
            entry: History entry dict with schedule_id, run_id, etc.

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def cleanup_history(self, max_entries: int = 1000) -> int:
        """
        Remove old history entries beyond max_entries.

        Args:
            max_entries: Maximum number of entries to keep

        Returns:
            Number of entries removed
        """
        pass

    # =========================================================================
    # Inventory Operations
    # =========================================================================

    @abstractmethod
    def get_all_inventory(self) -> List[Dict]:
        """
        Get all inventory items.

        Returns:
            List of inventory item dicts
        """
        pass

    @abstractmethod
    def get_inventory_item(self, item_id: str) -> Optional[Dict]:
        """
        Get a single inventory item by ID.

        Args:
            item_id: UUID of the inventory item

        Returns:
            Inventory item dict or None if not found
        """
        pass

    @abstractmethod
    def save_inventory_item(self, item_id: str, item: Dict) -> bool:
        """
        Save or update an inventory item.

        Args:
            item_id: UUID of the inventory item
            item: Inventory item data dict

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def delete_inventory_item(self, item_id: str) -> bool:
        """
        Delete an inventory item.

        Args:
            item_id: UUID of the inventory item

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def search_inventory(self, query: Dict) -> List[Dict]:
        """
        Search inventory items by criteria.

        Args:
            query: Search criteria dict (e.g., {'hostname': 'web*'})

        Returns:
            List of matching inventory items
        """
        pass

    # =========================================================================
    # Host Facts Operations (CMDB/Asset Inventory)
    # Stores collected data from playbook runs per host
    # =========================================================================

    @abstractmethod
    def get_host_facts(self, host: str) -> Optional[Dict]:
        """
        Get all collected facts for a specific host.

        Args:
            host: Hostname or IP address

        Returns:
            Host facts document or None if not found.
            Structure: {
                "host": "192.168.1.50",
                "groups": ["webservers"],
                "collections": {
                    "hardware": {"current": {...}, "last_updated": "...", "history": [...]},
                    "software": {...}
                },
                "first_seen": "...",
                "last_updated": "..."
            }
        """
        pass

    @abstractmethod
    def get_host_collection(self, host: str, collection: str,
                            include_history: bool = False) -> Optional[Dict]:
        """
        Get a specific collection (hardware, software, etc.) for a host.

        Args:
            host: Hostname or IP address
            collection: Collection name (e.g., 'hardware', 'software')
            include_history: Whether to include historical snapshots

        Returns:
            Collection data or None if not found.
            Structure: {
                "current": {...collected data...},
                "last_updated": "...",
                "history": [...] (if include_history=True)
            }
        """
        pass

    @abstractmethod
    def save_host_facts(self, host: str, collection: str, data: Dict,
                        groups: List[str] = None, source: str = None) -> Dict:
        """
        Save collected facts for a host. Automatically handles diff-based history.

        Args:
            host: Hostname or IP address
            collection: Collection name (e.g., 'hardware', 'software')
            data: The collected data to store
            groups: Ansible groups this host belongs to
            source: Source of data ('playbook', 'callback', 'manual')

        Returns:
            Dict with save result: {
                "status": "created|updated|unchanged",
                "changes": {...} (if updated),
                "host": "...",
                "collection": "..."
            }
        """
        pass

    @abstractmethod
    def get_all_hosts(self) -> List[Dict]:
        """
        Get summary of all hosts with collected facts.

        Returns:
            List of host summaries: [{
                "host": "...",
                "groups": [...],
                "collections": ["hardware", "software", ...],
                "last_updated": "..."
            }]
        """
        pass

    @abstractmethod
    def get_hosts_by_group(self, group: str) -> List[Dict]:
        """
        Get all hosts belonging to a specific group.

        Args:
            group: Ansible group name

        Returns:
            List of host summaries for hosts in that group
        """
        pass

    @abstractmethod
    def get_host_history(self, host: str, collection: str,
                         limit: int = 50) -> List[Dict]:
        """
        Get historical changes for a host's collection.

        Args:
            host: Hostname or IP address
            collection: Collection name
            limit: Max history entries to return

        Returns:
            List of historical snapshots with diffs
        """
        pass

    @abstractmethod
    def delete_host_facts(self, host: str, collection: str = None) -> bool:
        """
        Delete facts for a host.

        Args:
            host: Hostname or IP address
            collection: Specific collection to delete, or None for all

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def import_host_facts(self, host_data: Dict) -> bool:
        """
        Import a complete host facts document (used for migration).

        This method imports raw host data including history without
        applying diff-based processing. Used by migration scripts.

        Args:
            host_data: Complete host document with structure:
                {
                    "host": "hostname",
                    "groups": [...],
                    "collections": {
                        "hardware": {"current": {...}, "history": [...], ...}
                    },
                    "first_seen": "...",
                    "last_updated": "..."
                }

        Returns:
            True if imported successfully, False otherwise
        """
        pass

    # =========================================================================
    # Batch Job Operations
    # =========================================================================

    @abstractmethod
    def get_all_batch_jobs(self) -> List[Dict]:
        """
        Get all batch jobs.

        Returns:
            List of batch job dicts, sorted by created date (newest first)
        """
        pass

    @abstractmethod
    def get_batch_job(self, batch_id: str) -> Optional[Dict]:
        """
        Get a single batch job by ID.

        Args:
            batch_id: UUID of the batch job

        Returns:
            Batch job dict or None if not found
        """
        pass

    @abstractmethod
    def save_batch_job(self, batch_id: str, batch_job: Dict) -> bool:
        """
        Save or update a batch job.

        Args:
            batch_id: UUID of the batch job
            batch_job: Batch job data dict with structure:
                {
                    "id": "uuid",
                    "name": "optional display name",
                    "playbooks": ["playbook1.yml", "playbook2.yml"],
                    "targets": ["host1", "group1"],
                    "status": "pending|running|completed|failed|partial",
                    "total": int,
                    "completed": int,
                    "failed": int,
                    "current_playbook": "playbook.yml" or None,
                    "current_run_id": "run_id" or None,
                    "results": [
                        {
                            "playbook": "playbook.yml",
                            "target": "host1",
                            "status": "completed|failed|running",
                            "run_id": "...",
                            "log_file": "...",
                            "started": "ISO timestamp",
                            "finished": "ISO timestamp"
                        }
                    ],
                    "created": "ISO timestamp",
                    "started": "ISO timestamp" or None,
                    "finished": "ISO timestamp" or None
                }

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def delete_batch_job(self, batch_id: str) -> bool:
        """
        Delete a batch job.

        Args:
            batch_id: UUID of the batch job

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def get_batch_jobs_by_status(self, status: str) -> List[Dict]:
        """
        Get batch jobs filtered by status.

        Args:
            status: Status to filter by (pending, running, completed, failed, partial)

        Returns:
            List of matching batch job dicts
        """
        pass

    @abstractmethod
    def cleanup_batch_jobs(self, max_age_days: int = 30, keep_count: int = 100) -> int:
        """
        Clean up old batch jobs.

        Keeps at minimum keep_count jobs, and removes jobs older than max_age_days.

        Args:
            max_age_days: Maximum age in days for batch jobs
            keep_count: Minimum number of batch jobs to keep regardless of age

        Returns:
            Number of batch jobs removed
        """
        pass

    # =========================================================================
    # Utility Operations
    # =========================================================================

    # =========================================================================
    # Worker Operations (Cluster Support)
    # =========================================================================

    @abstractmethod
    def get_all_workers(self) -> List[Dict]:
        """
        Get all registered workers.

        Returns:
            List of worker dicts, sorted by registered_at (newest first)
        """
        pass

    @abstractmethod
    def get_worker(self, worker_id: str) -> Optional[Dict]:
        """
        Get a single worker by ID.

        Args:
            worker_id: UUID of the worker (or '__local__' for local executor)

        Returns:
            Worker dict or None if not found.
            Structure: {
                "id": "uuid",
                "name": "worker-01",
                "tags": ["network-a", "gpu"],
                "priority_boost": 0,
                "status": "online|offline|busy|stale",
                "is_local": false,
                "registered_at": "ISO timestamp",
                "last_checkin": "ISO timestamp",
                "sync_revision": "git-sha",
                "current_jobs": ["job-id", ...],
                "stats": {
                    "load_1m": 0.5,
                    "memory_percent": 45,
                    "jobs_completed": 150,
                    "jobs_failed": 3,
                    "avg_job_duration": 120
                }
            }
        """
        pass

    @abstractmethod
    def save_worker(self, worker: Dict) -> bool:
        """
        Save or update a worker.

        Args:
            worker: Worker data dict (must include 'id')

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def delete_worker(self, worker_id: str) -> bool:
        """
        Delete a worker.

        Args:
            worker_id: UUID of the worker

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def get_workers_by_status(self, statuses: List[str]) -> List[Dict]:
        """
        Get workers filtered by status.

        Args:
            statuses: List of statuses to filter by (e.g., ['online', 'busy'])

        Returns:
            List of matching worker dicts
        """
        pass

    @abstractmethod
    def update_worker_checkin(self, worker_id: str, checkin_data: Dict) -> bool:
        """
        Update worker with checkin data.

        Args:
            worker_id: UUID of the worker
            checkin_data: Dict with checkin info (stats, sync_revision, etc.)

        Returns:
            True if successful, False if worker not found
        """
        pass

    # =========================================================================
    # Job Queue Operations (Cluster Support)
    # =========================================================================

    @abstractmethod
    def get_all_jobs(self, filters: Dict = None) -> List[Dict]:
        """
        Get all jobs from the queue, optionally filtered.

        Args:
            filters: Optional dict of filters (status, playbook, assigned_worker, etc.)

        Returns:
            List of job dicts, sorted by submitted_at (newest first)
        """
        pass

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[Dict]:
        """
        Get a single job by ID.

        Args:
            job_id: UUID of the job

        Returns:
            Job dict or None if not found.
            Structure: {
                "id": "uuid",
                "playbook": "hardware-inventory.yml",
                "target": "webservers",
                "required_tags": ["network-a"],
                "preferred_tags": ["high-memory"],
                "priority": 50,
                "job_type": "normal|long_running",
                "status": "queued|assigned|running|completed|failed|cancelled",
                "assigned_worker": "worker-id|null|__local__",
                "submitted_by": "user|schedule:id",
                "submitted_at": "ISO timestamp",
                "assigned_at": "ISO timestamp|null",
                "started_at": "ISO timestamp|null",
                "completed_at": "ISO timestamp|null",
                "log_file": "path|null",
                "exit_code": "int|null",
                "error_message": "string|null"
            }
        """
        pass

    @abstractmethod
    def save_job(self, job: Dict) -> bool:
        """
        Save or update a job.

        Args:
            job: Job data dict (must include 'id')

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def update_job(self, job_id: str, updates: Dict) -> bool:
        """
        Partially update a job.

        Args:
            job_id: UUID of the job
            updates: Dict of fields to update

        Returns:
            True if successful, False if job not found
        """
        pass

    @abstractmethod
    def delete_job(self, job_id: str) -> bool:
        """
        Delete a job.

        Args:
            job_id: UUID of the job

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def get_pending_jobs(self) -> List[Dict]:
        """
        Get all jobs with status 'queued' awaiting assignment.

        Returns:
            List of pending job dicts, sorted by priority (highest first),
            then by submitted_at (oldest first)
        """
        pass

    @abstractmethod
    def get_worker_jobs(self, worker_id: str, statuses: List[str] = None) -> List[Dict]:
        """
        Get jobs assigned to a specific worker.

        Args:
            worker_id: UUID of the worker
            statuses: Optional list of statuses to filter by

        Returns:
            List of job dicts for that worker
        """
        pass

    @abstractmethod
    def cleanup_jobs(self, max_age_days: int = 30, keep_count: int = 500) -> int:
        """
        Clean up old completed/failed jobs.

        Keeps at minimum keep_count jobs, and removes completed/failed jobs
        older than max_age_days.

        Args:
            max_age_days: Maximum age in days for completed jobs
            keep_count: Minimum number of jobs to keep regardless of age

        Returns:
            Number of jobs removed
        """
        pass

    # =========================================================================
    # Utility Operations
    # =========================================================================

    @abstractmethod
    def health_check(self) -> bool:
        """
        Check if storage backend is healthy and accessible.

        Returns:
            True if healthy, False otherwise
        """
        pass

    @abstractmethod
    def get_backend_type(self) -> str:
        """
        Get the type of storage backend.

        Returns:
            'flatfile' or 'mongodb'
        """
        pass


# =============================================================================
# Utility Functions for Diff-Based History
# =============================================================================

def compute_diff(old_data: Dict, new_data: Dict, path: str = '') -> Dict:
    """
    Compute the difference between two data dictionaries.

    Recursively drills into nested dicts to find actual leaf-level changes,
    storing changes with dot-notation paths (e.g., 'memory.free_mb').

    Args:
        old_data: Previous data state
        new_data: New data state
        path: Current path prefix for nested keys (internal use)

    Returns:
        Diff dict with 'added', 'removed', 'changed' keys.
        Changed values include 'old' and 'new' for leaf values.
    """
    diff = {
        'added': {},
        'removed': {},
        'changed': {}
    }

    old_keys = set(old_data.keys()) if old_data else set()
    new_keys = set(new_data.keys()) if new_data else set()

    # Keys added in new data
    for key in new_keys - old_keys:
        full_key = f"{path}.{key}" if path else key
        diff['added'][full_key] = new_data[key]

    # Keys removed from old data
    for key in old_keys - new_keys:
        full_key = f"{path}.{key}" if path else key
        diff['removed'][full_key] = old_data[key]

    # Keys in both - check for changes
    for key in old_keys & new_keys:
        old_val = old_data[key]
        new_val = new_data[key]
        full_key = f"{path}.{key}" if path else key

        if old_val != new_val:
            if isinstance(old_val, dict) and isinstance(new_val, dict):
                # Recursive diff for nested dicts - drill down to find actual changes
                nested_diff = compute_diff(old_val, new_val, full_key)
                # Merge nested results into our diff (they already have full paths)
                diff['added'].update(nested_diff['added'])
                diff['removed'].update(nested_diff['removed'])
                diff['changed'].update(nested_diff['changed'])
            elif isinstance(old_val, list) and isinstance(new_val, list):
                # For lists, compute a summary of changes
                diff['changed'][full_key] = _compute_list_diff(old_val, new_val)
            else:
                # Leaf value changed
                diff['changed'][full_key] = {
                    'old': old_val,
                    'new': new_val
                }

    return diff


def _compute_list_diff(old_list: list, new_list: list) -> Dict:
    """
    Compute a summary diff for list changes.

    Instead of storing full lists, stores:
    - Items added (in new but not old)
    - Items removed (in old but not new)
    - Length change

    For large lists of dicts/complex objects, just stores counts.
    """
    result = {
        'old_length': len(old_list),
        'new_length': len(new_list)
    }

    # For simple scalar lists, compute actual added/removed items
    try:
        # Convert to sets for comparison (only works for hashable items)
        old_set = set(old_list) if all(isinstance(x, (str, int, float, bool, type(None))) for x in old_list) else None
        new_set = set(new_list) if all(isinstance(x, (str, int, float, bool, type(None))) for x in new_list) else None

        if old_set is not None and new_set is not None:
            added = new_set - old_set
            removed = old_set - new_set
            if added:
                result['items_added'] = list(added)[:10]  # Limit to 10 for display
                if len(added) > 10:
                    result['items_added_count'] = len(added)
            if removed:
                result['items_removed'] = list(removed)[:10]
                if len(removed) > 10:
                    result['items_removed_count'] = len(removed)
        else:
            # Complex objects - just note the change
            result['note'] = 'List of complex objects changed'
    except TypeError:
        # Unhashable types
        result['note'] = 'List contents changed'

    return result


def is_empty_diff(diff: Dict) -> bool:
    """Check if a diff represents no changes."""
    return not diff.get('added') and not diff.get('removed') and not diff.get('changed')


def summarize_diff(diff: Dict, max_items: int = 10) -> Dict:
    """
    Create a human-readable summary of a diff.

    Args:
        diff: The diff dict from compute_diff()
        max_items: Maximum number of items to include per category

    Returns:
        Summary dict with counts and key examples
    """
    summary = {
        'total_changes': 0,
        'added_count': len(diff.get('added', {})),
        'removed_count': len(diff.get('removed', {})),
        'changed_count': len(diff.get('changed', {})),
        'added_keys': [],
        'removed_keys': [],
        'changed_keys': []
    }

    summary['total_changes'] = (
        summary['added_count'] +
        summary['removed_count'] +
        summary['changed_count']
    )

    # Get sample keys for display
    summary['added_keys'] = list(diff.get('added', {}).keys())[:max_items]
    summary['removed_keys'] = list(diff.get('removed', {}).keys())[:max_items]
    summary['changed_keys'] = list(diff.get('changed', {}).keys())[:max_items]

    return summary
