# Inventory Directory

This directory contains Ansible inventory files defining hosts and groups.

## Inventory Format

The primary inventory file is `hosts` using INI format:

```ini
[webservers]
web1.example.com
web2.example.com ansible_host=192.168.1.10

[dbservers]
db1.example.com ansible_user=dbadmin

[all:vars]
ansible_python_interpreter=/usr/bin/python3
```

## Managed Inventory

In addition to static inventory files, hosts can be added via the web interface. These "managed" hosts are stored in the application database and merged with static inventory at runtime.

## Cluster Sync

When running in cluster mode, inventory files in this directory are synced to worker nodes. Workers can then target hosts defined here.

## Host Variables

Host-specific variables can be defined:
- Inline in the inventory file
- In `host_vars/<hostname>.yml` files
- Via the managed inventory web interface

## Group Variables

Group variables can be defined in `group_vars/<groupname>.yml` files.

## Example Files

- `hosts` - Main inventory file
- `hosts.example` - Example inventory with comments
- `hosts.sample` - Minimal sample inventory
