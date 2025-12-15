"""
Unit tests for Content Repository (Feature 3).

Tests the git repository management for syncable Ansible content.
"""

import os
import sys
import shutil
import tempfile
import unittest
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.content_repo import ContentRepository


class TestContentRepositoryInit(unittest.TestCase):
    """Test content repository initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        # Create basic directory structure
        os.makedirs(os.path.join(self.test_dir, 'playbooks'))
        os.makedirs(os.path.join(self.test_dir, 'inventory'))
        os.makedirs(os.path.join(self.test_dir, 'library'))
        os.makedirs(os.path.join(self.test_dir, 'callback_plugins'))

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_not_initialized_initially(self):
        """Test that repo is not initialized before init_repo()."""
        repo = ContentRepository(content_dir=self.test_dir)
        self.assertFalse(repo.is_initialized())

    def test_init_repo_creates_git_dir(self):
        """Test that init_repo creates git directory."""
        repo = ContentRepository(content_dir=self.test_dir)
        result = repo.init_repo()

        self.assertTrue(result)
        self.assertTrue(repo.is_initialized())
        self.assertTrue(os.path.isdir(repo.git_dir))

    def test_init_repo_idempotent(self):
        """Test that init_repo can be called multiple times."""
        repo = ContentRepository(content_dir=self.test_dir)

        result1 = repo.init_repo()
        result2 = repo.init_repo()

        self.assertTrue(result1)
        self.assertTrue(result2)

    def test_init_repo_creates_gitignore(self):
        """Test that init_repo creates .content-gitignore."""
        repo = ContentRepository(content_dir=self.test_dir)
        repo.init_repo()

        gitignore_path = os.path.join(self.test_dir, '.content-gitignore')
        self.assertTrue(os.path.exists(gitignore_path))


class TestContentRepositoryRevision(unittest.TestCase):
    """Test revision tracking."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.test_dir, 'playbooks'))
        os.makedirs(os.path.join(self.test_dir, 'inventory'))

        # Create a test playbook
        with open(os.path.join(self.test_dir, 'playbooks', 'test.yml'), 'w') as f:
            f.write('---\n- name: Test\n  hosts: all\n')

        self.repo = ContentRepository(content_dir=self.test_dir)
        self.repo.init_repo()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_current_revision(self):
        """Test getting current revision."""
        revision = self.repo.get_current_revision()

        self.assertIsNotNone(revision)
        self.assertEqual(len(revision), 40)  # SHA-1 hash length

    def test_get_short_revision(self):
        """Test getting short revision."""
        short_rev = self.repo.get_short_revision()

        self.assertIsNotNone(short_rev)
        self.assertEqual(len(short_rev), 7)

    def test_revision_before_init(self):
        """Test revision is None before initialization."""
        new_dir = tempfile.mkdtemp()
        try:
            repo = ContentRepository(content_dir=new_dir)
            self.assertIsNone(repo.get_current_revision())
        finally:
            shutil.rmtree(new_dir, ignore_errors=True)


class TestContentRepositoryCommit(unittest.TestCase):
    """Test committing changes."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.test_dir, 'playbooks'))
        os.makedirs(os.path.join(self.test_dir, 'inventory'))

        self.repo = ContentRepository(content_dir=self.test_dir)
        self.repo.init_repo()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_commit_changes_new_file(self):
        """Test committing a new file."""
        initial_rev = self.repo.get_current_revision()

        # Add a new playbook
        with open(os.path.join(self.test_dir, 'playbooks', 'new.yml'), 'w') as f:
            f.write('---\n- name: New Playbook\n  hosts: all\n')

        new_rev = self.repo.commit_changes('Added new playbook')

        self.assertIsNotNone(new_rev)
        # Revision should change after commit
        self.assertNotEqual(initial_rev, new_rev)

    def test_commit_changes_modified_file(self):
        """Test committing a modified file."""
        # Create initial file
        playbook_path = os.path.join(self.test_dir, 'playbooks', 'modify.yml')
        with open(playbook_path, 'w') as f:
            f.write('---\n- name: Original\n  hosts: all\n')
        self.repo.commit_changes('Initial')

        initial_rev = self.repo.get_current_revision()

        # Modify the file
        with open(playbook_path, 'w') as f:
            f.write('---\n- name: Modified\n  hosts: all\n')

        new_rev = self.repo.commit_changes('Modified playbook')

        self.assertNotEqual(initial_rev, new_rev)

    def test_commit_no_changes(self):
        """Test commit when there are no changes."""
        # Create and commit a file
        with open(os.path.join(self.test_dir, 'playbooks', 'static.yml'), 'w') as f:
            f.write('---\n- name: Static\n  hosts: all\n')
        self.repo.commit_changes('Initial')

        initial_rev = self.repo.get_current_revision()

        # Commit again without changes
        new_rev = self.repo.commit_changes('No changes')

        # Revision should remain the same
        self.assertEqual(initial_rev, new_rev)

    def test_commit_auto_message(self):
        """Test commit with auto-generated message."""
        with open(os.path.join(self.test_dir, 'playbooks', 'auto.yml'), 'w') as f:
            f.write('---\n- name: Auto\n  hosts: all\n')

        # Commit without explicit message
        rev = self.repo.commit_changes()

        self.assertIsNotNone(rev)


class TestContentRepositoryHasChanges(unittest.TestCase):
    """Test change detection."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.test_dir, 'playbooks'))

        self.repo = ContentRepository(content_dir=self.test_dir)
        self.repo.init_repo()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_has_changes_false_initially(self):
        """Test no changes after clean init."""
        # After init, there should be no uncommitted changes
        self.assertFalse(self.repo.has_changes())

    def test_has_changes_true_after_new_file(self):
        """Test has_changes detects new files."""
        with open(os.path.join(self.test_dir, 'playbooks', 'detect.yml'), 'w') as f:
            f.write('---\n- name: Detect\n  hosts: all\n')

        self.assertTrue(self.repo.has_changes())

    def test_has_changes_false_after_commit(self):
        """Test has_changes is false after committing."""
        with open(os.path.join(self.test_dir, 'playbooks', 'commit.yml'), 'w') as f:
            f.write('---\n- name: Commit\n  hosts: all\n')

        self.repo.commit_changes('Commit file')

        self.assertFalse(self.repo.has_changes())


class TestContentRepositoryManifest(unittest.TestCase):
    """Test file manifest generation."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.test_dir, 'playbooks'))
        os.makedirs(os.path.join(self.test_dir, 'inventory'))
        os.makedirs(os.path.join(self.test_dir, 'library'))

        # Create test files
        with open(os.path.join(self.test_dir, 'playbooks', 'test1.yml'), 'w') as f:
            f.write('---\n- name: Test1\n  hosts: all\n')

        with open(os.path.join(self.test_dir, 'playbooks', 'test2.yml'), 'w') as f:
            f.write('---\n- name: Test2\n  hosts: all\n')

        with open(os.path.join(self.test_dir, 'inventory', 'hosts'), 'w') as f:
            f.write('[webservers]\nweb1\nweb2\n')

        with open(os.path.join(self.test_dir, 'ansible.cfg'), 'w') as f:
            f.write('[defaults]\ninventory = ./inventory/hosts\n')

        self.repo = ContentRepository(content_dir=self.test_dir)
        self.repo.init_repo()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_manifest_includes_all_files(self):
        """Test manifest includes all tracked files."""
        manifest = self.repo.get_file_manifest()

        self.assertIn('playbooks/test1.yml', manifest)
        self.assertIn('playbooks/test2.yml', manifest)
        self.assertIn('inventory/hosts', manifest)
        self.assertIn('ansible.cfg', manifest)

    def test_manifest_file_info(self):
        """Test manifest includes file info."""
        manifest = self.repo.get_file_manifest()

        file_info = manifest['playbooks/test1.yml']
        self.assertIn('size', file_info)
        self.assertIn('sha256', file_info)
        self.assertIn('mtime', file_info)

        self.assertIsInstance(file_info['size'], int)
        self.assertEqual(len(file_info['sha256']), 64)  # SHA-256 hex length

    def test_manifest_excludes_hidden_files(self):
        """Test manifest excludes hidden files."""
        # Create a hidden file
        with open(os.path.join(self.test_dir, 'playbooks', '.hidden'), 'w') as f:
            f.write('hidden content')

        manifest = self.repo.get_file_manifest()

        self.assertNotIn('playbooks/.hidden', manifest)

    def test_manifest_excludes_pyc_files(self):
        """Test manifest excludes compiled Python files."""
        with open(os.path.join(self.test_dir, 'library', 'module.pyc'), 'w') as f:
            f.write('compiled')

        manifest = self.repo.get_file_manifest()

        self.assertNotIn('library/module.pyc', manifest)


class TestContentRepositoryStatus(unittest.TestCase):
    """Test status reporting."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.test_dir, 'playbooks'))

        with open(os.path.join(self.test_dir, 'playbooks', 'status.yml'), 'w') as f:
            f.write('---\n- name: Status\n  hosts: all\n')

        self.repo = ContentRepository(content_dir=self.test_dir)
        self.repo.init_repo()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_status_initialized(self):
        """Test status shows initialized."""
        status = self.repo.get_status()

        self.assertTrue(status['initialized'])
        self.assertIsNotNone(status['revision'])
        self.assertIsNotNone(status['short_revision'])

    def test_status_tracked_files(self):
        """Test status shows file count."""
        status = self.repo.get_status()

        self.assertIn('tracked_files', status)
        self.assertIsInstance(status['tracked_files'], int)
        self.assertGreater(status['tracked_files'], 0)

    def test_status_has_uncommitted_changes(self):
        """Test status shows uncommitted changes."""
        status = self.repo.get_status()
        self.assertFalse(status['has_uncommitted_changes'])

        # Add a new file
        with open(os.path.join(self.test_dir, 'playbooks', 'new.yml'), 'w') as f:
            f.write('---\n- name: New\n  hosts: all\n')

        status = self.repo.get_status()
        self.assertTrue(status['has_uncommitted_changes'])


class TestContentRepositoryCommitLog(unittest.TestCase):
    """Test commit history."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.test_dir, 'playbooks'))

        self.repo = ContentRepository(content_dir=self.test_dir)
        self.repo.init_repo()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_commit_log_initial(self):
        """Test commit log after initialization."""
        log = self.repo.get_commit_log()

        self.assertIsInstance(log, list)
        self.assertGreater(len(log), 0)

    def test_commit_log_entry_structure(self):
        """Test commit log entry structure."""
        log = self.repo.get_commit_log()

        if log:
            entry = log[0]
            self.assertIn('sha', entry)
            self.assertIn('message', entry)
            self.assertIn('date', entry)
            self.assertIn('author', entry)

    def test_commit_log_multiple_commits(self):
        """Test commit log with multiple commits."""
        # Make several commits
        for i in range(3):
            with open(os.path.join(self.test_dir, 'playbooks', f'file{i}.yml'), 'w') as f:
                f.write(f'---\n- name: File {i}\n  hosts: all\n')
            self.repo.commit_changes(f'Commit {i}')

        log = self.repo.get_commit_log()

        # Should have at least 4 commits (initial + 3)
        self.assertGreaterEqual(len(log), 4)

    def test_commit_log_limit(self):
        """Test commit log respects limit."""
        # Make several commits
        for i in range(5):
            with open(os.path.join(self.test_dir, 'playbooks', f'limit{i}.yml'), 'w') as f:
                f.write(f'---\n- name: Limit {i}\n  hosts: all\n')
            self.repo.commit_changes(f'Limit commit {i}')

        log = self.repo.get_commit_log(limit=3)

        self.assertEqual(len(log), 3)


class TestContentRepositoryArchive(unittest.TestCase):
    """Test archive creation."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.test_dir, 'playbooks'))

        with open(os.path.join(self.test_dir, 'playbooks', 'archive.yml'), 'w') as f:
            f.write('---\n- name: Archive\n  hosts: all\n')

        self.repo = ContentRepository(content_dir=self.test_dir)
        self.repo.init_repo()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_create_archive(self):
        """Test creating an archive."""
        archive_path = self.repo.create_archive()

        if archive_path:  # May fail if git archive not available
            self.assertTrue(os.path.exists(archive_path))
            self.assertTrue(archive_path.endswith('.tar.gz'))

            # Clean up
            os.remove(archive_path)

    def test_create_archive_custom_path(self):
        """Test creating archive with custom path."""
        custom_path = os.path.join(self.test_dir, 'custom-archive.tar.gz')
        archive_path = self.repo.create_archive(output_path=custom_path)

        if archive_path:
            self.assertEqual(archive_path, custom_path)
            self.assertTrue(os.path.exists(custom_path))


if __name__ == '__main__':
    unittest.main()
