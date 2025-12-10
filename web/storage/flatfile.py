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

        # Thread safety locks
        self._schedules_lock = threading.RLock()
        self._history_lock = threading.RLock()
        self._inventory_lock = threading.RLock()
        self._host_facts_lock = threading.RLock()

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
