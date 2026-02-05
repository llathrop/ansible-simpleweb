"""
Tests for deployment helper (web/deployment.py): desired/current/delta, no Ansible run.
Per memory.md §7 these verify behavior.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDeploymentHelper(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__('tempfile').mkdtemp()
        os.environ['CONFIG_DIR'] = self.tmp

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch('web.deployment.get_current_services')
    @patch('web.deployment.get_desired_services')
    def test_delta_deploy_db_when_desired_and_not_reachable(self, mock_desired, mock_current):
        import web.deployment as dep
        mock_desired.return_value = {'db_enabled': True, 'agent_enabled': False, 'workers_enabled': False, 'worker_count': 0}
        mock_current.return_value = {'db_reachable': False, 'agent_reachable': False, 'worker_count': 0}
        delta = dep.get_deployment_delta(desired=mock_desired.return_value, current=mock_current.return_value)
        self.assertTrue(delta.get('deploy_db'))
        self.assertFalse(delta.get('deploy_agent'))
        self.assertFalse(delta.get('deploy_workers'))

    @patch('web.deployment.get_current_services')
    @patch('web.deployment.get_desired_services')
    def test_delta_no_deploy_db_when_already_reachable(self, mock_desired, mock_current):
        import web.deployment as dep
        mock_desired.return_value = {'db_enabled': True, 'agent_enabled': False, 'workers_enabled': False, 'worker_count': 0}
        mock_current.return_value = {'db_reachable': True, 'agent_reachable': False, 'worker_count': 0}
        delta = dep.get_deployment_delta(desired=mock_desired.return_value, current=mock_current.return_value)
        self.assertFalse(delta.get('deploy_db'))

    @patch('web.deployment.get_current_services')
    def test_delta_deploy_workers_when_wanted_more_than_current(self, mock_current):
        import web.deployment as dep
        desired = {'db_enabled': False, 'agent_enabled': False, 'workers_enabled': True, 'worker_count': 2}
        mock_current.return_value = {'db_reachable': False, 'agent_reachable': False, 'worker_count': 1}
        delta = dep.get_deployment_delta(desired=desired, current=mock_current.return_value)
        self.assertTrue(delta.get('deploy_workers'))
        self.assertEqual(delta.get('worker_count_to_add'), 1)

    def test_run_bootstrap_empty_delta_returns_ok(self):
        import web.deployment as dep
        ok, msg = dep.run_bootstrap({'deploy_db': False, 'deploy_agent': False, 'deploy_workers': False})
        self.assertTrue(ok)
        self.assertIn('Nothing', msg)

    def test_run_bootstrap_missing_playbook_returns_fail(self):
        import web.deployment as dep
        ok, msg = dep.run_bootstrap({'deploy_db': True}, playbook_dir='/nonexistent')
        self.assertFalse(ok)
        self.assertIn('not found', msg)

    def test_get_desired_services_returns_expected_structure(self):
        """get_desired_services returns dict with db_enabled, agent_enabled, workers_enabled, worker_count."""
        import web.deployment as dep
        desired = dep.get_desired_services()
        self.assertIn('db_enabled', desired)
        self.assertIn('agent_enabled', desired)
        self.assertIn('workers_enabled', desired)
        self.assertIn('worker_count', desired)
        self.assertIsInstance(desired['worker_count'], int)
        # With no config file, defaults are false/0; delta with explicit desired is tested elsewhere
        self.assertFalse(desired['db_enabled'])
        self.assertFalse(desired['agent_enabled'])

    @patch('socket.socket')
    @patch('requests.get')
    def test_get_current_services_with_none_storage(self, mock_get, mock_socket):
        """get_current_services with storage_backend=None still returns db/agent reachable and worker_count 0."""
        import web.deployment as dep
        mock_socket.return_value.connect.side_effect = OSError('refused')
        mock_get.return_value.status_code = 404
        current = dep.get_current_services(storage_backend=None)
        self.assertIn('db_reachable', current)
        self.assertIn('agent_reachable', current)
        self.assertIn('worker_count', current)
        self.assertEqual(current['worker_count'], 0)

    def test_delta_with_missing_keys_in_desired_uses_defaults(self):
        """get_deployment_delta with desired missing keys does not crash; treats as false/zero."""
        import web.deployment as dep
        desired = {}
        current = {'db_reachable': False, 'agent_reachable': False, 'worker_count': 0}
        delta = dep.get_deployment_delta(desired=desired, current=current)
        self.assertFalse(delta.get('deploy_db'))
        self.assertFalse(delta.get('deploy_agent'))
        self.assertFalse(delta.get('deploy_workers'))
        self.assertEqual(delta.get('worker_count_to_add'), 0)
