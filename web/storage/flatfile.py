"""
Flat File Storage Backend

Implements storage using JSON files for persistence.
This is the original storage method, now wrapped in the StorageBackend interface.

File structure:
- config/schedules.json - Schedule definitions
- config/schedule_history.json - Execution history
- config/inventory.json - Inventory items (new)
"""

import json
import os
import threading
import fnmatch
from datetime import datetime
from typing import Dict, List, Optional, Any

from .base import StorageBackend


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

        # Thread safety locks
        self._schedules_lock = threading.RLock()
        self._history_lock = threading.RLock()
        self._inventory_lock = threading.RLock()

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
