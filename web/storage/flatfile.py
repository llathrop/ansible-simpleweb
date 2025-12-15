"""
Flat File Storage Backend

Implements storage using JSON files for persistence.
This is the original storage method, now wrapped in the StorageBackend interface.

File structure:
- config/schedules.json - Schedule definitions
- config/schedule_history.json - Execution history
- config/inventory.json - Inventory items
- config/host_facts.json - Collected host facts (CMDB)
"""

import json
import os
import threading
import fnmatch
from datetime import datetime
from typing import Dict, List, Optional, Any

from .base import StorageBackend, compute_diff, is_empty_diff


class FlatFileStorage(StorageBackend):
    """
    Flat file storage implementation using JSON files.

    Thread-safe with locks for concurrent access.
    Files are created automatically if they don't exist.
    """

    def __init__(self, config_dir: str = '/app/config'):
        """
        Initialize flat file storage.

        Args:
            config_dir: Directory for config files
        """
        self.config_dir = config_dir
        self.schedules_file = os.path.join(config_dir, 'schedules.json')
        self.history_file = os.path.join(config_dir, 'schedule_history.json')
        self.inventory_file = os.path.join(config_dir, 'inventory.json')
        self.host_facts_file = os.path.join(config_dir, 'host_facts.json')
        self.batch_jobs_file = os.path.join(config_dir, 'batch_jobs.json')
        self.workers_file = os.path.join(config_dir, 'workers.json')
        self.job_queue_file = os.path.join(config_dir, 'job_queue.json')

        # Thread safety locks
        self._schedules_lock = threading.RLock()
        self._history_lock = threading.RLock()
        self._inventory_lock = threading.RLock()
        self._host_facts_lock = threading.RLock()
        self._batch_jobs_lock = threading.RLock()
        self._workers_lock = threading.RLock()
        self._job_queue_lock = threading.RLock()

        # Ensure config directory exists
        os.makedirs(config_dir, exist_ok=True)

    # =========================================================================
    # Schedule Operations
    # =========================================================================

    def get_all_schedules(self) -> Dict[str, Dict]:
        """Get all schedules from file."""
        with self._schedules_lock:
            if not os.path.exists(self.schedules_file):
                return {}
            try:
                with open(self.schedules_file, 'r') as f:
                    data = json.load(f)
                    return data.get('schedules', {})
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading schedules: {e}")
                return {}

    def get_schedule(self, schedule_id: str) -> Optional[Dict]:
        """Get a single schedule by ID."""
        schedules = self.get_all_schedules()
        return schedules.get(schedule_id)

    def save_schedule(self, schedule_id: str, schedule: Dict) -> bool:
        """Save or update a schedule."""
        with self._schedules_lock:
            schedules = self.get_all_schedules()
            schedules[schedule_id] = schedule
            return self._write_schedules(schedules)

    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a schedule."""
        with self._schedules_lock:
            schedules = self.get_all_schedules()
            if schedule_id in schedules:
                del schedules[schedule_id]
                return self._write_schedules(schedules)
            return False

    def save_all_schedules(self, schedules: Dict[str, Dict]) -> bool:
        """Save all schedules (bulk operation)."""
        with self._schedules_lock:
            return self._write_schedules(schedules)

    def _write_schedules(self, schedules: Dict[str, Dict]) -> bool:
        """Write schedules to file."""
        try:
            data = {
                'version': '1.0',
                'schedules': schedules
            }
            with open(self.schedules_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except IOError as e:
            print(f"Error writing schedules: {e}")
            return False

    # =========================================================================
    # History Operations
    # =========================================================================

    def get_history(self, schedule_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Get execution history."""
        with self._history_lock:
            if not os.path.exists(self.history_file):
                return []
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    history = data.get('history', [])

                # Filter by schedule if specified
                if schedule_id:
                    history = [h for h in history if h.get('schedule_id') == schedule_id]

                return history[:limit]
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading history: {e}")
                return []

    def add_history_entry(self, entry: Dict) -> bool:
        """Add a new history entry."""
        with self._history_lock:
            try:
                if os.path.exists(self.history_file):
                    with open(self.history_file, 'r') as f:
                        data = json.load(f)
                else:
                    data = {'version': '1.0', 'history': []}

                # Insert at beginning (newest first)
                data['history'].insert(0, entry)

                with open(self.history_file, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                return True
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error adding history entry: {e}")
                return False

    def cleanup_history(self, max_entries: int = 1000) -> int:
        """Remove old history entries beyond max_entries."""
        with self._history_lock:
            try:
                if not os.path.exists(self.history_file):
                    return 0

                with open(self.history_file, 'r') as f:
                    data = json.load(f)

                history = data.get('history', [])
                original_count = len(history)

                if original_count <= max_entries:
                    return 0

                # Trim to max entries
                data['history'] = history[:max_entries]

                with open(self.history_file, 'w') as f:
                    json.dump(data, f, indent=2, default=str)

                return original_count - max_entries
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error cleaning up history: {e}")
                return 0

    # =========================================================================
    # Inventory Operations
    # =========================================================================

    def get_all_inventory(self) -> List[Dict]:
        """Get all inventory items."""
        with self._inventory_lock:
            if not os.path.exists(self.inventory_file):
                return []
            try:
                with open(self.inventory_file, 'r') as f:
                    data = json.load(f)
                    return data.get('inventory', [])
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading inventory: {e}")
                return []

    def get_inventory_item(self, item_id: str) -> Optional[Dict]:
        """Get a single inventory item by ID."""
        inventory = self.get_all_inventory()
        for item in inventory:
            if item.get('id') == item_id:
                return item
        return None

    def save_inventory_item(self, item_id: str, item: Dict) -> bool:
        """Save or update an inventory item."""
        with self._inventory_lock:
            try:
                inventory = self.get_all_inventory()

                # Find and update existing or append new
                found = False
                for i, existing in enumerate(inventory):
                    if existing.get('id') == item_id:
                        inventory[i] = item
                        found = True
                        break

                if not found:
                    inventory.append(item)

                return self._write_inventory(inventory)
            except Exception as e:
                print(f"Error saving inventory item: {e}")
                return False

    def delete_inventory_item(self, item_id: str) -> bool:
        """Delete an inventory item."""
        with self._inventory_lock:
            try:
                inventory = self.get_all_inventory()
                original_len = len(inventory)
                inventory = [item for item in inventory if item.get('id') != item_id]

                if len(inventory) < original_len:
                    return self._write_inventory(inventory)
                return False
            except Exception as e:
                print(f"Error deleting inventory item: {e}")
                return False

    def search_inventory(self, query: Dict) -> List[Dict]:
        """Search inventory items by criteria."""
        inventory = self.get_all_inventory()
        results = []

        for item in inventory:
            match = True
            for key, pattern in query.items():
                item_value = item.get(key, '')
                if isinstance(pattern, str) and '*' in pattern:
                    # Wildcard matching
                    if not fnmatch.fnmatch(str(item_value), pattern):
                        match = False
                        break
                elif item_value != pattern:
                    match = False
                    break

            if match:
                results.append(item)

        return results

    def _write_inventory(self, inventory: List[Dict]) -> bool:
        """Write inventory to file."""
        try:
            data = {
                'version': '1.0',
                'inventory': inventory
            }
            with open(self.inventory_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except IOError as e:
            print(f"Error writing inventory: {e}")
            return False

    # =========================================================================
    # Host Facts Operations (CMDB)
    # =========================================================================

    def _load_host_facts_data(self) -> Dict:
        """Load all host facts data from file."""
        if not os.path.exists(self.host_facts_file):
            return {'version': '1.0', 'hosts': {}}
        try:
            with open(self.host_facts_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading host facts: {e}")
            return {'version': '1.0', 'hosts': {}}

    def _write_host_facts_data(self, data: Dict) -> bool:
        """Write all host facts data to file."""
        try:
            with open(self.host_facts_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except IOError as e:
            print(f"Error writing host facts: {e}")
            return False

    def get_host_facts(self, host: str) -> Optional[Dict]:
        """Get all collected facts for a specific host."""
        with self._host_facts_lock:
            data = self._load_host_facts_data()
            return data.get('hosts', {}).get(host)

    def get_host_collection(self, host: str, collection: str,
                            include_history: bool = False) -> Optional[Dict]:
        """Get a specific collection for a host."""
        with self._host_facts_lock:
            data = self._load_host_facts_data()
            host_data = data.get('hosts', {}).get(host)
            if not host_data:
                return None

            collection_data = host_data.get('collections', {}).get(collection)
            if not collection_data:
                return None

            if include_history:
                return collection_data
            else:
                # Return without history
                return {
                    'current': collection_data.get('current'),
                    'last_updated': collection_data.get('last_updated')
                }

    def save_host_facts(self, host: str, collection: str, data: Dict,
                        groups: List[str] = None, source: str = None) -> Dict:
        """Save collected facts for a host with diff-based history."""
        with self._host_facts_lock:
            now = datetime.now().isoformat()
            all_data = self._load_host_facts_data()

            if 'hosts' not in all_data:
                all_data['hosts'] = {}

            # Initialize host if new
            if host not in all_data['hosts']:
                all_data['hosts'][host] = {
                    'host': host,
                    'groups': groups or [],
                    'collections': {},
                    'first_seen': now,
                    'last_updated': now
                }
                status = 'created'
            else:
                status = 'updated'
                # Update groups if provided
                if groups:
                    existing_groups = set(all_data['hosts'][host].get('groups', []))
                    all_data['hosts'][host]['groups'] = list(existing_groups | set(groups))

            host_entry = all_data['hosts'][host]

            # Initialize collection if new
            if collection not in host_entry['collections']:
                host_entry['collections'][collection] = {
                    'current': data,
                    'last_updated': now,
                    'source': source,
                    'history': []
                }
                changes = None
            else:
                # Compute diff with existing data
                coll = host_entry['collections'][collection]
                old_data = coll.get('current', {})
                diff = compute_diff(old_data, data)

                if is_empty_diff(diff):
                    # No changes
                    return {
                        'status': 'unchanged',
                        'host': host,
                        'collection': collection
                    }

                # Store diff in history (keeps old state recoverable)
                history_entry = {
                    'timestamp': coll.get('last_updated', now),
                    'source': coll.get('source'),
                    'diff_from_next': diff  # Diff to reconstruct this version from next
                }

                # Prepend to history (newest first)
                if 'history' not in coll:
                    coll['history'] = []
                coll['history'].insert(0, history_entry)

                # Limit history to 100 entries per collection
                coll['history'] = coll['history'][:100]

                # Update current data
                coll['current'] = data
                coll['last_updated'] = now
                coll['source'] = source
                changes = diff

            # Update host last_updated
            host_entry['last_updated'] = now

            # Save to file
            self._write_host_facts_data(all_data)

            result = {
                'status': status,
                'host': host,
                'collection': collection
            }
            if changes:
                result['changes'] = changes

            return result

    def get_all_hosts(self) -> List[Dict]:
        """Get summary of all hosts with collected facts."""
        with self._host_facts_lock:
            data = self._load_host_facts_data()
            hosts = []

            for host, host_data in data.get('hosts', {}).items():
                hosts.append({
                    'host': host,
                    'groups': host_data.get('groups', []),
                    'collections': list(host_data.get('collections', {}).keys()),
                    'first_seen': host_data.get('first_seen'),
                    'last_updated': host_data.get('last_updated')
                })

            # Sort by last_updated (newest first)
            hosts.sort(key=lambda x: x.get('last_updated', ''), reverse=True)
            return hosts

    def get_hosts_by_group(self, group: str) -> List[Dict]:
        """Get all hosts belonging to a specific group."""
        all_hosts = self.get_all_hosts()
        return [h for h in all_hosts if group in h.get('groups', [])]

    def get_host_history(self, host: str, collection: str,
                         limit: int = 50) -> List[Dict]:
        """Get historical changes for a host's collection."""
        with self._host_facts_lock:
            data = self._load_host_facts_data()
            host_data = data.get('hosts', {}).get(host)
            if not host_data:
                return []

            coll = host_data.get('collections', {}).get(collection)
            if not coll:
                return []

            history = coll.get('history', [])
            return history[:limit]

    def delete_host_facts(self, host: str, collection: str = None) -> bool:
        """Delete facts for a host."""
        with self._host_facts_lock:
            data = self._load_host_facts_data()

            if host not in data.get('hosts', {}):
                return False

            if collection:
                # Delete specific collection
                if collection in data['hosts'][host].get('collections', {}):
                    del data['hosts'][host]['collections'][collection]
                    self._write_host_facts_data(data)
                    return True
                return False
            else:
                # Delete entire host
                del data['hosts'][host]
                self._write_host_facts_data(data)
                return True

    def import_host_facts(self, host_data: Dict) -> bool:
        """
        Import a complete host facts document (used for migration).

        Directly writes the host document without diff processing,
        preserving all history and metadata from the source.

        Args:
            host_data: Complete host document

        Returns:
            True if imported successfully
        """
        with self._host_facts_lock:
            host = host_data.get('host')
            if not host:
                return False

            data = self._load_host_facts_data()
            if 'hosts' not in data:
                data['hosts'] = {}

            # Directly set the host data (overwrites if exists)
            data['hosts'][host] = host_data
            return self._write_host_facts_data(data)

    # =========================================================================
    # Batch Job Operations
    # =========================================================================

    def _load_batch_jobs_data(self) -> Dict:
        """Load all batch jobs data from file."""
        if not os.path.exists(self.batch_jobs_file):
            return {'version': '1.0', 'batch_jobs': []}
        try:
            with open(self.batch_jobs_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading batch jobs: {e}")
            return {'version': '1.0', 'batch_jobs': []}

    def _write_batch_jobs_data(self, data: Dict) -> bool:
        """Write all batch jobs data to file."""
        try:
            with open(self.batch_jobs_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except IOError as e:
            print(f"Error writing batch jobs: {e}")
            return False

    def get_all_batch_jobs(self) -> List[Dict]:
        """Get all batch jobs, sorted by created date (newest first)."""
        with self._batch_jobs_lock:
            data = self._load_batch_jobs_data()
            batch_jobs = data.get('batch_jobs', [])
            # Sort by created date (newest first)
            batch_jobs.sort(key=lambda x: x.get('created', ''), reverse=True)
            return batch_jobs

    def get_batch_job(self, batch_id: str) -> Optional[Dict]:
        """Get a single batch job by ID."""
        with self._batch_jobs_lock:
            data = self._load_batch_jobs_data()
            for job in data.get('batch_jobs', []):
                if job.get('id') == batch_id:
                    return job
            return None

    def save_batch_job(self, batch_id: str, batch_job: Dict) -> bool:
        """Save or update a batch job."""
        with self._batch_jobs_lock:
            try:
                data = self._load_batch_jobs_data()
                batch_jobs = data.get('batch_jobs', [])

                # Ensure id is in the batch job
                batch_job['id'] = batch_id

                # Find and update existing or append new
                found = False
                for i, existing in enumerate(batch_jobs):
                    if existing.get('id') == batch_id:
                        batch_jobs[i] = batch_job
                        found = True
                        break

                if not found:
                    batch_jobs.append(batch_job)

                data['batch_jobs'] = batch_jobs
                return self._write_batch_jobs_data(data)
            except Exception as e:
                print(f"Error saving batch job: {e}")
                return False

    def delete_batch_job(self, batch_id: str) -> bool:
        """Delete a batch job."""
        with self._batch_jobs_lock:
            try:
                data = self._load_batch_jobs_data()
                batch_jobs = data.get('batch_jobs', [])
                original_len = len(batch_jobs)
                batch_jobs = [job for job in batch_jobs if job.get('id') != batch_id]

                if len(batch_jobs) < original_len:
                    data['batch_jobs'] = batch_jobs
                    return self._write_batch_jobs_data(data)
                return False
            except Exception as e:
                print(f"Error deleting batch job: {e}")
                return False

    def get_batch_jobs_by_status(self, status: str) -> List[Dict]:
        """Get batch jobs filtered by status."""
        with self._batch_jobs_lock:
            data = self._load_batch_jobs_data()
            batch_jobs = data.get('batch_jobs', [])
            filtered = [job for job in batch_jobs if job.get('status') == status]
            # Sort by created date (newest first)
            filtered.sort(key=lambda x: x.get('created', ''), reverse=True)
            return filtered

    def cleanup_batch_jobs(self, max_age_days: int = 30, keep_count: int = 100) -> int:
        """Clean up old batch jobs."""
        with self._batch_jobs_lock:
            try:
                data = self._load_batch_jobs_data()
                batch_jobs = data.get('batch_jobs', [])

                if len(batch_jobs) <= keep_count:
                    return 0

                # Sort by created date (newest first)
                batch_jobs.sort(key=lambda x: x.get('created', ''), reverse=True)

                # Calculate cutoff date
                from datetime import timedelta
                cutoff = datetime.now() - timedelta(days=max_age_days)
                cutoff_str = cutoff.isoformat()

                # Keep jobs that are either:
                # 1. Within the keep_count (newest jobs)
                # 2. Newer than cutoff date
                # 3. Still running (never delete running jobs)
                jobs_to_keep = []
                removed_count = 0

                for i, job in enumerate(batch_jobs):
                    created = job.get('created', '')
                    status = job.get('status', '')

                    # Always keep running jobs
                    if status == 'running':
                        jobs_to_keep.append(job)
                    # Keep if within keep_count
                    elif i < keep_count:
                        jobs_to_keep.append(job)
                    # Keep if newer than cutoff
                    elif created >= cutoff_str:
                        jobs_to_keep.append(job)
                    else:
                        removed_count += 1

                if removed_count > 0:
                    data['batch_jobs'] = jobs_to_keep
                    self._write_batch_jobs_data(data)

                return removed_count
            except Exception as e:
                print(f"Error cleaning up batch jobs: {e}")
                return 0

    # =========================================================================
    # Worker Operations (Cluster Support)
    # =========================================================================

    def _load_workers_data(self) -> Dict:
        """Load all workers data from file."""
        if not os.path.exists(self.workers_file):
            return {'version': '1.0', 'workers': []}
        try:
            with open(self.workers_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading workers: {e}")
            return {'version': '1.0', 'workers': []}

    def _write_workers_data(self, data: Dict) -> bool:
        """Write all workers data to file."""
        try:
            with open(self.workers_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except IOError as e:
            print(f"Error writing workers: {e}")
            return False

    def get_all_workers(self) -> List[Dict]:
        """Get all registered workers, sorted by registered_at (newest first)."""
        with self._workers_lock:
            data = self._load_workers_data()
            workers = data.get('workers', [])
            workers.sort(key=lambda x: x.get('registered_at', ''), reverse=True)
            return workers

    def get_worker(self, worker_id: str) -> Optional[Dict]:
        """Get a single worker by ID."""
        with self._workers_lock:
            data = self._load_workers_data()
            for worker in data.get('workers', []):
                if worker.get('id') == worker_id:
                    return worker
            return None

    def save_worker(self, worker: Dict) -> bool:
        """Save or update a worker."""
        with self._workers_lock:
            try:
                data = self._load_workers_data()
                workers = data.get('workers', [])
                worker_id = worker.get('id')

                if not worker_id:
                    print("Error: Worker must have an 'id' field")
                    return False

                # Find and update existing or append new
                found = False
                for i, existing in enumerate(workers):
                    if existing.get('id') == worker_id:
                        workers[i] = worker
                        found = True
                        break

                if not found:
                    workers.append(worker)

                data['workers'] = workers
                return self._write_workers_data(data)
            except Exception as e:
                print(f"Error saving worker: {e}")
                return False

    def delete_worker(self, worker_id: str) -> bool:
        """Delete a worker."""
        with self._workers_lock:
            try:
                data = self._load_workers_data()
                workers = data.get('workers', [])
                original_len = len(workers)
                workers = [w for w in workers if w.get('id') != worker_id]

                if len(workers) < original_len:
                    data['workers'] = workers
                    return self._write_workers_data(data)
                return False
            except Exception as e:
                print(f"Error deleting worker: {e}")
                return False

    def get_workers_by_status(self, statuses: List[str]) -> List[Dict]:
        """Get workers filtered by status."""
        with self._workers_lock:
            data = self._load_workers_data()
            workers = data.get('workers', [])
            filtered = [w for w in workers if w.get('status') in statuses]
            filtered.sort(key=lambda x: x.get('registered_at', ''), reverse=True)
            return filtered

    def update_worker_checkin(self, worker_id: str, checkin_data: Dict) -> bool:
        """Update worker with checkin data."""
        with self._workers_lock:
            try:
                data = self._load_workers_data()
                workers = data.get('workers', [])

                for i, worker in enumerate(workers):
                    if worker.get('id') == worker_id:
                        # Update checkin timestamp
                        worker['last_checkin'] = datetime.now().isoformat()

                        # Update stats if provided
                        if 'stats' in checkin_data:
                            if 'stats' not in worker:
                                worker['stats'] = {}
                            worker['stats'].update(checkin_data['stats'])

                        # Update sync revision if provided
                        if 'sync_revision' in checkin_data:
                            worker['sync_revision'] = checkin_data['sync_revision']

                        # Update status if provided
                        if 'status' in checkin_data:
                            worker['status'] = checkin_data['status']

                        workers[i] = worker
                        data['workers'] = workers
                        return self._write_workers_data(data)

                return False  # Worker not found
            except Exception as e:
                print(f"Error updating worker checkin: {e}")
                return False

    # =========================================================================
    # Job Queue Operations (Cluster Support)
    # =========================================================================

    def _load_job_queue_data(self) -> Dict:
        """Load all job queue data from file."""
        if not os.path.exists(self.job_queue_file):
            return {'version': '1.0', 'jobs': []}
        try:
            with open(self.job_queue_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading job queue: {e}")
            return {'version': '1.0', 'jobs': []}

    def _write_job_queue_data(self, data: Dict) -> bool:
        """Write all job queue data to file."""
        try:
            with open(self.job_queue_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except IOError as e:
            print(f"Error writing job queue: {e}")
            return False

    def get_all_jobs(self, filters: Dict = None) -> List[Dict]:
        """Get all jobs from the queue, optionally filtered."""
        with self._job_queue_lock:
            data = self._load_job_queue_data()
            jobs = data.get('jobs', [])

            if filters:
                filtered_jobs = []
                for job in jobs:
                    match = True
                    for key, value in filters.items():
                        job_value = job.get(key)
                        # Support list-based filtering (e.g., status: ['queued', 'running'])
                        if isinstance(value, list):
                            if job_value not in value:
                                match = False
                                break
                        elif job_value != value:
                            match = False
                            break
                    if match:
                        filtered_jobs.append(job)
                jobs = filtered_jobs

            # Sort by submitted_at (newest first)
            jobs.sort(key=lambda x: x.get('submitted_at', ''), reverse=True)
            return jobs

    def get_job(self, job_id: str) -> Optional[Dict]:
        """Get a single job by ID."""
        with self._job_queue_lock:
            data = self._load_job_queue_data()
            for job in data.get('jobs', []):
                if job.get('id') == job_id:
                    return job
            return None

    def save_job(self, job: Dict) -> bool:
        """Save or update a job."""
        with self._job_queue_lock:
            try:
                data = self._load_job_queue_data()
                jobs = data.get('jobs', [])
                job_id = job.get('id')

                if not job_id:
                    print("Error: Job must have an 'id' field")
                    return False

                # Find and update existing or append new
                found = False
                for i, existing in enumerate(jobs):
                    if existing.get('id') == job_id:
                        jobs[i] = job
                        found = True
                        break

                if not found:
                    jobs.append(job)

                data['jobs'] = jobs
                return self._write_job_queue_data(data)
            except Exception as e:
                print(f"Error saving job: {e}")
                return False

    def update_job(self, job_id: str, updates: Dict) -> bool:
        """Partially update a job."""
        with self._job_queue_lock:
            try:
                data = self._load_job_queue_data()
                jobs = data.get('jobs', [])

                for i, job in enumerate(jobs):
                    if job.get('id') == job_id:
                        job.update(updates)
                        jobs[i] = job
                        data['jobs'] = jobs
                        return self._write_job_queue_data(data)

                return False  # Job not found
            except Exception as e:
                print(f"Error updating job: {e}")
                return False

    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        with self._job_queue_lock:
            try:
                data = self._load_job_queue_data()
                jobs = data.get('jobs', [])
                original_len = len(jobs)
                jobs = [j for j in jobs if j.get('id') != job_id]

                if len(jobs) < original_len:
                    data['jobs'] = jobs
                    return self._write_job_queue_data(data)
                return False
            except Exception as e:
                print(f"Error deleting job: {e}")
                return False

    def get_pending_jobs(self) -> List[Dict]:
        """Get all jobs with status 'queued' awaiting assignment."""
        with self._job_queue_lock:
            data = self._load_job_queue_data()
            jobs = data.get('jobs', [])
            pending = [j for j in jobs if j.get('status') == 'queued']
            # Sort by priority (highest first), then by submitted_at (oldest first)
            pending.sort(key=lambda x: (-x.get('priority', 50), x.get('submitted_at', '')))
            return pending

    def get_worker_jobs(self, worker_id: str, statuses: List[str] = None) -> List[Dict]:
        """Get jobs assigned to a specific worker."""
        with self._job_queue_lock:
            data = self._load_job_queue_data()
            jobs = data.get('jobs', [])
            worker_jobs = [j for j in jobs if j.get('assigned_worker') == worker_id]

            if statuses:
                worker_jobs = [j for j in worker_jobs if j.get('status') in statuses]

            worker_jobs.sort(key=lambda x: x.get('submitted_at', ''), reverse=True)
            return worker_jobs

    def cleanup_jobs(self, max_age_days: int = 30, keep_count: int = 500) -> int:
        """Clean up old completed/failed jobs."""
        with self._job_queue_lock:
            try:
                from datetime import timedelta

                data = self._load_job_queue_data()
                jobs = data.get('jobs', [])

                if len(jobs) <= keep_count:
                    return 0

                # Sort by submitted_at (newest first)
                jobs.sort(key=lambda x: x.get('submitted_at', ''), reverse=True)

                # Calculate cutoff date
                cutoff = datetime.now() - timedelta(days=max_age_days)
                cutoff_str = cutoff.isoformat()

                # Terminal statuses that can be cleaned up
                terminal_statuses = ['completed', 'failed', 'cancelled']

                jobs_to_keep = []
                removed_count = 0

                for i, job in enumerate(jobs):
                    submitted = job.get('submitted_at', '')
                    status = job.get('status', '')

                    # Always keep non-terminal jobs (queued, assigned, running)
                    if status not in terminal_statuses:
                        jobs_to_keep.append(job)
                    # Keep if within keep_count
                    elif i < keep_count:
                        jobs_to_keep.append(job)
                    # Keep if newer than cutoff
                    elif submitted >= cutoff_str:
                        jobs_to_keep.append(job)
                    else:
                        removed_count += 1

                if removed_count > 0:
                    data['jobs'] = jobs_to_keep
                    self._write_job_queue_data(data)

                return removed_count
            except Exception as e:
                print(f"Error cleaning up jobs: {e}")
                return 0

    # =========================================================================
    # Utility Operations
    # =========================================================================

    def health_check(self) -> bool:
        """Check if storage is healthy (config dir writable)."""
        try:
            test_file = os.path.join(self.config_dir, '.health_check')
            with open(test_file, 'w') as f:
                f.write('ok')
            os.remove(test_file)
            return True
        except Exception:
            return False

    def get_backend_type(self) -> str:
        """Return backend type identifier."""
        return 'flatfile'
