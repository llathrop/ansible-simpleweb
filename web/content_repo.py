"""
Content Repository Management

Manages a git repository containing Ansible content that can be synced to workers:
- playbooks/
- inventory/
- library/
- callback_plugins/
- ansible.cfg

The content repository is separate from the main application repository.
Workers clone/pull this repo to sync their Ansible content.
"""

import os
import subprocess
import hashlib
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple


class ContentRepository:
    """
    Manages the git repository for syncable Ansible content.

    The repository tracks:
    - Ansible playbooks
    - Inventory files
    - Custom modules (library/)
    - Callback plugins
    - Ansible configuration
    """

    # Directories to track in the content repo
    TRACKED_DIRS = ['playbooks', 'inventory', 'library', 'callback_plugins']
    # Individual files to track
    TRACKED_FILES = ['ansible.cfg']

    def __init__(self, content_dir: str = '/app', repo_subdir: str = '.content-repo'):
        """
        Initialize the content repository manager.

        Args:
            content_dir: Base directory containing Ansible content
            repo_subdir: Subdirectory name for the git repo metadata
                         (content is tracked in place, not copied)
        """
        self.content_dir = content_dir
        self.repo_dir = content_dir  # Git repo at content root
        self.git_dir = os.path.join(content_dir, repo_subdir)
        self._initialized = False

    def _run_git(self, args: List[str], check: bool = True) -> Tuple[int, str, str]:
        """
        Run a git command in the content directory.

        Args:
            args: Git command arguments (without 'git')
            check: Whether to raise on non-zero exit

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        cmd = ['git', f'--git-dir={self.git_dir}', f'--work-tree={self.repo_dir}'] + args
        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=30
            )
            if check and result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode, cmd, result.stdout, result.stderr
                )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, '', 'Command timed out'
        except FileNotFoundError:
            return -1, '', 'Git not found'

    def is_initialized(self) -> bool:
        """Check if the git repository is initialized."""
        return os.path.isdir(self.git_dir) and os.path.exists(
            os.path.join(self.git_dir, 'HEAD')
        )

    def init_repo(self, force: bool = False) -> bool:
        """
        Initialize the git repository if not already initialized.

        Args:
            force: Re-initialize even if already exists

        Returns:
            True if initialization successful or already initialized
        """
        if self.is_initialized() and not force:
            self._initialized = True
            return True

        try:
            # Create git directory
            os.makedirs(self.git_dir, exist_ok=True)

            # Initialize bare-style repo with separate git dir
            returncode, stdout, stderr = self._run_git(['init'], check=False)
            if returncode != 0:
                print(f"Git init failed: {stderr}")
                return False

            # Configure repo
            self._run_git(['config', 'user.email', 'ansible-simpleweb@local'], check=False)
            self._run_git(['config', 'user.name', 'Ansible SimpleWeb'], check=False)

            # Create .gitignore for content repo
            gitignore_path = os.path.join(self.repo_dir, '.content-gitignore')
            gitignore_content = """# Content repo gitignore
# Ignore everything except tracked directories
/*
!playbooks/
!inventory/
!library/
!callback_plugins/
!ansible.cfg
!.content-gitignore

# Ignore compiled Python
*.pyc
__pycache__/

# Ignore temporary files
*.tmp
*.swp
*~
"""
            with open(gitignore_path, 'w') as f:
                f.write(gitignore_content)

            # Initial commit with existing content
            self._stage_all()
            self._commit('Initial content repository setup')

            self._initialized = True
            print(f"Content repository initialized at {self.git_dir}")
            return True

        except Exception as e:
            print(f"Error initializing content repository: {e}")
            return False

    def _stage_all(self) -> bool:
        """Stage all tracked content for commit."""
        try:
            # Add tracked directories
            for dir_name in self.TRACKED_DIRS:
                dir_path = os.path.join(self.repo_dir, dir_name)
                if os.path.isdir(dir_path):
                    self._run_git(['add', '-A', dir_name], check=False)

            # Add tracked files
            for file_name in self.TRACKED_FILES:
                file_path = os.path.join(self.repo_dir, file_name)
                if os.path.isfile(file_path):
                    self._run_git(['add', file_name], check=False)

            # Add gitignore
            gitignore = os.path.join(self.repo_dir, '.content-gitignore')
            if os.path.isfile(gitignore):
                self._run_git(['add', '.content-gitignore'], check=False)

            return True
        except Exception as e:
            print(f"Error staging content: {e}")
            return False

    def _commit(self, message: str) -> Optional[str]:
        """
        Create a commit with the staged changes.

        Args:
            message: Commit message

        Returns:
            Commit SHA if successful, None otherwise
        """
        try:
            # Check if there are changes to commit
            returncode, stdout, stderr = self._run_git(
                ['diff', '--cached', '--quiet'], check=False
            )
            if returncode == 0:
                # No changes staged
                return self.get_current_revision()

            # Commit
            returncode, stdout, stderr = self._run_git(
                ['commit', '-m', message], check=False
            )
            if returncode != 0 and 'nothing to commit' not in stderr:
                print(f"Commit failed: {stderr}")
                return None

            return self.get_current_revision()
        except Exception as e:
            print(f"Error committing: {e}")
            return None

    def get_current_revision(self) -> Optional[str]:
        """
        Get the current HEAD commit SHA.

        Returns:
            40-character SHA string or None if no commits
        """
        if not self.is_initialized():
            return None

        try:
            returncode, stdout, stderr = self._run_git(
                ['rev-parse', 'HEAD'], check=False
            )
            if returncode == 0:
                return stdout.strip()
            return None
        except Exception:
            return None

    def get_short_revision(self) -> Optional[str]:
        """Get abbreviated revision (7 chars)."""
        rev = self.get_current_revision()
        return rev[:7] if rev else None

    def commit_changes(self, message: str = None) -> Optional[str]:
        """
        Stage all changes and commit.

        Args:
            message: Commit message (auto-generated if not provided)

        Returns:
            New commit SHA if changes committed, current SHA if no changes
        """
        if not self.is_initialized():
            if not self.init_repo():
                return None

        if not message:
            message = f"Content update at {datetime.now().isoformat()}"

        self._stage_all()
        return self._commit(message)

    def has_changes(self) -> bool:
        """Check if there are uncommitted changes in tracked content."""
        if not self.is_initialized():
            return False

        try:
            # Stage changes first to detect them
            self._stage_all()

            # Check for staged changes
            returncode, stdout, stderr = self._run_git(
                ['diff', '--cached', '--quiet'], check=False
            )
            return returncode != 0
        except Exception:
            return False

    def get_file_manifest(self) -> Dict[str, Dict]:
        """
        Generate a manifest of all tracked files with checksums.

        Returns:
            Dict mapping relative paths to {size, sha256, mtime}
        """
        manifest = {}

        for dir_name in self.TRACKED_DIRS:
            dir_path = os.path.join(self.repo_dir, dir_name)
            if os.path.isdir(dir_path):
                for root, dirs, files in os.walk(dir_path):
                    # Skip hidden directories
                    dirs[:] = [d for d in dirs if not d.startswith('.')]

                    for filename in files:
                        # Skip hidden files and compiled Python
                        if filename.startswith('.') or filename.endswith('.pyc'):
                            continue

                        filepath = os.path.join(root, filename)
                        relpath = os.path.relpath(filepath, self.repo_dir)

                        try:
                            stat = os.stat(filepath)
                            with open(filepath, 'rb') as f:
                                content = f.read()
                                sha256 = hashlib.sha256(content).hexdigest()

                            manifest[relpath] = {
                                'size': stat.st_size,
                                'sha256': sha256,
                                'mtime': datetime.fromtimestamp(stat.st_mtime).isoformat()
                            }
                        except (IOError, OSError) as e:
                            print(f"Error reading {filepath}: {e}")

        # Add tracked individual files
        for filename in self.TRACKED_FILES:
            filepath = os.path.join(self.repo_dir, filename)
            if os.path.isfile(filepath):
                try:
                    stat = os.stat(filepath)
                    with open(filepath, 'rb') as f:
                        content = f.read()
                        sha256 = hashlib.sha256(content).hexdigest()

                    manifest[filename] = {
                        'size': stat.st_size,
                        'sha256': sha256,
                        'mtime': datetime.fromtimestamp(stat.st_mtime).isoformat()
                    }
                except (IOError, OSError) as e:
                    print(f"Error reading {filepath}: {e}")

        return manifest

    def get_commit_log(self, limit: int = 10) -> List[Dict]:
        """
        Get recent commit history.

        Args:
            limit: Maximum number of commits to return

        Returns:
            List of commit dicts with sha, message, date, author
        """
        if not self.is_initialized():
            return []

        try:
            returncode, stdout, stderr = self._run_git([
                'log', f'-{limit}',
                '--format=%H|%s|%ai|%an'
            ], check=False)

            if returncode != 0:
                return []

            commits = []
            for line in stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split('|', 3)
                if len(parts) >= 4:
                    commits.append({
                        'sha': parts[0],
                        'message': parts[1],
                        'date': parts[2],
                        'author': parts[3]
                    })

            return commits
        except Exception:
            return []

    def get_changed_files(self, since_revision: str = None) -> List[str]:
        """
        Get list of files changed since a revision.

        Args:
            since_revision: Commit SHA to compare from (defaults to HEAD~1)

        Returns:
            List of changed file paths
        """
        if not self.is_initialized():
            return []

        try:
            if since_revision:
                args = ['diff', '--name-only', since_revision, 'HEAD']
            else:
                args = ['diff', '--name-only', 'HEAD~1', 'HEAD']

            returncode, stdout, stderr = self._run_git(args, check=False)
            if returncode != 0:
                return []

            return [f for f in stdout.strip().split('\n') if f]
        except Exception:
            return []

    def get_status(self) -> Dict:
        """
        Get repository status summary.

        Returns:
            Dict with revision, has_changes, file_count, etc.
        """
        revision = self.get_current_revision()
        manifest = self.get_file_manifest()

        return {
            'initialized': self.is_initialized(),
            'revision': revision,
            'short_revision': revision[:7] if revision else None,
            'has_uncommitted_changes': self.has_changes(),
            'tracked_files': len(manifest),
            'tracked_dirs': self.TRACKED_DIRS,
            'content_dir': self.content_dir
        }

    def create_archive(self, output_path: str = None) -> Optional[str]:
        """
        Create a tar.gz archive of the current content.

        Args:
            output_path: Path for the archive (auto-generated if not provided)

        Returns:
            Path to created archive or None on failure
        """
        if not self.is_initialized():
            return None

        if not output_path:
            revision = self.get_short_revision() or 'unknown'
            output_path = f'/tmp/ansible-content-{revision}.tar.gz'

        try:
            returncode, stdout, stderr = self._run_git([
                'archive',
                '--format=tar.gz',
                f'--output={output_path}',
                'HEAD'
            ], check=False)

            if returncode == 0 and os.path.exists(output_path):
                return output_path
            return None
        except Exception as e:
            print(f"Error creating archive: {e}")
            return None


# Singleton instance for the application
_content_repo: Optional[ContentRepository] = None


def get_content_repo(content_dir: str = '/app') -> ContentRepository:
    """
    Get or create the content repository instance.

    Args:
        content_dir: Base directory for Ansible content

    Returns:
        ContentRepository instance
    """
    global _content_repo
    if _content_repo is None:
        _content_repo = ContentRepository(content_dir=content_dir)
    return _content_repo


def init_content_repo(content_dir: str = '/app') -> bool:
    """
    Initialize the content repository.

    Args:
        content_dir: Base directory for Ansible content

    Returns:
        True if initialization successful
    """
    repo = get_content_repo(content_dir)
    return repo.init_repo()
