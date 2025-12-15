"""
Content Synchronization

Handles syncing Ansible content from the primary server to the worker.
Supports both full sync (archive) and incremental sync (individual files).
"""

import os
import hashlib
import tarfile
import shutil
import tempfile
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .api_client import PrimaryAPIClient


@dataclass
class SyncResult:
    """Result of a sync operation."""
    success: bool
    revision: Optional[str] = None
    files_synced: int = 0
    error: Optional[str] = None


class ContentSync:
    """Manages content synchronization with primary server."""

    # Directories to sync
    SYNC_DIRS = ['playbooks', 'inventory', 'library', 'callback_plugins']
    # Individual files to sync
    SYNC_FILES = ['ansible.cfg']

    def __init__(self, api_client: PrimaryAPIClient, content_dir: str):
        """
        Initialize content sync manager.

        Args:
            api_client: API client for primary server
            content_dir: Local directory for Ansible content
        """
        self.api = api_client
        self.content_dir = content_dir
        self._local_revision: Optional[str] = None
        self._local_manifest: Dict = {}

    @property
    def local_revision(self) -> Optional[str]:
        """Get the current local content revision."""
        return self._local_revision

    def _compute_file_checksum(self, filepath: str) -> str:
        """Compute SHA256 checksum of a file."""
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _build_local_manifest(self) -> Dict[str, Dict]:
        """Build manifest of local content files."""
        manifest = {}

        for dir_name in self.SYNC_DIRS:
            dir_path = os.path.join(self.content_dir, dir_name)
            if os.path.isdir(dir_path):
                for root, dirs, files in os.walk(dir_path):
                    # Skip hidden directories
                    dirs[:] = [d for d in dirs if not d.startswith('.')]

                    for filename in files:
                        # Skip hidden and compiled files
                        if filename.startswith('.') or filename.endswith('.pyc'):
                            continue

                        filepath = os.path.join(root, filename)
                        relpath = os.path.relpath(filepath, self.content_dir)

                        try:
                            stat = os.stat(filepath)
                            manifest[relpath] = {
                                'size': stat.st_size,
                                'sha256': self._compute_file_checksum(filepath)
                            }
                        except (IOError, OSError):
                            pass

        for filename in self.SYNC_FILES:
            filepath = os.path.join(self.content_dir, filename)
            if os.path.isfile(filepath):
                try:
                    stat = os.stat(filepath)
                    manifest[filename] = {
                        'size': stat.st_size,
                        'sha256': self._compute_file_checksum(filepath)
                    }
                except (IOError, OSError):
                    pass

        return manifest

    def check_sync_needed(self) -> Tuple[bool, Optional[str]]:
        """
        Check if sync is needed by comparing revisions.

        Returns:
            Tuple of (needs_sync, server_revision)
        """
        response = self.api.get_sync_revision()
        if not response.success:
            return False, None

        server_revision = response.data.get('revision')
        needs_sync = self._local_revision != server_revision

        return needs_sync, server_revision

    def get_changed_files(self) -> Tuple[List[str], List[str], List[str]]:
        """
        Compare local and server manifests to find changes.

        Returns:
            Tuple of (new_files, modified_files, deleted_files)
        """
        response = self.api.get_sync_manifest()
        if not response.success:
            return [], [], []

        server_manifest = response.data.get('files', {})
        local_manifest = self._build_local_manifest()

        new_files = []
        modified_files = []
        deleted_files = []

        # Find new and modified files
        for path, info in server_manifest.items():
            if path not in local_manifest:
                new_files.append(path)
            elif info['sha256'] != local_manifest[path]['sha256']:
                modified_files.append(path)

        # Find deleted files
        for path in local_manifest:
            if path not in server_manifest:
                deleted_files.append(path)

        return new_files, modified_files, deleted_files

    def full_sync(self) -> SyncResult:
        """
        Perform full sync by downloading and extracting archive.

        Returns:
            SyncResult with status
        """
        # Get server revision first
        rev_response = self.api.get_sync_revision()
        if not rev_response.success:
            return SyncResult(
                success=False,
                error=f"Failed to get revision: {rev_response.error}"
            )

        server_revision = rev_response.data.get('revision')

        # Download archive to temp file
        with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tmp:
            archive_path = tmp.name

        try:
            success, error = self.api.download_archive(archive_path)
            if not success:
                return SyncResult(success=False, error=f"Download failed: {error}")

            # Create backup of existing content
            backup_dir = None
            if os.path.exists(self.content_dir):
                backup_dir = tempfile.mkdtemp()
                for dir_name in self.SYNC_DIRS:
                    src = os.path.join(self.content_dir, dir_name)
                    if os.path.isdir(src):
                        shutil.copytree(src, os.path.join(backup_dir, dir_name))

            # Extract archive
            try:
                # Clear existing content directories
                for dir_name in self.SYNC_DIRS:
                    dir_path = os.path.join(self.content_dir, dir_name)
                    if os.path.isdir(dir_path):
                        shutil.rmtree(dir_path)
                    os.makedirs(dir_path, exist_ok=True)

                # Extract archive
                with tarfile.open(archive_path, 'r:gz') as tar:
                    tar.extractall(self.content_dir)

                # Count extracted files
                files_synced = 0
                for dir_name in self.SYNC_DIRS:
                    dir_path = os.path.join(self.content_dir, dir_name)
                    if os.path.isdir(dir_path):
                        for root, dirs, files in os.walk(dir_path):
                            files_synced += len(files)

                self._local_revision = server_revision
                self._local_manifest = self._build_local_manifest()

                # Remove backup on success
                if backup_dir:
                    shutil.rmtree(backup_dir, ignore_errors=True)

                return SyncResult(
                    success=True,
                    revision=server_revision,
                    files_synced=files_synced
                )

            except Exception as e:
                # Restore from backup on failure
                if backup_dir:
                    for dir_name in self.SYNC_DIRS:
                        src = os.path.join(backup_dir, dir_name)
                        dst = os.path.join(self.content_dir, dir_name)
                        if os.path.isdir(src):
                            if os.path.isdir(dst):
                                shutil.rmtree(dst)
                            shutil.copytree(src, dst)
                    shutil.rmtree(backup_dir, ignore_errors=True)

                return SyncResult(
                    success=False,
                    error=f"Extraction failed: {str(e)}"
                )

        finally:
            # Clean up temp archive
            if os.path.exists(archive_path):
                os.remove(archive_path)

    def incremental_sync(self) -> SyncResult:
        """
        Perform incremental sync by downloading only changed files.

        Returns:
            SyncResult with status
        """
        # Get changes
        new_files, modified_files, deleted_files = self.get_changed_files()

        if not new_files and not modified_files and not deleted_files:
            # Already in sync
            return SyncResult(success=True, files_synced=0)

        files_to_download = new_files + modified_files
        files_synced = 0
        errors = []

        # Download new and modified files
        for filepath in files_to_download:
            local_path = os.path.join(self.content_dir, filepath)

            # Ensure directory exists
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            success, error = self.api.download_file(filepath, local_path)
            if success:
                files_synced += 1
            else:
                errors.append(f"{filepath}: {error}")

        # Delete removed files
        for filepath in deleted_files:
            local_path = os.path.join(self.content_dir, filepath)
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except OSError as e:
                    errors.append(f"Delete {filepath}: {str(e)}")

        # Update local revision
        rev_response = self.api.get_sync_revision()
        if rev_response.success:
            self._local_revision = rev_response.data.get('revision')

        self._local_manifest = self._build_local_manifest()

        if errors:
            return SyncResult(
                success=False,
                revision=self._local_revision,
                files_synced=files_synced,
                error='; '.join(errors)
            )

        return SyncResult(
            success=True,
            revision=self._local_revision,
            files_synced=files_synced
        )

    def sync(self, force_full: bool = False) -> SyncResult:
        """
        Sync content from primary server.

        Uses incremental sync if possible, falls back to full sync
        for initial sync or when incremental fails.

        Args:
            force_full: Force full sync even if incremental is possible

        Returns:
            SyncResult with status
        """
        # Check if we need to sync
        needs_sync, server_revision = self.check_sync_needed()
        if not needs_sync and not force_full:
            return SyncResult(success=True, revision=self._local_revision)

        # Use full sync for initial sync or when forced
        if self._local_revision is None or force_full:
            return self.full_sync()

        # Try incremental sync
        result = self.incremental_sync()

        # Fall back to full sync on failure
        if not result.success:
            return self.full_sync()

        return result

    def ensure_directories(self):
        """Ensure all sync directories exist."""
        for dir_name in self.SYNC_DIRS:
            dir_path = os.path.join(self.content_dir, dir_name)
            os.makedirs(dir_path, exist_ok=True)
