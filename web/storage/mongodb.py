"""
MongoDB Storage Backend

Implements storage using MongoDB for persistence.
Provides the same interface as flat file storage for seamless switching.

Collections:
- schedules - Schedule definitions
- history - Execution history
- inventory - Inventory items
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Any

from pymongo import MongoClient, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from .base import StorageBackend


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
