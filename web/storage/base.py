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

def compute_diff(old_data: Dict, new_data: Dict) -> Dict:
    """
    Compute the difference between two data dictionaries.

    Returns a diff that can be used to reconstruct old_data from new_data.

    Args:
        old_data: Previous data state
        new_data: New data state

    Returns:
        Diff dict with 'added', 'removed', 'changed' keys
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
        diff['added'][key] = new_data[key]

    # Keys removed from old data
    for key in old_keys - new_keys:
        diff['removed'][key] = old_data[key]

    # Keys in both - check for changes
    for key in old_keys & new_keys:
        old_val = old_data[key]
        new_val = new_data[key]

        if old_val != new_val:
            if isinstance(old_val, dict) and isinstance(new_val, dict):
                # Recursive diff for nested dicts
                nested_diff = compute_diff(old_val, new_val)
                if nested_diff['added'] or nested_diff['removed'] or nested_diff['changed']:
                    diff['changed'][key] = {
                        'old': old_val,
                        'new': new_val,
                        'diff': nested_diff
                    }
            elif isinstance(old_val, list) and isinstance(new_val, list):
                # For lists, store old and new values
                if old_val != new_val:
                    diff['changed'][key] = {
                        'old': old_val,
                        'new': new_val
                    }
            else:
                diff['changed'][key] = {
                    'old': old_val,
                    'new': new_val
                }

    return diff


def is_empty_diff(diff: Dict) -> bool:
    """Check if a diff represents no changes."""
    return not diff.get('added') and not diff.get('removed') and not diff.get('changed')
