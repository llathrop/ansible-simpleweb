"""
Storage Backend Module

Provides abstraction layer for data persistence with support for:
- Flat file storage (JSON files)
- MongoDB storage

Usage:
    from storage import get_storage_backend
    storage = get_storage_backend()

    # Use storage for schedules, history, inventory
    schedules = storage.get_all_schedules()
"""

import os
from typing import Optional

from .base import StorageBackend
from .flatfile import FlatFileStorage
from .mongodb import MongoDBStorage


def get_storage_backend() -> StorageBackend:
    """
    Factory function to get the appropriate storage backend.

    Reads STORAGE_BACKEND environment variable:
    - 'flatfile' (default): JSON file storage
    - 'mongodb': MongoDB storage

    Returns:
        StorageBackend instance
    """
    backend_type = os.environ.get('STORAGE_BACKEND', 'flatfile').lower()

    if backend_type == 'mongodb':
        host = os.environ.get('MONGODB_HOST', 'mongodb')
        port = int(os.environ.get('MONGODB_PORT', 27017))
        database = os.environ.get('MONGODB_DATABASE', 'ansible_simpleweb')
        return MongoDBStorage(host=host, port=port, database=database)
    else:
        # Default to flat file
        config_dir = os.environ.get('CONFIG_DIR', '/app/config')
        return FlatFileStorage(config_dir=config_dir)


__all__ = ['get_storage_backend', 'StorageBackend', 'FlatFileStorage', 'MongoDBStorage']
