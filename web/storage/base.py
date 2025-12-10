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
