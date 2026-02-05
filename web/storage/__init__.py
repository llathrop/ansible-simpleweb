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
# Note: MongoDBStorage is imported lazily to avoid requiring pymongo
# when only using flatfile storage


def get_storage_backend() -> StorageBackend:
    """
    Factory function to get the appropriate storage backend.

    When app_config.yaml exists (see config_manager), uses config for backend
    and MongoDB settings. Otherwise uses environment variables:
    - STORAGE_BACKEND: 'flatfile' (default) or 'mongodb'
    - MONGODB_HOST, MONGODB_PORT, MONGODB_DATABASE when backend is mongodb

    Returns:
        StorageBackend instance
    """
    try:
        from config_manager import config_file_exists, get_effective_storage_backend, get_effective_mongodb_settings
        if config_file_exists():
            backend_type = get_effective_storage_backend().lower()
            if backend_type == 'mongodb':
                from .mongodb import MongoDBStorage
                m = get_effective_mongodb_settings()
                return MongoDBStorage(host=m['host'], port=m['port'], database=m['database'])
            config_dir = os.environ.get('CONFIG_DIR', '/app/config')
            return FlatFileStorage(config_dir=config_dir)
    except ImportError:
        pass

    backend_type = os.environ.get('STORAGE_BACKEND', 'flatfile').lower()
    if backend_type == 'mongodb':
        from .mongodb import MongoDBStorage
        host = os.environ.get('MONGODB_HOST', 'mongodb')
        port = int(os.environ.get('MONGODB_PORT', 27017))
        database = os.environ.get('MONGODB_DATABASE', 'ansible_simpleweb')
        return MongoDBStorage(host=host, port=port, database=database)
    config_dir = os.environ.get('CONFIG_DIR', '/app/config')
    return FlatFileStorage(config_dir=config_dir)


def get_mongodb_storage_class():
    """Lazy loader for MongoDBStorage class."""
    from .mongodb import MongoDBStorage
    return MongoDBStorage


__all__ = ['get_storage_backend', 'StorageBackend', 'FlatFileStorage', 'get_mongodb_storage_class']
