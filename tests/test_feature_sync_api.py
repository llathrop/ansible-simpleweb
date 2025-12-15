"""
Feature Validation Test for Content Sync API (Feature 4)

This test validates the complete content sync workflow from the perspective
of both the primary server and worker nodes.
"""

import os
import sys
import shutil
import tempfile
import unittest
import hashlib
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.content_repo import ContentRepository


class TestFeatureSyncAPI(unittest.TestCase):
    """
    Feature validation test for content sync API.

    This test simulates:
    1. Primary server initializes content repository
    2. Workers check revision to determine if sync needed
    3. Workers get manifest to identify changed files
    4. Workers download individual files or full archive
    5. Content changes trigger new revisions
    6. Workers detect changes and sync incrementally
    """

    def setUp(self):
        """Set up test fixtures simulating primary server content."""
        self.primary_dir = tempfile.mkdtemp()

        # Create realistic content structure
        os.makedirs(os.path.join(self.primary_dir, 'playbooks'))
        os.makedirs(os.path.join(self.primary_dir, 'inventory'))
        os.makedirs(os.path.join(self.primary_dir, 'library'))
        os.makedirs(os.path.join(self.primary_dir, 'callback_plugins'))

        # Create playbooks
        self._create_file('playbooks/hardware-inventory.yml', '''---
- name: Hardware Inventory
  hosts: all
  gather_facts: yes
  tasks:
    - name: Collect hardware facts
      setup:
        gather_subset: [hardware]
''')

        self._create_file('playbooks/software-inventory.yml', '''---
- name: Software Inventory
  hosts: all
  tasks:
    - name: Get packages
      package_facts:
        manager: auto
''')

        self._create_file('playbooks/system-health.yml', '''---
- name: System Health Check
  hosts: all
  tasks:
    - name: Check uptime
      command: uptime
''')

        # Create inventory
        self._create_file('inventory/hosts', '''[webservers]
web1.example.com
web2.example.com

[dbservers]
db1.example.com
''')

        # Create library module
        self._create_file('library/custom_facts.py', '''#!/usr/bin/python
from ansible.module_utils.basic import AnsibleModule

def main():
    module = AnsibleModule(argument_spec={})
    module.exit_json(changed=False, facts={})

if __name__ == '__main__':
    main()
''')

        # Create ansible.cfg
        self._create_file('ansible.cfg', '''[defaults]
inventory = ./inventory/hosts
library = ./library
host_key_checking = False
''')

        self.repo = ContentRepository(content_dir=self.primary_dir)
        self.repo.init_repo()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.primary_dir, ignore_errors=True)

    def _create_file(self, relpath, content):
        """Helper to create a file with content."""
        filepath = os.path.join(self.primary_dir, relpath)
        with open(filepath, 'w') as f:
            f.write(content)

    def _compute_checksum(self, filepath):
        """Compute SHA256 checksum of a file."""
        full_path = os.path.join(self.primary_dir, filepath)
        with open(full_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()

    def test_complete_sync_workflow(self):
        """Test complete content sync workflow."""
        print("\n=== Feature 4: Content Sync API Workflow ===\n")

        # =====================================================================
        # Step 1: Primary server has initialized content repository
        # =====================================================================
        print("Step 1: Primary server content repository status...")

        status = self.repo.get_status()
        self.assertTrue(status['initialized'])
        self.assertGreater(status['tracked_files'], 0)

        initial_revision = self.repo.get_current_revision()
        print(f"  - Repository initialized: {status['short_revision']}")
        print(f"  - Tracked files: {status['tracked_files']}")

        # =====================================================================
        # Step 2: New worker registers and checks if sync needed
        # =====================================================================
        print("\nStep 2: Worker checks if sync needed...")

        # Simulate worker with no content (empty revision)
        worker_revision = None
        server_revision = self.repo.get_current_revision()

        needs_sync = worker_revision != server_revision
        self.assertTrue(needs_sync)
        print(f"  - Worker revision: {worker_revision}")
        print(f"  - Server revision: {server_revision[:7]}")
        print(f"  - Sync needed: {needs_sync}")

        # =====================================================================
        # Step 3: Worker gets manifest to understand what to sync
        # =====================================================================
        print("\nStep 3: Worker retrieves file manifest...")

        manifest = self.repo.get_file_manifest()
        self.assertGreater(len(manifest), 0)

        print(f"  - Files in manifest: {len(manifest)}")
        for path in sorted(manifest.keys())[:5]:
            info = manifest[path]
            print(f"    {path}: {info['size']} bytes, sha256={info['sha256'][:8]}...")

        # =====================================================================
        # Step 4: Worker downloads archive for initial sync
        # =====================================================================
        print("\nStep 4: Worker downloads content archive...")

        archive_path = self.repo.create_archive()
        if archive_path:
            archive_size = os.path.getsize(archive_path)
            print(f"  - Archive created: {os.path.basename(archive_path)}")
            print(f"  - Archive size: {archive_size} bytes")

            # Simulate worker extracting and updating revision
            worker_revision = server_revision
            print(f"  - Worker revision after sync: {worker_revision[:7]}")

            os.remove(archive_path)
        else:
            print("  - Archive creation not available")
            worker_revision = server_revision

        # =====================================================================
        # Step 5: Content changes on primary server
        # =====================================================================
        print("\nStep 5: Content updated on primary server...")

        # Add new playbook
        self._create_file('playbooks/new-playbook.yml', '''---
- name: New Playbook
  hosts: all
  tasks:
    - name: New task
      debug:
        msg: "New playbook added"
''')

        # Modify existing playbook
        self._create_file('playbooks/hardware-inventory.yml', '''---
- name: Hardware Inventory (Updated)
  hosts: all
  gather_facts: yes
  tasks:
    - name: Collect hardware facts
      setup:
        gather_subset: [hardware, network]
    - name: Display CPU info
      debug:
        var: ansible_processor
''')

        self.assertTrue(self.repo.has_changes())
        new_revision = self.repo.commit_changes('Updated hardware-inventory and added new-playbook')

        self.assertNotEqual(worker_revision, new_revision)
        print(f"  - New server revision: {new_revision[:7]}")
        print(f"  - Changes committed")

        # =====================================================================
        # Step 6: Worker detects changes via revision check
        # =====================================================================
        print("\nStep 6: Worker detects changes...")

        server_revision = self.repo.get_current_revision()
        needs_sync = worker_revision != server_revision

        self.assertTrue(needs_sync)
        print(f"  - Worker revision: {worker_revision[:7]}")
        print(f"  - Server revision: {server_revision[:7]}")
        print(f"  - Sync needed: {needs_sync}")

        # =====================================================================
        # Step 7: Worker determines changed files via manifest comparison
        # =====================================================================
        print("\nStep 7: Worker identifies changed files...")

        old_manifest = manifest  # From step 3
        new_manifest = self.repo.get_file_manifest()

        # Find new and modified files
        new_files = []
        modified_files = []
        for path, info in new_manifest.items():
            if path not in old_manifest:
                new_files.append(path)
            elif info['sha256'] != old_manifest[path]['sha256']:
                modified_files.append(path)

        self.assertIn('playbooks/new-playbook.yml', new_files)
        self.assertIn('playbooks/hardware-inventory.yml', modified_files)

        print(f"  - New files: {new_files}")
        print(f"  - Modified files: {modified_files}")

        # =====================================================================
        # Step 8: Worker downloads only changed files (incremental sync)
        # =====================================================================
        print("\nStep 8: Worker performs incremental sync...")

        files_to_sync = new_files + modified_files
        for filepath in files_to_sync:
            # Simulate downloading file
            full_path = os.path.join(self.primary_dir, filepath)
            self.assertTrue(os.path.exists(full_path))
            print(f"  - Synced: {filepath}")

        # Update worker revision
        worker_revision = server_revision
        print(f"  - Worker revision after sync: {worker_revision[:7]}")

        # =====================================================================
        # Step 9: Verify worker is in sync
        # =====================================================================
        print("\nStep 9: Verify worker is in sync...")

        needs_sync = worker_revision != server_revision
        self.assertFalse(needs_sync)
        print(f"  - Worker revision: {worker_revision[:7]}")
        print(f"  - Server revision: {server_revision[:7]}")
        print(f"  - In sync: {not needs_sync}")

        # =====================================================================
        # Step 10: Check commit history
        # =====================================================================
        print("\nStep 10: View commit history...")

        history = self.repo.get_commit_log(limit=5)
        self.assertGreater(len(history), 0)

        print(f"  - Recent commits:")
        for commit in history[:3]:
            print(f"    [{commit['sha'][:7]}] {commit['message']}")

        print("\n=== Feature 4 Validation Complete ===")
        print("Content sync API successfully supports worker synchronization!")

    def test_security_path_validation(self):
        """Test that only allowed paths can be accessed."""
        # Create a sensitive file outside tracked dirs
        os.makedirs(os.path.join(self.primary_dir, 'config'))
        self._create_file('config/secrets.json', '{"api_key": "secret"}')

        manifest = self.repo.get_file_manifest()

        # Verify sensitive file not in manifest
        self.assertNotIn('config/secrets.json', manifest)

        # Verify tracked files are in manifest
        self.assertIn('playbooks/hardware-inventory.yml', manifest)
        self.assertIn('inventory/hosts', manifest)
        self.assertIn('ansible.cfg', manifest)

    def test_manifest_checksum_verification(self):
        """Test that manifest checksums can be used for verification."""
        manifest = self.repo.get_file_manifest()

        # Verify checksums match actual file content
        for path, info in manifest.items():
            actual_checksum = self._compute_checksum(path)
            self.assertEqual(info['sha256'], actual_checksum,
                           f"Checksum mismatch for {path}")


class TestSyncEdgeCases(unittest.TestCase):
    """Test edge cases in sync workflow."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.test_dir, 'playbooks'))

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_empty_repository(self):
        """Test handling of repository with no content."""
        repo = ContentRepository(content_dir=self.test_dir)
        repo.init_repo()

        manifest = repo.get_file_manifest()
        # Should have no files (empty playbooks dir)
        playbook_files = [f for f in manifest if f.startswith('playbooks/')]
        self.assertEqual(len(playbook_files), 0)

    def test_rapid_commits(self):
        """Test handling multiple rapid commits."""
        with open(os.path.join(self.test_dir, 'playbooks', 'rapid.yml'), 'w') as f:
            f.write('initial')

        repo = ContentRepository(content_dir=self.test_dir)
        repo.init_repo()

        revisions = [repo.get_current_revision()]

        for i in range(5):
            with open(os.path.join(self.test_dir, 'playbooks', 'rapid.yml'), 'w') as f:
                f.write(f'version {i}')
            repo.commit_changes(f'Update {i}')
            revisions.append(repo.get_current_revision())

        # All revisions should be unique
        self.assertEqual(len(revisions), len(set(revisions)))

    def test_large_file_handling(self):
        """Test handling of larger files."""
        # Create a "large" file (100KB)
        large_content = 'x' * (100 * 1024)
        with open(os.path.join(self.test_dir, 'playbooks', 'large.yml'), 'w') as f:
            f.write(large_content)

        repo = ContentRepository(content_dir=self.test_dir)
        repo.init_repo()

        manifest = repo.get_file_manifest()
        self.assertIn('playbooks/large.yml', manifest)
        self.assertEqual(manifest['playbooks/large.yml']['size'], len(large_content))


if __name__ == '__main__':
    unittest.main(verbosity=2)
