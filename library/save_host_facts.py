#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Ansible module: save_host_facts

Saves collected facts from playbooks to the Ansible Simpleweb storage backend.
This enables automatic CMDB population from inventory playbooks.

Usage in playbook:
    - name: Save hardware inventory to CMDB
      save_host_facts:
        collection: hardware
        data: "{{ collected_hardware_facts }}"
        groups: "{{ group_names }}"

    - name: Save software inventory
      save_host_facts:
        collection: software
        data:
          packages: "{{ ansible_facts.packages }}"
          services: "{{ service_facts }}"
"""

from ansible.module_utils.basic import AnsibleModule
import json
import os
import sys

# Add the web directory to path for storage imports
WEB_DIR = '/app/web'
if WEB_DIR not in sys.path:
    sys.path.insert(0, WEB_DIR)


def get_storage_backend():
    """Get the configured storage backend."""
    try:
        from storage import get_storage_backend as _get_storage
        return _get_storage()
    except ImportError as e:
        return None


def main():
    module = AnsibleModule(
        argument_spec=dict(
            collection=dict(type='str', required=True),
            data=dict(type='dict', required=True),
            groups=dict(type='list', elements='str', default=[]),
            host=dict(type='str', default=None),  # Override host if needed
        ),
        supports_check_mode=True
    )

    collection = module.params['collection']
    data = module.params['data']
    groups = module.params['groups']
    host = module.params['host']

    # Use inventory_hostname if host not specified
    if not host:
        host = module.params.get('ansible_host') or os.environ.get('ANSIBLE_HOST', 'unknown')

    # Get storage backend
    storage = get_storage_backend()
    if not storage:
        module.fail_json(
            msg="Could not initialize storage backend. Make sure the Ansible Simpleweb storage module is available.",
            changed=False
        )

    # Check mode - don't actually save
    if module.check_mode:
        module.exit_json(
            changed=True,
            msg=f"Would save {collection} facts for {host}",
            host=host,
            collection=collection
        )

    # Save the facts
    try:
        result = storage.save_host_facts(
            host=host,
            collection=collection,
            data=data,
            groups=groups,
            source='playbook'
        )

        if result.get('status') == 'error':
            module.fail_json(
                msg=f"Error saving facts: {result.get('error', 'Unknown error')}",
                changed=False,
                result=result
            )

        changed = result.get('status') in ('created', 'updated')
        module.exit_json(
            changed=changed,
            msg=f"Host facts {result.get('status')} for {host}/{collection}",
            result=result
        )

    except Exception as e:
        module.fail_json(
            msg=f"Exception saving host facts: {str(e)}",
            changed=False
        )


if __name__ == '__main__':
    main()
