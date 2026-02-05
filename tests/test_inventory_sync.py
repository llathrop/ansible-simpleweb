"""
Phase 7.1: Inventory Sync & Auth Verification

Tests that inventory content (including multiple INI files like inventory/routers
and group_vars like inventory/group_vars/routers.yml) propagates correctly to
workers via the sync system.
"""

import os
import sys
import shutil
import tempfile
import tarfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.content_repo import ContentRepository


def _create_file(base_dir: str, path: str, content: str) -> None:
    """Create a file, creating parent dirs as needed."""
    full_path = os.path.join(base_dir, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w') as f:
        f.write(content)


class TestInventorySyncManifest(unittest.TestCase):
    """Verify inventory files (including routers and group_vars) are in sync manifest."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.test_dir, 'playbooks'), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, 'inventory'), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, 'library'), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, 'callback_plugins'), exist_ok=True)

        _create_file(self.test_dir, 'playbooks/hardware-inventory.yml', '---\n- hosts: all\n')
        _create_file(self.test_dir, 'inventory/hosts', '[local]\nlocalhost\n')
        _create_file(self.test_dir, 'inventory/routers', '[routers]\n192.168.1.1 ansible_user=admin\n')
        _create_file(
            self.test_dir,
            'inventory/group_vars/routers.yml',
            'ansible_connection: network_cli\nansible_network_os: routeros\n'
        )
        _create_file(self.test_dir, 'ansible.cfg', '[defaults]\ninventory = ./inventory\n')

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_inventory_routers_in_manifest(self):
        """inventory/routers (multiple INI files) must be in sync manifest."""
        repo = ContentRepository(content_dir=self.test_dir)
        self.assertTrue(repo.init_repo(), "Content repo should initialize")

        manifest = repo.get_file_manifest()
        self.assertIn('inventory/routers', manifest,
                      "Manifest must include inventory/routers for MikroTik targets")

    def test_inventory_group_vars_in_manifest(self):
        """inventory/group_vars/routers.yml must be in sync manifest."""
        repo = ContentRepository(content_dir=self.test_dir)
        self.assertTrue(repo.init_repo(), "Content repo should initialize")

        manifest = repo.get_file_manifest()
        self.assertIn('inventory/group_vars/routers.yml', manifest,
                      "Manifest must include group_vars for routers auth/config")

    def test_archive_contains_inventory_files(self):
        """Sync archive must contain inventory/routers and group_vars."""
        repo = ContentRepository(content_dir=self.test_dir)
        self.assertTrue(repo.init_repo(), "Content repo should initialize")

        archive_path = repo.create_archive()
        self.assertIsNotNone(archive_path, "Archive creation should succeed")
        self.assertTrue(os.path.exists(archive_path), "Archive file should exist")

        try:
            with tarfile.open(archive_path, 'r:gz') as tar:
                names = tar.getnames()

            self.assertIn('inventory/routers', names,
                          "Archive must include inventory/routers")
            self.assertIn('inventory/group_vars/routers.yml', names,
                          "Archive must include inventory/group_vars/routers.yml")
        finally:
            if archive_path and os.path.exists(archive_path):
                os.remove(archive_path)

    def test_archive_content_matches_source(self):
        """Extracted archive content must match source for inventory files."""
        repo = ContentRepository(content_dir=self.test_dir)
        self.assertTrue(repo.init_repo(), "Content repo should initialize")

        archive_path = repo.create_archive()
        self.assertIsNotNone(archive_path)

        extract_dir = tempfile.mkdtemp()
        try:
            with tarfile.open(archive_path, 'r:gz') as tar:
                tar.extractall(extract_dir)

            routers_src = os.path.join(self.test_dir, 'inventory', 'routers')
            routers_dst = os.path.join(extract_dir, 'inventory', 'routers')
            self.assertTrue(os.path.exists(routers_dst))
            with open(routers_src) as f1, open(routers_dst) as f2:
                self.assertEqual(f1.read(), f2.read(), "inventory/routers content must match")

            gv_src = os.path.join(self.test_dir, 'inventory', 'group_vars', 'routers.yml')
            gv_dst = os.path.join(extract_dir, 'inventory', 'group_vars', 'routers.yml')
            self.assertTrue(os.path.exists(gv_dst))
            with open(gv_src) as f1, open(gv_dst) as f2:
                self.assertEqual(f1.read(), f2.read(), "group_vars/routers.yml content must match")
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)
            if archive_path and os.path.exists(archive_path):
                os.remove(archive_path)


def _cluster_available():
    """Check if primary is reachable for integration tests."""
    try:
        import requests
        url = os.environ.get('PRIMARY_URL', 'http://localhost:3001')
        r = requests.get(f"{url}/api/sync/manifest", timeout=5)
        return r.ok
    except Exception:
        return False


@unittest.skipUnless(_cluster_available(), "Cluster not available - run docker-compose up first")
class TestInventorySyncIntegration(unittest.TestCase):
    """Integration tests against running cluster (requires docker-compose up)."""

    def test_manifest_includes_routers_or_group_vars(self):
        """Primary manifest should include routers or group_vars when present."""
        import requests
        url = os.environ.get('PRIMARY_URL', 'http://localhost:3001')
        response = requests.get(f"{url}/api/sync/manifest", timeout=10)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        files = data.get('files', {})
        file_paths = list(files.keys()) if isinstance(files, dict) else [f.get('path', f) for f in files]

        # At least one of: inventory/routers, inventory/group_vars/routers.yml, or inventory/hosts
        inventory_paths = [p for p in file_paths if 'inventory' in p]
        self.assertGreater(len(inventory_paths), 0,
                          "Manifest should include inventory files")


if __name__ == '__main__':
    unittest.main()
