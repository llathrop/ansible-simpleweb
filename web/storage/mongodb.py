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
