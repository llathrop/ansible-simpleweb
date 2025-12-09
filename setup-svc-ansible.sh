#!/bin/bash
# Setup script for svc-ansible service account
# Run this on the HOST machine (not in Docker container)

set -e  # Exit on error

echo "=================================="
echo "Setting up svc-ansible account"
echo "=================================="
echo

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Please run with sudo:"
    echo "  sudo bash setup-svc-ansible.sh"
    exit 1
fi

# 1. Create service account
echo "[1/5] Creating svc-ansible user..."
if id "svc-ansible" &>/dev/null; then
    echo "  ⚠ User svc-ansible already exists, skipping..."
else
    useradd -m -s /bin/bash svc-ansible
    echo "  ✓ User svc-ansible created"
fi

# 2. Set up sudo permissions
echo "[2/5] Configuring sudo permissions..."
cat > /etc/sudoers.d/svc-ansible << 'EOF'
# Allow svc-ansible to run all commands without password
svc-ansible ALL=(ALL) NOPASSWD:ALL
EOF
chmod 0440 /etc/sudoers.d/svc-ansible
echo "  ✓ Sudo permissions configured"

# 3. Generate SSH keys
echo "[3/5] Generating SSH keys..."
sudo -u svc-ansible bash << 'EOF'
mkdir -p ~/.ssh
chmod 700 ~/.ssh

if [ -f ~/.ssh/id_ed25519 ]; then
    echo "  ⚠ SSH key already exists, skipping generation..."
else
    ssh-keygen -t ed25519 -C "svc-ansible@ansible-automation" -f ~/.ssh/id_ed25519 -N ""
    echo "  ✓ SSH key generated"
fi

# Add to authorized_keys
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
echo "  ✓ SSH key added to authorized_keys"
EOF

# 4. Verify SSH service
echo "[4/5] Checking SSH service..."
if systemctl is-active --quiet sshd || systemctl is-active --quiet ssh; then
    echo "  ✓ SSH service is running"
else
    echo "  ⚠ WARNING: SSH service is not running!"
    echo "    Start it with: sudo systemctl start sshd"
fi

# 5. Display configuration info
echo "[5/5] Setup complete!"
echo
echo "=================================="
echo "Configuration Summary"
echo "=================================="
echo
echo "Host IP Address(es):"
hostname -I
echo
echo "SSH Service Status:"
systemctl is-active sshd 2>/dev/null || systemctl is-active ssh 2>/dev/null || echo "Not running"
echo
echo "=================================="
echo "SSH Private Key for Container"
echo "=================================="
echo "(Copy this entire key including BEGIN/END lines)"
echo
sudo cat /home/svc-ansible/.ssh/id_ed25519
echo
echo "=================================="
echo "Next Steps"
echo "=================================="
echo "1. Copy the private key above"
echo "2. Note the host IP address"
echo "3. Provide these to Claude to configure the container"
echo "=================================="
