# Custom Ansible Modules

This directory contains custom Ansible modules that extend Ansible's functionality.

## Using Custom Modules

Modules in this directory are automatically available to playbooks. Use them like built-in modules:

```yaml
- name: Save host facts to CMDB
  save_host_facts:
    collection: hardware
    data: "{{ ansible_facts }}"
```

## Included Modules

### save_host_facts

Saves collected facts to the CMDB storage backend.

**Parameters:**
- `collection` (required): Name of the data collection (e.g., 'hardware', 'software')
- `data` (required): Dictionary of data to save
- `host` (optional): Override hostname (defaults to inventory_hostname)

**Example:**
```yaml
- name: Save custom metrics
  save_host_facts:
    collection: metrics
    data:
      cpu_usage: "{{ cpu_percent }}"
      memory_free: "{{ mem_free_mb }}"
```

## Creating Custom Modules

1. Create a Python file in this directory
2. Follow Ansible module development guidelines
3. Module will be available immediately (no restart needed)

See: https://docs.ansible.com/ansible/latest/dev_guide/developing_modules.html

## Cluster Sync

Custom modules are synced to worker nodes, ensuring consistent functionality across the cluster.
