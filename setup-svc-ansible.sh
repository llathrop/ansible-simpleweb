#!/bin/bash
# Setup script for svc_ansible service account
# Run this on target hosts: sudo bash setup-svc-ansible.sh

set -e

USERNAME="svc_ansible"
PASSWORD="mDpdilMAQ7rCMkhS1OA2"

echo "=== Setting up Ansible Service Account ==="

# Create user if doesn't exist
if id "$USERNAME" &>/dev/null; then
    echo "User $USERNAME already exists"
else
    echo "Creating user $USERNAME..."
    useradd -m -s /bin/bash -c "Ansible Service Account" "$USERNAME"
fi

# Set password
echo "Setting password..."
echo "$USERNAME:$PASSWORD" | chpasswd

# Create sudoers file - full NOPASSWD access for Ansible operations
echo "Configuring sudo access..."
cat > /etc/sudoers.d/svc_ansible << 'EOF'
# Ansible service account - full sudo access for automation
# Ansible requires sudo for gather_facts and many modules
svc_ansible ALL=(ALL) NOPASSWD: ALL
EOF

chmod 440 /etc/sudoers.d/svc_ansible

# Validate sudoers syntax
if visudo -cf /etc/sudoers.d/svc_ansible; then
    echo "Sudoers configuration valid"
else
    echo "ERROR: Invalid sudoers configuration!"
    rm /etc/sudoers.d/svc_ansible
    exit 1
fi

echo ""
echo "=== Setup Complete ==="
echo "Username: $USERNAME"
echo "Password: $PASSWORD"
echo "Sudo: Full NOPASSWD access"
echo ""
echo "IMPORTANT: Save the password securely and delete this script!"
