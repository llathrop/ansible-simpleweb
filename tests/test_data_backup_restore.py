"""
Tests for data backup/restore API (GET /api/data/backup, POST /api/data/restore).

Real tests: real Flask app, real FlatFileStorage with temp dir (no mocks).
MongoDB branch tested only when MongoDB is reachable (skip otherwise).
"""
import os
import sys
import json
import zipfile
import tempfile
import unittest
from io import BytesIO

os.environ.setdefault('SECRET_KEY', 'test-key')
os.environ.setdefault('CLUSTER_MODE', 'standalone')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Minimal harness: allow test client without eventlet
from unittest.mock import MagicMock
mock_socketio = MagicMock()
sys.modules['flask_socketio'] = mock_socketio

import web.app as app_module


class TestDataBackupRestoreAPI(unittest.TestCase):
    """Real API tests: app uses real FlatFileStorage with temp CONFIG_DIR."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ['CONFIG_DIR'] = self.tmp
        # Initialize real storage (same as app main block)
        app_module.storage_backend = app_module.get_storage_backend()
        self.client = app_module.app.test_client()
        self.client.testing = True

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_data_backup_no_storage_returns_500(self):
        """When storage backend is not initialized, backup returns 500."""
        app_module.storage_backend = None
        resp = self.client.get('/api/data/backup')
        self.assertEqual(resp.status_code, 500)
        # Restore for other tests (next test will re-set in setUp)
        app_module.storage_backend = app_module.get_storage_backend()

    def test_data_backup_flatfile_returns_zip(self):
        """GET /api/data/backup with real flatfile storage returns zip."""
        resp = self.client.get('/api/data/backup')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('zip', resp.content_type or '')
        self.assertIn('attachment', resp.headers.get('Content-Disposition', ''))
        buf = BytesIO(resp.data)
        z = zipfile.ZipFile(buf, 'r')
        z.close()

    def test_data_backup_flatfile_zip_contains_expected_files(self):
        """Real outcome: backup zip contains entries for existing data files."""
        with open(os.path.join(self.tmp, 'schedules.json'), 'w') as f:
            json.dump({'schedules': {}}, f)
        with open(os.path.join(self.tmp, 'inventory.json'), 'w') as f:
            json.dump({'inventory': []}, f)
        resp = self.client.get('/api/data/backup')
        self.assertEqual(resp.status_code, 200)
        buf = BytesIO(resp.data)
        z = zipfile.ZipFile(buf, 'r')
        names = z.namelist()
        z.close()
        self.assertIn('schedules.json', names)
        self.assertIn('inventory.json', names)

    def test_data_restore_no_storage_returns_500(self):
        """When storage is not initialized, restore returns 500."""
        app_module.storage_backend = None
        try:
            resp = self.client.post('/api/data/restore', data={})
            self.assertEqual(resp.status_code, 500)
        finally:
            app_module.storage_backend = app_module.get_storage_backend()

    def test_data_restore_flatfile_no_file_returns_400(self):
        """POST /api/data/restore with no file returns 400."""
        resp = self.client.post('/api/data/restore')
        self.assertEqual(resp.status_code, 400)

    def test_data_restore_flatfile_writes_files(self):
        """Real outcome: restore writes zip entries into storage config_dir."""
        payload = {'schedules': {'id1': {'name': 'Test'}}}
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('schedules.json', json.dumps(payload))
        buf.seek(0)
        resp = self.client.post('/api/data/restore', data={'file': (buf, 'backup.zip')})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        path = os.path.join(self.tmp, 'schedules.json')
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            restored = json.load(f)
        self.assertEqual(restored.get('schedules', {}).get('id1', {}).get('name'), 'Test')

    def test_data_restore_invalid_zip_returns_error(self):
        """POST /api/data/restore with non-zip file returns 400 or 500."""
        buf = BytesIO(b'not a zip file')
        resp = self.client.post('/api/data/restore', data={'file': (buf, 'fake.zip')})
        self.assertIn(resp.status_code, (400, 500))
        if resp.status_code == 500:
            data = resp.get_json()
            self.assertIn('error', data)


# MongoDB backup/restore: run only when MongoDB is reachable (real integration)
class TestDataBackupRestoreMongoDB(unittest.TestCase):
    """MongoDB backup/restore: real tests when MongoDB is available."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('SECRET_KEY', 'test-key')
        os.environ.setdefault('CLUSTER_MODE', 'standalone')
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if 'flask_socketio' not in sys.modules or not hasattr(sys.modules['flask_socketio'], 'SocketIO'):
            from unittest.mock import MagicMock
            sys.modules['flask_socketio'] = MagicMock()
        import web.storage as st
        try:
            os.environ['STORAGE_BACKEND'] = 'mongodb'
            storage = st.get_storage_backend()
            cls.mongodb_available = storage.health_check()
        except Exception:
            cls.mongodb_available = False
        os.environ.pop('STORAGE_BACKEND', None)

    def setUp(self):
        if not self.mongodb_available:
            self.skipTest('MongoDB not reachable; set STORAGE_BACKEND=mongodb and ensure MongoDB is running')
        import web.app as app_module
        self.app_module = app_module
        self.tmp = tempfile.mkdtemp()
        os.environ['CONFIG_DIR'] = self.tmp
        os.environ['STORAGE_BACKEND'] = 'mongodb'
        self.app_module.storage_backend = self.app_module.get_storage_backend()
        self.client = self.app_module.app.test_client()
        self.client.testing = True

    def tearDown(self):
        os.environ.pop('STORAGE_BACKEND', None)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_data_backup_mongodb_returns_zip(self):
        """Real MongoDB backup returns zip of exported collections."""
        resp = self.client.get('/api/data/backup')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('zip', resp.content_type or '')
        self.assertIn('attachment', resp.headers.get('Content-Disposition', ''))

    def test_data_restore_mongodb_no_file_returns_400(self):
        """POST /api/data/restore with MongoDB backend and no file returns 400."""
        resp = self.client.post('/api/data/restore')
        self.assertEqual(resp.status_code, 400)
