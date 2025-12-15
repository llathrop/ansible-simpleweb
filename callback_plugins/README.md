# Callback Plugins

This directory contains Ansible callback plugins that hook into playbook execution events.

## Active Plugins

### cmdb_collector

Automatically collects task results and facts during playbook execution and stores them in the CMDB.

**Features:**
- Captures facts from `setup` and `gather_facts` tasks
- Records task results for inventory playbooks
- Maintains change history with diff tracking
- Works with both flatfile and MongoDB backends

**Triggered by playbooks matching:**
- `*-inventory` (hardware-inventory, software-inventory, etc.)
- `system-health`

## Creating Callback Plugins

1. Create a Python file inheriting from `CallbackBase`
2. Implement desired callback methods (`v2_runner_on_ok`, etc.)
3. Set `CALLBACK_VERSION` and `CALLBACK_TYPE`

**Example structure:**
```python
from ansible.plugins.callback import CallbackBase

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'my_plugin'

    def v2_runner_on_ok(self, result):
        # Handle successful task
        pass
```

## Callback Types

- `stdout` - Output formatting (only one active)
- `notification` - Side effects (multiple can be active)
- `aggregate` - Data collection

## Cluster Sync

Callback plugins are synced to worker nodes to ensure consistent behavior across the cluster.

See: https://docs.ansible.com/ansible/latest/plugins/callback.html
