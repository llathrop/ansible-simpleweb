"""
MongoDB Storage Backend

Implements storage using MongoDB for persistence.
Provides the same interface as flat file storage for seamless switching.

Collections:
- schedules - Schedule definitions
- history - Execution history
- inventory - Inventory items
- host_facts - Collected host facts (CMDB)
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Any

from pymongo import MongoClient, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from .base import StorageBackend, compute_diff, is_empty_diff


class MongoDBStorage(StorageBackend):
    """
    MongoDB storage implementation.

    Uses the same data structures as flat file storage for compatibility.
    Indexes are created automatically on first use.
    """

    def __init__(self, host: str = 'mongodb', port: int = 27017,
                 database: str = 'ansible_simpleweb'):
        """
        Initialize MongoDB storage.

        Args:
            host: MongoDB host
            port: MongoDB port
            database: Database name
        """
        self.host = host
        self.port = port
        self.database_name = database

        # Connect to MongoDB
        self.client = MongoClient(
            host=host,
            port=port,
            serverSelectionTimeoutMS=5000
        )
        self.db = self.client[database]

        # Collection references
        self.schedules_collection = self.db['schedules']
        self.history_collection = self.db['history']
        self.inventory_collection = self.db['inventory']
        self.host_facts_collection = self.db['host_facts']
        self.batch_jobs_collection = self.db['batch_jobs']
        self.workers_collection = self.db['workers']
        self.job_queue_collection = self.db['job_queue']

        # Ensure indexes
        self._ensure_indexes()

    def _ensure_indexes(self):
        """Create indexes for efficient queries."""
        try:
            # Schedules - index by id
            self.schedules_collection.create_index('id', unique=True)

            # History - indexes for common queries
            self.history_collection.create_index([('started', DESCENDING)])
            self.history_collection.create_index('schedule_id')
            self.history_collection.create_index('run_id')

            # Inventory - indexes for search
            self.inventory_collection.create_index('id', unique=True)
            self.inventory_collection.create_index('hostname')
            self.inventory_collection.create_index('group')

            # Host facts - indexes for CMDB queries
            self.host_facts_collection.create_index('host', unique=True)
            self.host_facts_collection.create_index('groups')
            self.host_facts_collection.create_index([('last_updated', DESCENDING)])

            # Batch jobs - indexes for queries
            self.batch_jobs_collection.create_index('id', unique=True)
            self.batch_jobs_collection.create_index('status')
            self.batch_jobs_collection.create_index([('created', DESCENDING)])

            # Workers - indexes for cluster support
            self.workers_collection.create_index('id', unique=True)
            self.workers_collection.create_index('status')
            self.workers_collection.create_index('name')
            self.workers_collection.create_index([('registered_at', DESCENDING)])

            # Job queue - indexes for cluster support
            self.job_queue_collection.create_index('id', unique=True)
            self.job_queue_collection.create_index('status')
            self.job_queue_collection.create_index('assigned_worker')
            self.job_queue_collection.create_index('playbook')
            self.job_queue_collection.create_index([('submitted_at', DESCENDING)])
            self.job_queue_collection.create_index([('priority', DESCENDING)])
        except Exception as e:
            print(f"Warning: Could not create indexes: {e}")

    # =========================================================================
    # Schedule Operations
    # =========================================================================

    def get_all_schedules(self) -> Dict[str, Dict]:
        """Get all schedules from MongoDB."""
        try:
            schedules = {}
            for doc in self.schedules_collection.find():
                schedule_id = doc.get('id')
                if schedule_id:
                    # Remove MongoDB _id field
                    doc.pop('_id', None)
                    schedules[schedule_id] = doc
            return schedules
        except Exception as e:
            print(f"Error loading schedules from MongoDB: {e}")
            return {}

    def get_schedule(self, schedule_id: str) -> Optional[Dict]:
        """Get a single schedule by ID."""
        try:
            doc = self.schedules_collection.find_one({'id': schedule_id})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting schedule from MongoDB: {e}")
            return None

    def save_schedule(self, schedule_id: str, schedule: Dict) -> bool:
        """Save or update a schedule."""
        try:
            # Ensure id is in the document
            schedule['id'] = schedule_id
            self.schedules_collection.replace_one(
                {'id': schedule_id},
                schedule,
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error saving schedule to MongoDB: {e}")
            return False

    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a schedule."""
        try:
            result = self.schedules_collection.delete_one({'id': schedule_id})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting schedule from MongoDB: {e}")
            return False

    def save_all_schedules(self, schedules: Dict[str, Dict]) -> bool:
        """Save all schedules (bulk operation)."""
        try:
            # Clear existing and insert all
            self.schedules_collection.delete_many({})
            if schedules:
                docs = []
                for schedule_id, schedule in schedules.items():
                    schedule['id'] = schedule_id
                    docs.append(schedule)
                self.schedules_collection.insert_many(docs)
            return True
        except Exception as e:
            print(f"Error saving all schedules to MongoDB: {e}")
            return False

    # =========================================================================
    # History Operations
    # =========================================================================

    def get_history(self, schedule_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Get execution history."""
        try:
            query = {}
            if schedule_id:
                query['schedule_id'] = schedule_id

            cursor = self.history_collection.find(query).sort(
                'started', DESCENDING
            ).limit(limit)

            history = []
            for doc in cursor:
                doc.pop('_id', None)
                history.append(doc)
            return history
        except Exception as e:
            print(f"Error loading history from MongoDB: {e}")
            return []

    def add_history_entry(self, entry: Dict) -> bool:
        """Add a new history entry."""
        try:
            self.history_collection.insert_one(entry.copy())
            return True
        except Exception as e:
            print(f"Error adding history entry to MongoDB: {e}")
            return False

    def cleanup_history(self, max_entries: int = 1000) -> int:
        """Remove old history entries beyond max_entries."""
        try:
            # Count total entries
            total = self.history_collection.count_documents({})
            if total <= max_entries:
                return 0

            # Find the cutoff point
            to_remove = total - max_entries
            cursor = self.history_collection.find().sort(
                'started', DESCENDING
            ).skip(max_entries).limit(to_remove)

            # Get IDs to delete
            ids_to_delete = [doc['_id'] for doc in cursor]
            if ids_to_delete:
                result = self.history_collection.delete_many(
                    {'_id': {'$in': ids_to_delete}}
                )
                return result.deleted_count
            return 0
        except Exception as e:
            print(f"Error cleaning up history in MongoDB: {e}")
            return 0

    # =========================================================================
    # Inventory Operations
    # =========================================================================

    def get_all_inventory(self) -> List[Dict]:
        """Get all inventory items."""
        try:
            inventory = []
            for doc in self.inventory_collection.find():
                doc.pop('_id', None)
                inventory.append(doc)
            return inventory
        except Exception as e:
            print(f"Error loading inventory from MongoDB: {e}")
            return []

    def get_inventory_item(self, item_id: str) -> Optional[Dict]:
        """Get a single inventory item by ID."""
        try:
            doc = self.inventory_collection.find_one({'id': item_id})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting inventory item from MongoDB: {e}")
            return None

    def save_inventory_item(self, item_id: str, item: Dict) -> bool:
        """Save or update an inventory item."""
        try:
            item['id'] = item_id
            self.inventory_collection.replace_one(
                {'id': item_id},
                item,
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error saving inventory item to MongoDB: {e}")
            return False

    def delete_inventory_item(self, item_id: str) -> bool:
        """Delete an inventory item."""
        try:
            result = self.inventory_collection.delete_one({'id': item_id})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting inventory item from MongoDB: {e}")
            return False

    def search_inventory(self, query: Dict) -> List[Dict]:
        """Search inventory items by criteria."""
        try:
            mongo_query = {}
            for key, pattern in query.items():
                if isinstance(pattern, str) and '*' in pattern:
                    # Convert wildcard to regex
                    regex_pattern = pattern.replace('*', '.*')
                    mongo_query[key] = {'$regex': f'^{regex_pattern}$', '$options': 'i'}
                else:
                    mongo_query[key] = pattern

            results = []
            for doc in self.inventory_collection.find(mongo_query):
                doc.pop('_id', None)
                results.append(doc)
            return results
        except Exception as e:
            print(f"Error searching inventory in MongoDB: {e}")
            return []

    # =========================================================================
    # Host Facts Operations (CMDB)
    # =========================================================================

    def get_host_facts(self, host: str) -> Optional[Dict]:
        """Get all collected facts for a specific host."""
        try:
            doc = self.host_facts_collection.find_one({'host': host})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting host facts from MongoDB: {e}")
            return None

    def get_host_collection(self, host: str, collection: str,
                            include_history: bool = False) -> Optional[Dict]:
        """Get a specific collection for a host."""
        try:
            doc = self.host_facts_collection.find_one({'host': host})
            if not doc:
                return None

            collection_data = doc.get('collections', {}).get(collection)
            if not collection_data:
                return None

            if include_history:
                return collection_data
            else:
                return {
                    'current': collection_data.get('current'),
                    'last_updated': collection_data.get('last_updated')
                }
        except Exception as e:
            print(f"Error getting host collection from MongoDB: {e}")
            return None

    def save_host_facts(self, host: str, collection: str, data: Dict,
                        groups: List[str] = None, source: str = None) -> Dict:
        """Save collected facts for a host with diff-based history."""
        try:
            now = datetime.now().isoformat()
            existing = self.host_facts_collection.find_one({'host': host})

            if not existing:
                # Create new host document
                new_doc = {
                    'host': host,
                    'groups': groups or [],
                    'collections': {
                        collection: {
                            'current': data,
                            'last_updated': now,
                            'source': source,
                            'history': []
                        }
                    },
                    'first_seen': now,
                    'last_updated': now
                }
                self.host_facts_collection.insert_one(new_doc)
                return {
                    'status': 'created',
                    'host': host,
                    'collection': collection
                }

            # Update existing host
            # Update groups if provided
            if groups:
                existing_groups = set(existing.get('groups', []))
                updated_groups = list(existing_groups | set(groups))
            else:
                updated_groups = existing.get('groups', [])

            collections = existing.get('collections', {})

            if collection not in collections:
                # New collection for existing host
                collections[collection] = {
                    'current': data,
                    'last_updated': now,
                    'source': source,
                    'history': []
                }
                changes = None
            else:
                # Update existing collection
                coll = collections[collection]
                old_data = coll.get('current', {})
                diff = compute_diff(old_data, data)

                if is_empty_diff(diff):
                    return {
                        'status': 'unchanged',
                        'host': host,
                        'collection': collection
                    }

                # Store diff in history
                history_entry = {
                    'timestamp': coll.get('last_updated', now),
                    'source': coll.get('source'),
                    'diff_from_next': diff
                }

                history = coll.get('history', [])
                history.insert(0, history_entry)
                history = history[:100]  # Limit history

                coll['current'] = data
                coll['last_updated'] = now
                coll['source'] = source
                coll['history'] = history
                changes = diff

            # Update document
            self.host_facts_collection.update_one(
                {'host': host},
                {'$set': {
                    'groups': updated_groups,
                    'collections': collections,
                    'last_updated': now
                }}
            )

            result = {
                'status': 'updated',
                'host': host,
                'collection': collection
            }
            if 'changes' in dir() and changes:
                result['changes'] = changes

            return result

        except Exception as e:
            print(f"Error saving host facts to MongoDB: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'host': host,
                'collection': collection
            }

    def get_all_hosts(self) -> List[Dict]:
        """Get summary of all hosts with collected facts."""
        try:
            hosts = []
            cursor = self.host_facts_collection.find().sort('last_updated', DESCENDING)

            for doc in cursor:
                hosts.append({
                    'host': doc.get('host'),
                    'groups': doc.get('groups', []),
                    'collections': list(doc.get('collections', {}).keys()),
                    'first_seen': doc.get('first_seen'),
                    'last_updated': doc.get('last_updated')
                })

            return hosts
        except Exception as e:
            print(f"Error getting all hosts from MongoDB: {e}")
            return []

    def get_hosts_by_group(self, group: str) -> List[Dict]:
        """Get all hosts belonging to a specific group."""
        try:
            hosts = []
            cursor = self.host_facts_collection.find({'groups': group})

            for doc in cursor:
                hosts.append({
                    'host': doc.get('host'),
                    'groups': doc.get('groups', []),
                    'collections': list(doc.get('collections', {}).keys()),
                    'first_seen': doc.get('first_seen'),
                    'last_updated': doc.get('last_updated')
                })

            return hosts
        except Exception as e:
            print(f"Error getting hosts by group from MongoDB: {e}")
            return []

    def get_host_history(self, host: str, collection: str,
                         limit: int = 50) -> List[Dict]:
        """Get historical changes for a host's collection."""
        try:
            doc = self.host_facts_collection.find_one({'host': host})
            if not doc:
                return []

            coll = doc.get('collections', {}).get(collection)
            if not coll:
                return []

            history = coll.get('history', [])
            return history[:limit]
        except Exception as e:
            print(f"Error getting host history from MongoDB: {e}")
            return []

    def delete_host_facts(self, host: str, collection: str = None) -> bool:
        """Delete facts for a host."""
        try:
            if collection:
                # Delete specific collection
                result = self.host_facts_collection.update_one(
                    {'host': host},
                    {'$unset': {f'collections.{collection}': ''}}
                )
                return result.modified_count > 0
            else:
                # Delete entire host
                result = self.host_facts_collection.delete_one({'host': host})
                return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting host facts from MongoDB: {e}")
            return False

    def import_host_facts(self, host_data: Dict) -> bool:
        """
        Import a complete host facts document (used for migration).

        Directly inserts/replaces the host document without diff processing,
        preserving all history and metadata from the source.

        Args:
            host_data: Complete host document

        Returns:
            True if imported successfully
        """
        try:
            host = host_data.get('host')
            if not host:
                return False

            # Remove MongoDB _id if present (from source export)
            doc = {k: v for k, v in host_data.items() if k != '_id'}

            # Use replace_one with upsert to insert or replace
            self.host_facts_collection.replace_one(
                {'host': host},
                doc,
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error importing host facts to MongoDB: {e}")
            return False

    # =========================================================================
    # Batch Job Operations
    # =========================================================================

    def get_all_batch_jobs(self) -> List[Dict]:
        """Get all batch jobs, sorted by created date (newest first)."""
        try:
            batch_jobs = []
            cursor = self.batch_jobs_collection.find().sort('created', DESCENDING)
            for doc in cursor:
                doc.pop('_id', None)
                batch_jobs.append(doc)
            return batch_jobs
        except Exception as e:
            print(f"Error loading batch jobs from MongoDB: {e}")
            return []

    def get_batch_job(self, batch_id: str) -> Optional[Dict]:
        """Get a single batch job by ID."""
        try:
            doc = self.batch_jobs_collection.find_one({'id': batch_id})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting batch job from MongoDB: {e}")
            return None

    def save_batch_job(self, batch_id: str, batch_job: Dict) -> bool:
        """Save or update a batch job."""
        try:
            # Ensure id is in the document
            batch_job['id'] = batch_id
            self.batch_jobs_collection.replace_one(
                {'id': batch_id},
                batch_job,
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error saving batch job to MongoDB: {e}")
            return False

    def delete_batch_job(self, batch_id: str) -> bool:
        """Delete a batch job."""
        try:
            result = self.batch_jobs_collection.delete_one({'id': batch_id})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting batch job from MongoDB: {e}")
            return False

    def get_batch_jobs_by_status(self, status: str) -> List[Dict]:
        """Get batch jobs filtered by status."""
        try:
            batch_jobs = []
            cursor = self.batch_jobs_collection.find({'status': status}).sort('created', DESCENDING)
            for doc in cursor:
                doc.pop('_id', None)
                batch_jobs.append(doc)
            return batch_jobs
        except Exception as e:
            print(f"Error getting batch jobs by status from MongoDB: {e}")
            return []

    def cleanup_batch_jobs(self, max_age_days: int = 30, keep_count: int = 100) -> int:
        """Clean up old batch jobs."""
        try:
            from datetime import timedelta

            # Count total jobs
            total = self.batch_jobs_collection.count_documents({})
            if total <= keep_count:
                return 0

            # Calculate cutoff date
            cutoff = datetime.now() - timedelta(days=max_age_days)
            cutoff_str = cutoff.isoformat()

            # Get IDs of jobs to potentially delete (excluding running jobs)
            # First, get the newest keep_count job IDs to preserve
            cursor = self.batch_jobs_collection.find(
                {},
                {'id': 1}
            ).sort('created', DESCENDING).limit(keep_count)
            keep_ids = {doc['id'] for doc in cursor}

            # Delete jobs that are:
            # 1. Not in the keep_ids set
            # 2. Older than cutoff
            # 3. Not running
            result = self.batch_jobs_collection.delete_many({
                'id': {'$nin': list(keep_ids)},
                'created': {'$lt': cutoff_str},
                'status': {'$ne': 'running'}
            })

            return result.deleted_count
        except Exception as e:
            print(f"Error cleaning up batch jobs in MongoDB: {e}")
            return 0

    # =========================================================================
    # Worker Operations (Cluster Support)
    # =========================================================================

    def get_all_workers(self) -> List[Dict]:
        """Get all registered workers, sorted by registered_at (newest first)."""
        try:
            workers = []
            cursor = self.workers_collection.find().sort('registered_at', DESCENDING)
            for doc in cursor:
                doc.pop('_id', None)
                workers.append(doc)
            return workers
        except Exception as e:
            print(f"Error loading workers from MongoDB: {e}")
            return []

    def get_worker(self, worker_id: str) -> Optional[Dict]:
        """Get a single worker by ID."""
        try:
            doc = self.workers_collection.find_one({'id': worker_id})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting worker from MongoDB: {e}")
            return None

    def save_worker(self, worker: Dict) -> bool:
        """Save or update a worker."""
        try:
            worker_id = worker.get('id')
            if not worker_id:
                print("Error: Worker must have an 'id' field")
                return False

            self.workers_collection.replace_one(
                {'id': worker_id},
                worker,
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error saving worker to MongoDB: {e}")
            return False

    def delete_worker(self, worker_id: str) -> bool:
        """Delete a worker."""
        try:
            result = self.workers_collection.delete_one({'id': worker_id})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting worker from MongoDB: {e}")
            return False

    def get_workers_by_status(self, statuses: List[str]) -> List[Dict]:
        """Get workers filtered by status."""
        try:
            workers = []
            cursor = self.workers_collection.find(
                {'status': {'$in': statuses}}
            ).sort('registered_at', DESCENDING)
            for doc in cursor:
                doc.pop('_id', None)
                workers.append(doc)
            return workers
        except Exception as e:
            print(f"Error getting workers by status from MongoDB: {e}")
            return []

    def update_worker_checkin(self, worker_id: str, checkin_data: Dict) -> bool:
        """Update worker with checkin data."""
        try:
            update_fields = {
                'last_checkin': datetime.now().isoformat()
            }

            # Update stats if provided
            if 'stats' in checkin_data:
                for key, value in checkin_data['stats'].items():
                    update_fields[f'stats.{key}'] = value

            # Update sync revision if provided
            if 'sync_revision' in checkin_data:
                update_fields['sync_revision'] = checkin_data['sync_revision']

            # Update status if provided
            if 'status' in checkin_data:
                update_fields['status'] = checkin_data['status']

            result = self.workers_collection.update_one(
                {'id': worker_id},
                {'$set': update_fields}
            )
            return result.matched_count > 0
        except Exception as e:
            print(f"Error updating worker checkin in MongoDB: {e}")
            return False

    # =========================================================================
    # Job Queue Operations (Cluster Support)
    # =========================================================================

    def get_all_jobs(self, filters: Dict = None) -> List[Dict]:
        """Get all jobs from the queue, optionally filtered."""
        try:
            query = {}
            if filters:
                for key, value in filters.items():
                    # Convert list filters to MongoDB $in queries
                    if isinstance(value, list):
                        query[key] = {'$in': value}
                    else:
                        query[key] = value
            jobs = []
            cursor = self.job_queue_collection.find(query).sort('submitted_at', DESCENDING)
            for doc in cursor:
                doc.pop('_id', None)
                jobs.append(doc)
            return jobs
        except Exception as e:
            print(f"Error loading jobs from MongoDB: {e}")
            return []

    def get_job(self, job_id: str) -> Optional[Dict]:
        """Get a single job by ID."""
        try:
            doc = self.job_queue_collection.find_one({'id': job_id})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting job from MongoDB: {e}")
            return None

    def save_job(self, job: Dict) -> bool:
        """Save or update a job."""
        try:
            job_id = job.get('id')
            if not job_id:
                print("Error: Job must have an 'id' field")
                return False

            self.job_queue_collection.replace_one(
                {'id': job_id},
                job,
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error saving job to MongoDB: {e}")
            return False

    def update_job(self, job_id: str, updates: Dict) -> bool:
        """Partially update a job."""
        try:
            result = self.job_queue_collection.update_one(
                {'id': job_id},
                {'$set': updates}
            )
            return result.matched_count > 0
        except Exception as e:
            print(f"Error updating job in MongoDB: {e}")
            return False

    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        try:
            result = self.job_queue_collection.delete_one({'id': job_id})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting job from MongoDB: {e}")
            return False

    def get_pending_jobs(self) -> List[Dict]:
        """Get all jobs with status 'queued' awaiting assignment."""
        try:
            jobs = []
            # Sort by priority (highest first), then by submitted_at (oldest first)
            cursor = self.job_queue_collection.find(
                {'status': 'queued'}
            ).sort([('priority', DESCENDING), ('submitted_at', 1)])
            for doc in cursor:
                doc.pop('_id', None)
                jobs.append(doc)
            return jobs
        except Exception as e:
            print(f"Error getting pending jobs from MongoDB: {e}")
            return []

    def get_worker_jobs(self, worker_id: str, statuses: List[str] = None) -> List[Dict]:
        """Get jobs assigned to a specific worker."""
        try:
            query = {'assigned_worker': worker_id}
            if statuses:
                query['status'] = {'$in': statuses}

            jobs = []
            cursor = self.job_queue_collection.find(query).sort('submitted_at', DESCENDING)
            for doc in cursor:
                doc.pop('_id', None)
                jobs.append(doc)
            return jobs
        except Exception as e:
            print(f"Error getting worker jobs from MongoDB: {e}")
            return []

    def cleanup_jobs(self, max_age_days: int = 30, keep_count: int = 500) -> int:
        """Clean up old completed/failed jobs."""
        try:
            from datetime import timedelta

            # Count total jobs
            total = self.job_queue_collection.count_documents({})
            if total <= keep_count:
                return 0

            # Calculate cutoff date
            cutoff = datetime.now() - timedelta(days=max_age_days)
            cutoff_str = cutoff.isoformat()

            # Terminal statuses that can be cleaned up
            terminal_statuses = ['completed', 'failed', 'cancelled']

            # Get IDs of newest jobs to keep
            cursor = self.job_queue_collection.find(
                {},
                {'id': 1}
            ).sort('submitted_at', DESCENDING).limit(keep_count)
            keep_ids = {doc['id'] for doc in cursor}

            # Delete jobs that are:
            # 1. Not in the keep_ids set
            # 2. Older than cutoff
            # 3. In terminal status
            result = self.job_queue_collection.delete_many({
                'id': {'$nin': list(keep_ids)},
                'submitted_at': {'$lt': cutoff_str},
                'status': {'$in': terminal_statuses}
            })

            return result.deleted_count
        except Exception as e:
            print(f"Error cleaning up jobs in MongoDB: {e}")
            return 0

    # =========================================================================
    # User Operations (Authentication)
    # =========================================================================

    def _ensure_auth_indexes(self):
        """Create indexes for authentication collections."""
        try:
            # Users collection
            self.db['users'].create_index('username', unique=True)
            self.db['users'].create_index('id', unique=True)

            # Groups collection
            self.db['groups'].create_index('name', unique=True)
            self.db['groups'].create_index('id', unique=True)

            # Roles collection
            self.db['roles'].create_index('name', unique=True)
            self.db['roles'].create_index('id', unique=True)

            # API tokens collection
            self.db['api_tokens'].create_index('id', unique=True)
            self.db['api_tokens'].create_index('token_hash', unique=True)
            self.db['api_tokens'].create_index('user_id')

            # Audit log collection
            self.db['audit_log'].create_index([('timestamp', DESCENDING)])
            self.db['audit_log'].create_index('user')
            self.db['audit_log'].create_index('action')
            self.db['audit_log'].create_index('resource')
        except Exception as e:
            print(f"Error creating auth indexes: {e}")

    def get_user(self, username: str) -> Optional[Dict]:
        """Get a user by username."""
        try:
            doc = self.db['users'].find_one({'username': username})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting user from MongoDB: {e}")
            return None

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get a user by ID."""
        try:
            doc = self.db['users'].find_one({'id': user_id})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting user by ID from MongoDB: {e}")
            return None

    def get_all_users(self) -> List[Dict]:
        """Get all users (without password_hash)."""
        try:
            cursor = self.db['users'].find(
                {},
                {'_id': 0, 'password_hash': 0}  # Exclude password_hash
            )
            return list(cursor)
        except Exception as e:
            print(f"Error getting all users from MongoDB: {e}")
            return []

    def save_user(self, username: str, user: Dict) -> bool:
        """Save or update a user."""
        try:
            self._ensure_auth_indexes()
            self.db['users'].update_one(
                {'username': username},
                {'$set': user},
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error saving user to MongoDB: {e}")
            return False

    def delete_user(self, username: str) -> bool:
        """Delete a user."""
        try:
            result = self.db['users'].delete_one({'username': username})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting user from MongoDB: {e}")
            return False

    def check_user_credentials(self, username: str, password_hash: str) -> bool:
        """Check if username and password hash match."""
        user = self.get_user(username)
        if user and user.get('password_hash') == password_hash:
            return True
        return False

    # =========================================================================
    # Group Operations
    # =========================================================================

    def get_group(self, group_name: str) -> Optional[Dict]:
        """Get a group by name."""
        try:
            doc = self.db['groups'].find_one({'name': group_name})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting group from MongoDB: {e}")
            return None

    def get_all_groups(self) -> List[Dict]:
        """Get all groups."""
        try:
            cursor = self.db['groups'].find({}, {'_id': 0})
            return list(cursor)
        except Exception as e:
            print(f"Error getting all groups from MongoDB: {e}")
            return []

    def save_group(self, group_name: str, group: Dict) -> bool:
        """Save or update a group."""
        try:
            self._ensure_auth_indexes()
            self.db['groups'].update_one(
                {'name': group_name},
                {'$set': group},
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error saving group to MongoDB: {e}")
            return False

    def delete_group(self, group_name: str) -> bool:
        """Delete a group."""
        try:
            result = self.db['groups'].delete_one({'name': group_name})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting group from MongoDB: {e}")
            return False

    # =========================================================================
    # Role Operations (RBAC)
    # =========================================================================

    def get_role(self, role_name: str) -> Optional[Dict]:
        """Get a role by name."""
        try:
            doc = self.db['roles'].find_one({'name': role_name})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting role from MongoDB: {e}")
            return None

    def get_all_roles(self) -> List[Dict]:
        """Get all roles."""
        try:
            cursor = self.db['roles'].find({}, {'_id': 0})
            return list(cursor)
        except Exception as e:
            print(f"Error getting all roles from MongoDB: {e}")
            return []

    def save_role(self, role_name: str, role: Dict) -> bool:
        """Save or update a role."""
        try:
            self._ensure_auth_indexes()
            self.db['roles'].update_one(
                {'name': role_name},
                {'$set': role},
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error saving role to MongoDB: {e}")
            return False

    def delete_role(self, role_name: str) -> bool:
        """Delete a role."""
        try:
            result = self.db['roles'].delete_one({'name': role_name})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting role from MongoDB: {e}")
            return False

    # =========================================================================
    # API Token Operations
    # =========================================================================

    def get_api_token(self, token_id: str) -> Optional[Dict]:
        """Get an API token by ID."""
        try:
            doc = self.db['api_tokens'].find_one({'id': token_id})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting API token from MongoDB: {e}")
            return None

    def get_api_token_by_hash(self, token_hash: str) -> Optional[Dict]:
        """Get an API token by its hash."""
        try:
            doc = self.db['api_tokens'].find_one({'token_hash': token_hash})
            if doc:
                doc.pop('_id', None)
                return doc
            return None
        except Exception as e:
            print(f"Error getting API token by hash from MongoDB: {e}")
            return None

    def get_user_api_tokens(self, user_id: str) -> List[Dict]:
        """Get all API tokens for a user (without token_hash)."""
        try:
            cursor = self.db['api_tokens'].find(
                {'user_id': user_id},
                {'_id': 0, 'token_hash': 0}  # Exclude token_hash
            )
            return list(cursor)
        except Exception as e:
            print(f"Error getting user API tokens from MongoDB: {e}")
            return []

    def save_api_token(self, token_id: str, token: Dict) -> bool:
        """Save or update an API token."""
        try:
            self._ensure_auth_indexes()
            self.db['api_tokens'].update_one(
                {'id': token_id},
                {'$set': token},
                upsert=True
            )
            return True
        except Exception as e:
            print(f"Error saving API token to MongoDB: {e}")
            return False

    def update_api_token(self, token_id: str, token: Dict) -> bool:
        """Update an existing API token."""
        return self.save_api_token(token_id, token)

    def delete_api_token(self, token_id: str) -> bool:
        """Delete an API token."""
        try:
            result = self.db['api_tokens'].delete_one({'id': token_id})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting API token from MongoDB: {e}")
            return False

    # =========================================================================
    # Audit Log Operations
    # =========================================================================

    def add_audit_entry(self, entry: Dict) -> bool:
        """Add an audit log entry."""
        try:
            self._ensure_auth_indexes()
            # Add timestamp if not present
            if 'timestamp' not in entry:
                entry['timestamp'] = datetime.utcnow().isoformat()
            self.db['audit_log'].insert_one(entry)
            return True
        except Exception as e:
            print(f"Error adding audit entry to MongoDB: {e}")
            return False

    def get_audit_log(self, filters: Dict = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get audit log entries with optional filters."""
        try:
            query = {}
            if filters:
                if filters.get('user'):
                    query['user'] = filters['user']
                if filters.get('action'):
                    query['action'] = filters['action']
                if filters.get('resource'):
                    query['resource'] = filters['resource']
                if filters.get('success') is not None:
                    query['success'] = filters['success']
                if filters.get('start_time') or filters.get('end_time'):
                    query['timestamp'] = {}
                    if filters.get('start_time'):
                        query['timestamp']['$gte'] = filters['start_time']
                    if filters.get('end_time'):
                        query['timestamp']['$lte'] = filters['end_time']

            cursor = self.db['audit_log'].find(
                query,
                {'_id': 0}
            ).sort('timestamp', DESCENDING).skip(offset).limit(limit)

            return list(cursor)
        except Exception as e:
            print(f"Error getting audit log from MongoDB: {e}")
            return []

    def cleanup_audit_log(self, max_age_days: int = 90, keep_count: int = 10000) -> int:
        """Clean up old audit log entries."""
        try:
            from datetime import timedelta

            # Count total entries
            total = self.db['audit_log'].count_documents({})
            if total <= keep_count:
                return 0

            # Calculate cutoff date
            cutoff = datetime.utcnow() - timedelta(days=max_age_days)
            cutoff_str = cutoff.isoformat()

            # Get timestamps of newest entries to keep
            cursor = self.db['audit_log'].find(
                {},
                {'timestamp': 1}
            ).sort('timestamp', DESCENDING).limit(keep_count)
            keep_timestamps = {doc.get('timestamp') for doc in cursor}

            # Find the oldest timestamp to keep
            min_keep_timestamp = min(keep_timestamps) if keep_timestamps else cutoff_str

            # Delete entries older than both cutoff and min_keep_timestamp
            delete_before = max(cutoff_str, min_keep_timestamp)
            result = self.db['audit_log'].delete_many({
                'timestamp': {'$lt': delete_before}
            })

            return result.deleted_count
        except Exception as e:
            print(f"Error cleaning up audit log in MongoDB: {e}")
            return 0

    # =========================================================================
    # Utility Operations
    # =========================================================================

    def health_check(self) -> bool:
        """Check if MongoDB is healthy and accessible."""
        try:
            # The ping command is cheap and does not require auth
            self.client.admin.command('ping')
            return True
        except (ConnectionFailure, ServerSelectionTimeoutError):
            return False

    def get_backend_type(self) -> str:
        """Return backend type identifier."""
        return 'mongodb'
