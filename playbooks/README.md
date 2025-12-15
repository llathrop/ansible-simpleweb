# Playbooks Directory

This directory contains Ansible playbooks that can be executed via the web interface.

## Adding Playbooks

Simply add `.yml` or `.yaml` files to this directory. They will automatically appear in the web interface.

## Playbook Requirements

Playbooks should:
- Be valid Ansible YAML syntax
- Include a descriptive `name` at the play level
- Use `hosts: all` or specific group names from inventory

## Example Playbook

```yaml
---
- name: Example Playbook
  hosts: all
  gather_facts: yes
  tasks:
    - name: Display hostname
      debug:
        msg: "Running on {{ ansible_hostname }}"
```

## Cluster Sync

When running in cluster mode, playbooks in this directory are automatically synced to worker nodes via git. Changes made here will be propagated to all workers.

## Included Playbooks

- `hardware-inventory.yml` - Collect hardware information
- `software-inventory.yml` - List installed packages
- `system-health.yml` - Check system health metrics
- `service-status.yml` - List running services
- `network-config.yml` - Network configuration details
- `disk-usage-analyzer.yml` - Disk space analysis
