# Configuration Guide

Complete guide to configuring inventory, SSH access, and system settings.

## Table of Contents

- [Inventory Configuration](#inventory-configuration)
- [SSH Setup](#ssh-setup)
- [Service Account Setup](#service-account-setup)
- [Adding Hosts](#adding-hosts)
- [Host Groups](#host-groups)
- [Advanced Configuration](#advanced-configuration)

## Inventory Configuration

### Inventory File Location

`inventory/hosts` - Main inventory file (INI format)

### Basic Structure

```ini
[groupname]
hostname ansible_user=username ansible_ssh_private_key_file=/path/to/key

[another_group]
192.168.1.100 ansible_user=admin
server.example.com ansible_user=deploy
```

### Current Default Setup

```ini
[local]
# Container's localhost (commented out by default)
# localhost ansible_connection=local

[host_machine]
# Your actual host machine
192.168.1.50 ansible_user=svc-ansible ansible_ssh_private_key_file=/app/.ssh/svc-ansible-key

[remote_servers]
# Add additional remote hosts here

[all_hosts:children]
host_machine
remote_servers
```

## SSH Setup

### Prerequisites

Target hosts must have:
- SSH server running (`sshd`)
- Port 22 open (or custom port configured)
- User account with appropriate permissions
- Sudo access (for privileged operations)

### Authentication Methods

#### Method 1: SSH Key (Recommended)

**Advantages:**
- More secure
- No password in configuration
- Automated execution

**Setup:**

```bash
# On host machine, generate key for service account
sudo su - svc-ansible
ssh-keygen -t ed25519 -C "ansible-automation" -f ~/.ssh/id_ed25519 -N ""

# Copy to container (already done in initial setup)
# Key mounted from: ~/.ssh -> /app/.ssh

# Add to inventory
[servers]
server1.example.com ansible_user=deploy ansible_ssh_private_key_file=/app/.ssh/id_ed25519
```

#### Method 2: SSH Password

**Advantages:**
- Quick setup
- No key management

**Disadvantages:**
- Less secure
- Password visible in inventory

**Setup:**

```bash
# Install sshpass in container (already installed)
# Add to inventory
[servers]
server1.example.com ansible_user=admin ansible_ssh_pass=SecurePassword123
```

**Security Note:** Never commit inventory files with passwords to git!

### Testing SSH Connection

```bash
# Test from container
docker-compose exec -T ansible-web ansible all -m ping

# Test specific host
docker-compose exec -T ansible-web ansible 192.168.1.50 -m ping

# Test with verbose output
docker-compose exec -T ansible-web ansible 192.168.1.50 -m ping -vvv
```

## Service Account Setup

### Why Use a Service Account?

- Dedicated user for automation
- Easier auditing
- Isolate permissions
- Revoke access without affecting users

### Creating Service Account (Ubuntu/Debian)

The project includes `setup-svc-ansible.sh` script:

```bash
# Run on target host
sudo bash setup-svc-ansible.sh
```

**What it does:**
1. Creates `svc-ansible` user
2. Configures passwordless sudo
3. Generates SSH key pair
4. Sets up authorized_keys
5. Displays configuration info

### Manual Service Account Setup

```bash
# Create user
sudo useradd -m -s /bin/bash svc-ansible

# Allow passwordless sudo
echo 'svc-ansible ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/svc-ansible
sudo chmod 0440 /etc/sudoers.d/svc-ansible

# Generate SSH key
sudo su - svc-ansible
ssh-keygen -t ed25519 -C "ansible@automation" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### Service Account Best Practices

1. **Use dedicated account** - Don't use personal accounts
2. **Restrict sudo** - Only grant needed permissions
3. **Rotate keys** - Change SSH keys periodically
4. **Monitor usage** - Check auth logs regularly
5. **Document access** - Keep list of which hosts use which accounts

## Adding Hosts

### Single Host

```ini
[webservers]
web1.example.com ansible_user=deploy ansible_ssh_private_key_file=/app/.ssh/deploy_key
```

### Multiple Hosts in Group

```ini
[webservers]
web1.example.com ansible_user=deploy
web2.example.com ansible_user=deploy
web3.example.com ansible_user=deploy
```

### With Variables

```ini
[databases]
db1.example.com ansible_user=dbadmin ansible_port=2222
db2.example.com ansible_user=dbadmin ansible_port=2222
```

### Host Aliases

```ini
[servers]
web ansible_host=192.168.1.100 ansible_user=deploy
db ansible_host=192.168.1.101 ansible_user=deploy
```

Use aliases in playbooks: `ansible web -m ping`

## Host Groups

### Simple Groups

```ini
[production]
prod1.example.com
prod2.example.com

[staging]
stage1.example.com
stage2.example.com
```

### Nested Groups (Children)

```ini
[production]
prod-web1.example.com
prod-web2.example.com

[staging]
stage-web1.example.com

[webservers:children]
production
staging
```

Now targeting `webservers` runs on all production + staging hosts.

### Group Variables

Create `group_vars/` directory:

```bash
mkdir -p inventory/group_vars

# Create file for group
cat > inventory/group_vars/webservers.yml << EOF
ansible_user: deploy
ansible_port: 22
http_port: 80
EOF
```

All hosts in `webservers` group inherit these variables.

### Host Variables

Create `host_vars/` directory:

```bash
mkdir -p inventory/host_vars

# Create file for specific host
cat > inventory/host_vars/web1.example.com.yml << EOF
http_port: 8080
custom_setting: value
EOF
```

## Advanced Configuration

### Ansible Configuration File

`ansible.cfg` - Main Ansible configuration

**Key Settings:**

```ini
[defaults]
inventory = ./inventory/hosts           # Inventory location
host_key_checking = False               # Disable SSH key verification
log_path = ./logs/ansible.log           # Log file location
remote_user = root                      # Default SSH user
gathering = smart                       # Fact gathering strategy

[privilege_escalation]
become = True                           # Enable privilege escalation
become_method = sudo                    # Use sudo
become_user = root                      # Become root
become_ask_pass = False                 # Don't prompt for password
```

### SSH Configuration

Create `ansible.cfg` SSH settings:

```ini
[ssh_connection]
timeout = 30                            # SSH timeout
pipelining = True                       # Enable pipelining (faster)
control_path = /tmp/ansible-ssh-%%h-%%p-%%r
```

### Connection Settings

#### For Slow Networks:

```ini
[defaults]
timeout = 60
gather_timeout = 60
```

#### For Fast Local Networks:

```ini
[defaults]
timeout = 10
gather_timeout = 10
forks = 10                              # Parallel execution
```

### Custom Ports

```ini
[servers]
server1.example.com ansible_port=2222
server2.example.com ansible_port=2222
```

### Jump Hosts (Bastion)

```ini
[prod_servers]
internal-server.local ansible_ssh_common_args='-o ProxyCommand="ssh -W %h:%p -q bastion@jump.example.com"'
```

### Different Python Interpreters

```ini
[servers]
old-server.example.com ansible_python_interpreter=/usr/bin/python2
new-server.example.com ansible_python_interpreter=/usr/bin/python3
```

## Docker Network Configuration

### Accessing Host from Container

The container can access the host machine via:
- Host IP address (e.g., `192.168.1.50`)
- Docker gateway (typically `172.17.0.1`)

### Accessing Other Containers

If running other Docker containers that need management:

```ini
[docker_containers]
container1 ansible_connection=docker ansible_user=root
```

### Network Troubleshooting

```bash
# Check container can reach host
docker-compose exec ansible-web ping -c 3 192.168.1.50

# Check DNS resolution
docker-compose exec ansible-web nslookup server.example.com

# Check port accessibility
docker-compose exec ansible-web telnet 192.168.1.50 22
```

## Security Best Practices

### 1. Protect Inventory Files

```bash
# Restrict permissions
chmod 600 inventory/hosts

# Don't commit passwords
echo "inventory/hosts" >> .gitignore  # If it contains passwords
```

### 2. Use Ansible Vault for Secrets

```bash
# Create encrypted file
ansible-vault create inventory/secrets.yml

# Edit encrypted file
ansible-vault edit inventory/secrets.yml

# Use in playbook
vars_files:
  - secrets.yml
```

### 3. Limit SSH Access

On target hosts:

```bash
# Restrict SSH to specific users
echo "AllowUsers svc-ansible" | sudo tee -a /etc/ssh/sshd_config

# Disable password authentication
echo "PasswordAuthentication no" | sudo tee -a /etc/ssh/sshd_config

# Restart SSH
sudo systemctl restart sshd
```

### 4. Use Sudo Restrictions

Instead of `NOPASSWD:ALL`, restrict to specific commands:

```bash
# /etc/sudoers.d/svc-ansible
svc-ansible ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/bin/apt-get
```

### 5. Monitor Access

```bash
# Check auth logs on target
sudo tail -f /var/log/auth.log | grep svc-ansible

# Check Ansible logs in container
docker-compose exec -T ansible-web tail -f /app/logs/ansible.log
```

## Example Configurations

### Small Homelab

```ini
[homelab]
192.168.1.50 ansible_user=admin ansible_become_pass=password

[all:vars]
ansible_python_interpreter=/usr/bin/python3
```

### Production Environment

```ini
[production_web]
web1.prod.example.com ansible_user=deploy
web2.prod.example.com ansible_user=deploy

[production_db]
db1.prod.example.com ansible_user=dbadmin
db2.prod.example.com ansible_user=dbadmin

[production:children]
production_web
production_db

[production:vars]
ansible_ssh_private_key_file=/app/.ssh/prod_key
ansible_become=yes
```

### Multi-Environment

```ini
[dev]
dev1.example.com ansible_user=developer

[staging]
stage1.example.com ansible_user=deploy
stage2.example.com ansible_user=deploy

[production]
prod1.example.com ansible_user=deploy
prod2.example.com ansible_user=deploy
prod3.example.com ansible_user=deploy

[all:vars]
ansible_ssh_private_key_file=/app/.ssh/deploy_key
```

## Troubleshooting

### Connection Refused

```bash
# Check SSH is running on target
ssh user@target-host

# Check from container
docker-compose exec -T ansible-web ssh -v user@target-host
```

### Permission Denied

```bash
# Verify SSH key permissions
ls -la ~/.ssh/

# Keys should be 600, directories 700
chmod 700 ~/.ssh
chmod 600 ~/.ssh/id_ed25519
```

### Host Key Verification Failed

Option 1: Disable (already done in `ansible.cfg`):
```ini
[defaults]
host_key_checking = False
```

Option 2: Add to known_hosts:
```bash
ssh-keyscan target-host >> ~/.ssh/known_hosts
```

### Sudo Password Required

If playbook fails needing sudo password:

```ini
# Add to inventory
[servers]
server ansible_user=user ansible_become_pass=password
```

Or configure passwordless sudo on target (preferred).

## Next Steps

- See [USAGE.md](USAGE.md) for running playbooks
- See [ADDING_PLAYBOOKS.md](ADDING_PLAYBOOKS.md) for creating playbooks
- See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues
