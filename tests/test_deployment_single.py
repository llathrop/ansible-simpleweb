"""
Deployment tests: single-container mode.

Validates that docker-compose.single.yml defines only the web service and that
the app can run in single-container mode (storage=flatfile, no dependencies).
Integration tests that require a running container are in test_deployment_* or
run manually (see docs/PHASE_SINGLE_CONTAINER_BOOTSTRAP.md).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSingleCompose(unittest.TestCase):
    """Validate docker-compose.single.yml structure."""

    def test_single_compose_file_exists(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, 'docker-compose.single.yml')
        self.assertTrue(os.path.isfile(path), f'{path} should exist')

    def test_single_compose_has_one_service(self):
        try:
            import yaml
        except ImportError:
            self.skipTest('PyYAML not available')
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, 'docker-compose.single.yml')
        with open(path) as f:
            data = yaml.safe_load(f)
        services = data.get('services', {})
        self.assertEqual(list(services.keys()), ['ansible-web'], 'single compose should define only ansible-web')
        web = services['ansible-web']
        self.assertIn('environment', web)
        env = {e.split('=', 1)[0]: e.split('=', 1)[1] for e in web['environment'] if '=' in e}
        self.assertEqual(env.get('STORAGE_BACKEND', ''), 'flatfile')
        self.assertEqual(env.get('CLUSTER_MODE', ''), 'standalone')
        self.assertNotIn('depends_on', web)
