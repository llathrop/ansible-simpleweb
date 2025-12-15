"""
Feature Validation Test for Content Repository Setup (Feature 3)

This test validates the complete content repository workflow for syncing
Ansible content to worker nodes.
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


class TestFeatureContentRepository(unittest.TestCase):
    """
    Feature validation test for content repository.

    This test simulates a complete content repository workflow:
    1. Initialize repository with existing Ansible content
    2. Track changes to playbooks
    3. Commit changes and track revisions
    4. Generate manifests for sync verification
    5. Support worker sync scenarios
    """

    def setUp(self):
        """Set up test fixtures with realistic directory structure."""
        self.test_dir = tempfile.mkdtemp()

        # Create realistic Ansible directory structure
        os.makedirs(os.path.join(self.test_dir, 'playbooks'))
        os.makedirs(os.path.join(self.test_dir, 'inventory'))
        os.makedirs(os.path.join(self.test_dir, 'library'))
        os.makedirs(os.path.join(self.test_dir, 'callback_plugins'))

        # Create sample playbooks
        self._create_playbook('hardware-inventory.yml', '''---
- name: Hardware Inventory
  hosts: all
  gather_facts: yes
  tasks:
    - name: Collect hardware facts
      setup:
        gather_subset:
          - hardware
''')

        self._create_playbook('software-inventory.yml', '''---
- name: Software Inventory
  hosts: all
  tasks:
    - name: Get installed packages
      package_facts:
        manager: auto
''')

        # Create sample inventory
        with open(os.path.join(self.test_dir, 'inventory', 'hosts'), 'w') as f:
            f.write('''[webservers]
web1.example.com
web2.example.com

[dbservers]
db1.example.com

[all:vars]
ansible_python_interpreter=/usr/bin/python3
''')

        # Create sample library module
        with open(os.path.join(self.test_dir, 'library', 'custom_module.py'), 'w') as f:
            f.write('''#!/usr/bin/python
from ansible.module_utils.basic import AnsibleModule

def main():
    module = AnsibleModule(argument_spec={})
    module.exit_json(changed=False)

if __name__ == '__main__':
    main()
''')

        # Create ansible.cfg
        with open(os.path.join(self.test_dir, 'ansible.cfg'), 'w') as f:
            f.write('''[defaults]
inventory = ./inventory/hosts
library = ./library
callback_plugins = ./callback_plugins
host_key_checking = False
''')

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_playbook(self, name, content):
        """Helper to create a playbook file."""
        path = os.path.join(self.test_dir, 'playbooks', name)
        with open(path, 'w') as f:
            f.write(content)

    def test_complete_content_sync_workflow(self):
        """
        Test the complete content repository workflow.
        """
        print("\n=== Feature 3: Content Repository Workflow ===\n")

        # =====================================================================
        # Step 1: Initialize repository with existing content
        # =====================================================================
        print("Step 1: Initialize content repository...")

        repo = ContentRepository(content_dir=self.test_dir)
        self.assertFalse(repo.is_initialized())

        result = repo.init_repo()
        self.assertTrue(result)
        self.assertTrue(repo.is_initialized())

        initial_rev = repo.get_current_revision()
        self.assertIsNotNone(initial_rev)
        print(f"  - Repository initialized with revision: {initial_rev[:7]}")

        # =====================================================================
        # Step 2: Verify all content is tracked
        # =====================================================================
        print("\nStep 2: Verify tracked content...")

        manifest = repo.get_file_manifest()
        self.assertGreater(len(manifest), 0)

        # Check expected files are tracked
        self.assertIn('playbooks/hardware-inventory.yml', manifest)
        self.assertIn('playbooks/software-inventory.yml', manifest)
        self.assertIn('inventory/hosts', manifest)
        self.assertIn('library/custom_module.py', manifest)
        self.assertIn('ansible.cfg', manifest)

        print(f"  - Tracked files: {len(manifest)}")
        for path in sorted(manifest.keys()):
            info = manifest[path]
            print(f"    {path} ({info['size']} bytes)")

        # =====================================================================
        # Step 3: Add new playbook and detect changes
        # =====================================================================
        print("\nStep 3: Add new playbook and detect changes...")

        self.assertFalse(repo.has_changes())

        self._create_playbook('new-playbook.yml', '''---
- name: New Playbook
  hosts: all
  tasks:
    - name: Debug message
      debug:
        msg: "Hello from new playbook"
''')

        self.assertTrue(repo.has_changes())
        print("  - New playbook added, changes detected")

        # =====================================================================
        # Step 4: Commit changes and verify revision
        # =====================================================================
        print("\nStep 4: Commit changes...")

        new_rev = repo.commit_changes('Added new-playbook.yml')

        self.assertIsNotNone(new_rev)
        self.assertNotEqual(initial_rev, new_rev)
        self.assertFalse(repo.has_changes())

        print(f"  - New revision: {new_rev[:7]}")

        # =====================================================================
        # Step 5: Modify existing playbook
        # =====================================================================
        print("\nStep 5: Modify existing playbook...")

        self._create_playbook('hardware-inventory.yml', '''---
- name: Hardware Inventory (Updated)
  hosts: all
  gather_facts: yes
  tasks:
    - name: Collect hardware facts
      setup:
        gather_subset:
          - hardware
          - network
    - name: Display facts
      debug:
        var: ansible_facts
''')

        self.assertTrue(repo.has_changes())

        modified_rev = repo.commit_changes('Updated hardware-inventory.yml')
        self.assertNotEqual(new_rev, modified_rev)
        print(f"  - Modified revision: {modified_rev[:7]}")

        # =====================================================================
        # Step 6: Check commit history
        # =====================================================================
        print("\nStep 6: Check commit history...")

        log = repo.get_commit_log(limit=5)
        self.assertGreaterEqual(len(log), 3)  # Initial + 2 commits

        print(f"  - Commit log ({len(log)} entries):")
        for entry in log[:3]:
            print(f"    [{entry['sha'][:7]}] {entry['message']}")

        # =====================================================================
        # Step 7: Generate manifest for worker sync verification
        # =====================================================================
        print("\nStep 7: Generate sync manifest...")

        manifest = repo.get_file_manifest()
        self.assertIn('playbooks/new-playbook.yml', manifest)

        # Verify checksums can be used for sync verification
        for path, info in manifest.items():
            self.assertIn('sha256', info)
            self.assertEqual(len(info['sha256']), 64)

        print(f"  - Manifest generated: {len(manifest)} files")

        # =====================================================================
        # Step 8: Get repository status
        # =====================================================================
        print("\nStep 8: Repository status...")

        status = repo.get_status()

        self.assertTrue(status['initialized'])
        self.assertEqual(status['revision'], modified_rev)
        self.assertFalse(status['has_uncommitted_changes'])
        self.assertEqual(status['tracked_dirs'], ContentRepository.TRACKED_DIRS)

        print(f"  - Initialized: {status['initialized']}")
        print(f"  - Revision: {status['short_revision']}")
        print(f"  - Tracked files: {status['tracked_files']}")
        print(f"  - Uncommitted changes: {status['has_uncommitted_changes']}")

        # =====================================================================
        # Step 9: Test archive creation for bulk sync
        # =====================================================================
        print("\nStep 9: Create archive for bulk sync...")

        archive_path = repo.create_archive()
        if archive_path:
            self.assertTrue(os.path.exists(archive_path))
            archive_size = os.path.getsize(archive_path)
            print(f"  - Archive created: {archive_path}")
            print(f"  - Archive size: {archive_size} bytes")
            os.remove(archive_path)
        else:
            print("  - Archive creation skipped (git archive not available)")

        # =====================================================================
        # Step 10: Simulate worker sync verification
        # =====================================================================
        print("\nStep 10: Simulate worker sync verification...")

        # Worker would compare their revision with server
        server_revision = repo.get_current_revision()
        worker_revision = initial_rev  # Worker has old revision

        needs_sync = server_revision != worker_revision
        self.assertTrue(needs_sync)
        print(f"  - Server revision: {server_revision[:7]}")
        print(f"  - Worker revision: {worker_revision[:7]}")
        print(f"  - Sync needed: {needs_sync}")

        # After sync, worker would have same revision
        worker_revision = server_revision
        needs_sync = server_revision != worker_revision
        self.assertFalse(needs_sync)
        print(f"  - After sync, worker revision: {worker_revision[:7]}")
        print(f"  - Sync needed: {needs_sync}")

        print("\n=== Feature 3 Validation Complete ===")
        print("Content repository successfully manages Ansible content sync!")

    def test_multiple_directories_tracked(self):
        """Test that all tracked directories are properly managed."""
        repo = ContentRepository(content_dir=self.test_dir)
        repo.init_repo()

        # Add files to each tracked directory
        with open(os.path.join(self.test_dir, 'callback_plugins', 'test_cb.py'), 'w') as f:
            f.write('# Test callback plugin\n')

        with open(os.path.join(self.test_dir, 'inventory', 'hosts.dev'), 'w') as f:
            f.write('[dev]\nlocalhost\n')

        repo.commit_changes('Add files to multiple directories')

        manifest = repo.get_file_manifest()

        # Verify files from all directories
        tracked_dirs = set()
        for path in manifest.keys():
            parts = path.split('/')
            if len(parts) > 1:
                tracked_dirs.add(parts[0])

        self.assertIn('playbooks', tracked_dirs)
        self.assertIn('inventory', tracked_dirs)
        self.assertIn('library', tracked_dirs)
        self.assertIn('callback_plugins', tracked_dirs)

    def test_idempotent_initialization(self):
        """Test that re-initialization doesn't lose data."""
        repo = ContentRepository(content_dir=self.test_dir)
        repo.init_repo()

        initial_rev = repo.get_current_revision()
        initial_manifest = repo.get_file_manifest()

        # Re-initialize
        repo2 = ContentRepository(content_dir=self.test_dir)
        repo2.init_repo()

        # Data should be preserved
        self.assertEqual(repo2.get_current_revision(), initial_rev)
        self.assertEqual(len(repo2.get_file_manifest()), len(initial_manifest))


if __name__ == '__main__':
    unittest.main(verbosity=2)
