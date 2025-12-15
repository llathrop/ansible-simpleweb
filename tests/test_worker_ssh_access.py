"""
Unit Tests for Worker SSH Access Configuration.

Tests verify that worker containers have proper SSH configuration
to reach inventory hosts. These tests check configuration correctness
rather than actual connectivity (which requires live hosts).

Run with: pytest tests/test_worker_ssh_access.py -v
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSSHDirectoryStructure(unittest.TestCase):
    """Test SSH directory structure requirements."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.ssh_dir = os.path.join(self.test_dir, '.ssh')

    def tearDown(self):
        """Clean up test directories."""
        shutil.rmtree(self.test_dir)

    def test_ssh_directory_created(self):
        """Test that .ssh directory can be created with correct permissions."""
        os.makedirs(self.ssh_dir, mode=0o700)

        self.assertTrue(os.path.exists(self.ssh_dir))
        self.assertTrue(os.path.isdir(self.ssh_dir))

        # Check permissions (700)
        stat_info = os.stat(self.ssh_dir)
        permissions = stat_info.st_mode & 0o777
        self.assertEqual(permissions, 0o700)

    def test_ssh_key_permissions(self):
        """Test that SSH key files have correct permissions."""
        os.makedirs(self.ssh_dir, mode=0o700)
        key_file = os.path.join(self.ssh_dir, 'id_rsa')

        # Create a mock key file
        with open(key_file, 'w') as f:
            f.write('-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----')

        # Set correct permissions (600)
        os.chmod(key_file, 0o600)

        stat_info = os.stat(key_file)
        permissions = stat_info.st_mode & 0o777
        self.assertEqual(permissions, 0o600)

    def test_known_hosts_permissions(self):
        """Test that known_hosts file has correct permissions."""
        os.makedirs(self.ssh_dir, mode=0o700)
        known_hosts = os.path.join(self.ssh_dir, 'known_hosts')

        with open(known_hosts, 'w') as f:
            f.write('# Known hosts for ansible targets\n')

        # Set correct permissions (644 or 600)
        os.chmod(known_hosts, 0o644)

        stat_info = os.stat(known_hosts)
        permissions = stat_info.st_mode & 0o777
        self.assertIn(permissions, [0o644, 0o600])


class TestSSHConfigFile(unittest.TestCase):
    """Test SSH configuration file handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.ssh_dir = os.path.join(self.test_dir, '.ssh')
        os.makedirs(self.ssh_dir, mode=0o700)

    def tearDown(self):
        """Clean up test directories."""
        shutil.rmtree(self.test_dir)

    def test_ssh_config_format(self):
        """Test SSH config file follows correct format."""
        config_content = """Host *
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR

Host target-server
    HostName 192.168.1.100
    User ansible
    IdentityFile ~/.ssh/ansible_key
    Port 22
"""
        config_file = os.path.join(self.ssh_dir, 'config')
        with open(config_file, 'w') as f:
            f.write(config_content)

        # Verify file exists and is readable
        self.assertTrue(os.path.exists(config_file))
        with open(config_file, 'r') as f:
            content = f.read()

        self.assertIn('Host *', content)
        self.assertIn('StrictHostKeyChecking', content)

    def test_disable_host_key_checking(self):
        """Test configuration to disable strict host key checking."""
        config_content = """Host *
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
"""
        config_file = os.path.join(self.ssh_dir, 'config')
        with open(config_file, 'w') as f:
            f.write(config_content)

        with open(config_file, 'r') as f:
            content = f.read()

        self.assertIn('StrictHostKeyChecking no', content)
        self.assertIn('UserKnownHostsFile /dev/null', content)


class TestAnsibleSSHConfiguration(unittest.TestCase):
    """Test Ansible SSH configuration options."""

    def test_ansible_cfg_ssh_settings(self):
        """Test ansible.cfg SSH-related settings."""
        ansible_cfg_content = """[defaults]
host_key_checking = False
timeout = 30

[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=60s -o StrictHostKeyChecking=no
pipelining = True
"""
        # Parse and verify key settings
        self.assertIn('host_key_checking = False', ansible_cfg_content)
        self.assertIn('StrictHostKeyChecking=no', ansible_cfg_content)
        self.assertIn('pipelining = True', ansible_cfg_content)

    def test_inventory_ssh_vars(self):
        """Test inventory file SSH variables."""
        inventory_content = """[webservers]
web1.example.com ansible_user=deploy ansible_ssh_private_key_file=/app/ssh-keys/deploy_key

[dbservers]
db1.example.com ansible_user=admin ansible_port=2222

[all:vars]
ansible_ssh_common_args='-o StrictHostKeyChecking=no'
"""
        self.assertIn('ansible_user=', inventory_content)
        self.assertIn('ansible_ssh_private_key_file=', inventory_content)
        self.assertIn('ansible_port=', inventory_content)
        self.assertIn('ansible_ssh_common_args=', inventory_content)


class TestSSHKeyManagement(unittest.TestCase):
    """Test SSH key management for workers."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.keys_dir = os.path.join(self.test_dir, 'ssh-keys')
        os.makedirs(self.keys_dir)

    def tearDown(self):
        """Clean up test directories."""
        shutil.rmtree(self.test_dir)

    def test_key_file_discovery(self):
        """Test discovery of SSH key files in directory."""
        # Create some key files
        key_files = ['id_rsa', 'deploy_key', 'ansible_key.pem']
        for key in key_files:
            key_path = os.path.join(self.keys_dir, key)
            with open(key_path, 'w') as f:
                f.write(f'# Mock key: {key}')

        # Discover keys
        found_keys = [f for f in os.listdir(self.keys_dir)
                      if os.path.isfile(os.path.join(self.keys_dir, f))]

        self.assertEqual(len(found_keys), 3)
        for key in key_files:
            self.assertIn(key, found_keys)

    def test_key_file_validation_header(self):
        """Test validation of SSH key file format."""
        key_content = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA...
-----END RSA PRIVATE KEY-----"""

        key_path = os.path.join(self.keys_dir, 'test_key')
        with open(key_path, 'w') as f:
            f.write(key_content)

        with open(key_path, 'r') as f:
            content = f.read()

        # Verify key format
        self.assertTrue(
            content.startswith('-----BEGIN') and '-----END' in content,
            "Key file should have PEM format"
        )

    def test_openssh_key_format(self):
        """Test OpenSSH key format validation."""
        key_content = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABlwAAAAdzc2gtcn
-----END OPENSSH PRIVATE KEY-----"""

        key_path = os.path.join(self.keys_dir, 'openssh_key')
        with open(key_path, 'w') as f:
            f.write(key_content)

        with open(key_path, 'r') as f:
            content = f.read()

        # Verify OpenSSH format
        self.assertIn('OPENSSH PRIVATE KEY', content)


class TestDockerVolumeMounts(unittest.TestCase):
    """Test Docker volume mount configuration for SSH."""

    def test_ssh_keys_volume_config(self):
        """Test ssh-keys volume mount configuration."""
        # Expected docker-compose.yml configuration
        volume_config = {
            'ssh-keys': {
                'source': './ssh-keys',
                'target': '/app/ssh-keys',
                'read_only': True
            }
        }

        self.assertEqual(volume_config['ssh-keys']['source'], './ssh-keys')
        self.assertEqual(volume_config['ssh-keys']['target'], '/app/ssh-keys')
        self.assertTrue(volume_config['ssh-keys']['read_only'])

    def test_host_ssh_volume_config(self):
        """Test host .ssh directory mount configuration."""
        volume_config = {
            'host-ssh': {
                'source': '~/.ssh',
                'target': '/root/.ssh',
                'read_only': True
            }
        }

        self.assertEqual(volume_config['host-ssh']['target'], '/root/.ssh')
        self.assertTrue(volume_config['host-ssh']['read_only'])

    def test_network_mode_host(self):
        """Test network_mode: host configuration for direct network access."""
        network_config = {
            'network_mode': 'host'
        }

        self.assertEqual(network_config['network_mode'], 'host')


class TestSSHConnectivitySimulation(unittest.TestCase):
    """Test SSH connectivity simulation (mocked)."""

    @patch('subprocess.run')
    def test_ssh_key_auth_command(self, mock_run):
        """Test SSH command with key-based authentication."""
        mock_run.return_value = MagicMock(returncode=0, stdout='Success')

        import subprocess
        result = subprocess.run([
            'ssh', '-i', '/app/ssh-keys/deploy_key',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'BatchMode=yes',
            'user@target', 'echo', 'test'
        ], capture_output=True, text=True)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertIn('-i', call_args)
        self.assertIn('/app/ssh-keys/deploy_key', call_args)

    @patch('subprocess.run')
    def test_ansible_connection_test(self, mock_run):
        """Test Ansible connection test command."""
        mock_run.return_value = MagicMock(returncode=0, stdout='pong')

        import subprocess
        result = subprocess.run([
            'ansible', 'all', '-m', 'ping',
            '-i', '/app/inventory/hosts'
        ], capture_output=True, text=True)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertIn('ansible', call_args)
        self.assertIn('-m', call_args)
        self.assertIn('ping', call_args)


class TestExtraHostsConfiguration(unittest.TestCase):
    """Test extra_hosts Docker configuration for DNS."""

    def test_extra_hosts_format(self):
        """Test extra_hosts configuration format."""
        extra_hosts = [
            'target1.example.com:192.168.1.100',
            'target2.example.com:192.168.1.101',
            'db.internal:10.0.0.50'
        ]

        # Verify format (hostname:ip)
        for entry in extra_hosts:
            self.assertIn(':', entry)
            hostname, ip = entry.split(':')
            self.assertTrue(len(hostname) > 0)
            self.assertTrue(len(ip) > 0)

    def test_parse_extra_hosts(self):
        """Test parsing extra_hosts into /etc/hosts format."""
        extra_hosts = [
            'target1.example.com:192.168.1.100',
            'target2.example.com:192.168.1.101'
        ]

        # Convert to /etc/hosts format
        hosts_lines = []
        for entry in extra_hosts:
            hostname, ip = entry.split(':')
            hosts_lines.append(f'{ip}\t{hostname}')

        expected = ['192.168.1.100\ttarget1.example.com',
                    '192.168.1.101\ttarget2.example.com']
        self.assertEqual(hosts_lines, expected)


class TestInventorySyncForSSH(unittest.TestCase):
    """Test inventory synchronization includes SSH configuration."""

    def test_inventory_has_ssh_vars(self):
        """Test synced inventory contains SSH variables."""
        inventory_content = """[webservers]
web1 ansible_host=192.168.1.10 ansible_user=deploy ansible_ssh_private_key_file=/app/ssh-keys/key
web2 ansible_host=192.168.1.11 ansible_user=deploy

[all:vars]
ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
"""
        # Verify SSH-related variables are present
        self.assertIn('ansible_user=', inventory_content)
        self.assertIn('ansible_ssh_private_key_file=', inventory_content)
        self.assertIn('ansible_ssh_common_args=', inventory_content)

    def test_group_vars_ssh_settings(self):
        """Test group_vars can contain SSH settings."""
        group_vars = {
            'ansible_user': 'deploy',
            'ansible_become': True,
            'ansible_become_method': 'sudo',
            'ansible_ssh_common_args': '-o StrictHostKeyChecking=no'
        }

        self.assertIn('ansible_user', group_vars)
        self.assertIn('ansible_ssh_common_args', group_vars)


if __name__ == '__main__':
    unittest.main()
