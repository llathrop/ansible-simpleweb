"""
Tests for inventory sync (DB <-> static inventory).
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.inventory_sync import (
    sync_db_to_static,
    sync_static_to_db,
    run_inventory_sync,
    MANAGED_HOSTS_FILE,
)


class MockStorage:
    """Mock storage backend for inventory sync tests."""

    def __init__(self):
        self.inventory = []

    def get_all_inventory(self):
        return list(self.inventory)

    def save_inventory_item(self, item_id, item):
        self.inventory = [i for i in self.inventory if i.get('id') != item_id]
        self.inventory.append(item)
        return True


class TestInventorySync(unittest.TestCase):
    """Verify inventory sync: DB to static and static to DB."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.storage = MockStorage()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sync_db_to_static_writes_managed_hosts_ini(self):
        """DB hosts are written to managed_hosts.ini."""
        self.storage.inventory = [
            {
                'id': 'id1',
                'hostname': 'web1.example.com',
                'group': 'webservers',
                'variables': {'ansible_user': 'deploy'},
            },
            {
                'id': 'id2',
                'hostname': 'db1.example.com',
                'group': 'databases',
                'variables': {},
            },
        ]
        n, err = sync_db_to_static(self.storage, self.tmp)
        self.assertIsNone(err)
        self.assertEqual(n, 2)
        path = os.path.join(self.tmp, MANAGED_HOSTS_FILE)
        self.assertTrue(os.path.isfile(path))
        content = open(path).read()
        self.assertIn('[webservers]', content)
        self.assertIn('web1.example.com', content)
        self.assertIn('ansible_user=deploy', content)
        self.assertIn('[databases]', content)
        self.assertIn('db1.example.com', content)

    def test_sync_db_to_static_empty_writes_empty_file(self):
        """Empty DB writes managed_hosts.ini with just headers."""
        n, err = sync_db_to_static(self.storage, self.tmp)
        self.assertIsNone(err)
        self.assertEqual(n, 0)
        path = os.path.join(self.tmp, MANAGED_HOSTS_FILE)
        self.assertTrue(os.path.isfile(path))
        content = open(path).read()
        self.assertIn('Auto-generated', content)
        self.assertNotIn('[', content.replace('# [', ''))

    def test_sync_static_to_db_adds_missing_hosts(self):
        """Hosts in static inventory are added to DB if missing."""
        hosts_ini = os.path.join(self.tmp, 'hosts.ini')
        with open(hosts_ini, 'w') as f:
            f.write("[webservers]\nweb1.example.com ansible_user=deploy\n")
        n, err = sync_static_to_db(self.storage, self.tmp)
        self.assertIsNone(err)
        self.assertEqual(n, 1)
        inv = self.storage.get_all_inventory()
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv[0]['hostname'], 'web1.example.com')
        self.assertEqual(inv[0]['group'], 'webservers')
        self.assertEqual(inv[0]['variables'], {'ansible_user': 'deploy'})

    def test_sync_static_to_db_skips_existing(self):
        """Hosts already in DB are not duplicated."""
        self.storage.inventory = [
            {'id': 'id1', 'hostname': 'web1.example.com', 'group': 'x', 'variables': {}},
        ]
        hosts_ini = os.path.join(self.tmp, 'hosts.ini')
        with open(hosts_ini, 'w') as f:
            f.write("[webservers]\nweb1.example.com\n")
        n, err = sync_static_to_db(self.storage, self.tmp)
        self.assertIsNone(err)
        self.assertEqual(n, 0)
        self.assertEqual(len(self.storage.get_all_inventory()), 1)

    def test_run_inventory_sync_full_cycle(self):
        """Full sync: DB to static, then static to DB, then db_to_static again."""
        self.storage.inventory = [
            {'id': 'id1', 'hostname': 'db-host', 'group': 'managed', 'variables': {}},
        ]
        hosts_ini = os.path.join(self.tmp, 'hosts.ini')
        with open(hosts_ini, 'w') as f:
            f.write("[static]\nstatic-host.example.com\n")
        result = run_inventory_sync(self.storage, self.tmp)
        self.assertIsNone(result.get('error'))
        self.assertGreaterEqual(result['db_to_static'], 1)
        self.assertEqual(result['static_to_db'], 1)
        managed_path = os.path.join(self.tmp, MANAGED_HOSTS_FILE)
        self.assertTrue(os.path.isfile(managed_path))
        inv = self.storage.get_all_inventory()
        hostnames = {i['hostname'] for i in inv}
        self.assertIn('db-host', hostnames)
        self.assertIn('static-host.example.com', hostnames)
