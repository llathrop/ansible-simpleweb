"""
Ansible Callback Plugin: cmdb_collector

Automatically captures playbook results and stores them in the CMDB.
This provides automatic data collection when playbooks don't explicitly
use the save_host_facts module.

Enable in ansible.cfg:
    [defaults]
    callback_plugins = ./callback_plugins
    callbacks_enabled = cmdb_collector

Environment variables:
    CMDB_COLLECTOR_ENABLED=true    Enable/disable collection (default: true)
    CMDB_COLLECTOR_PLAYBOOKS=*     Comma-separated playbook patterns to collect (default: *-inventory)
"""

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = '''
    name: cmdb_collector
    type: notification
    short_description: Collects playbook results into CMDB
    description:
        - Automatically stores gathered facts and task results in the CMDB storage backend
        - Works with hardware-inventory, software-inventory, and similar playbooks
    requirements:
        - Ansible Simpleweb storage module
'''

import os
import sys
import re
from datetime import datetime

from ansible.plugins.callback import CallbackBase

# Add web directory to path
WEB_DIR = '/app/web'
if WEB_DIR not in sys.path:
    sys.path.insert(0, WEB_DIR)


class CallbackModule(CallbackBase):
    """
    Callback plugin to collect playbook results into CMDB.
    """

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'cmdb_collector'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self, *args, **kwargs):
        super(CallbackModule, self).__init__(*args, **kwargs)

        # Configuration
        self.enabled = os.environ.get('CMDB_COLLECTOR_ENABLED', 'true').lower() == 'true'
        self.playbook_patterns = os.environ.get('CMDB_COLLECTOR_PLAYBOOKS', '*-inventory,system-health').split(',')

        # State tracking
        self.current_playbook = None
        self.current_play = None
        self.host_results = {}  # {host: {task_name: result}}
        self.host_facts = {}    # {host: ansible_facts}
        self.storage = None

        # Try to initialize storage
        self._init_storage()

    def _init_storage(self):
        """Initialize storage backend."""
        if not self.enabled:
            return

        try:
            from storage import get_storage_backend
            self.storage = get_storage_backend()
            self._display.v("CMDB Collector: Storage backend initialized")
        except ImportError as e:
            self._display.warning(f"CMDB Collector: Could not import storage module: {e}")
            self.storage = None
        except Exception as e:
            self._display.warning(f"CMDB Collector: Storage initialization failed: {e}")
            self.storage = None

    def _should_collect(self, playbook_name):
        """Check if this playbook should be collected."""
        if not self.enabled or not self.storage:
            return False

        for pattern in self.playbook_patterns:
            pattern = pattern.strip()
            if pattern == '*':
                return True
            # Convert glob to regex
            regex = pattern.replace('*', '.*')
            if re.match(regex, playbook_name, re.IGNORECASE):
                return True

        return False

    def _get_collection_name(self, playbook_name):
        """Derive collection name from playbook name."""
        # Remove common suffixes
        name = playbook_name.replace('.yml', '').replace('.yaml', '')

        # Map common playbook names to collection names
        mappings = {
            'hardware-inventory': 'hardware',
            'software-inventory': 'software',
            'system-health': 'health',
            'network-config': 'network',
            'service-status': 'services',
        }

        return mappings.get(name, name)

    def v2_playbook_on_start(self, playbook):
        """Called when playbook starts."""
        self.current_playbook = os.path.basename(playbook._file_name)
        self.host_results = {}
        self.host_facts = {}

        if self._should_collect(self.current_playbook):
            self._display.v(f"CMDB Collector: Will collect results from {self.current_playbook}")

    def v2_playbook_on_play_start(self, play):
        """Called when a play starts."""
        self.current_play = play.get_name()

    def v2_runner_on_ok(self, result):
        """Called when a task succeeds."""
        if not self._should_collect(self.current_playbook or ''):
            return

        host = result._host.get_name()
        task_name = result._task.get_name()
        task_result = result._result

        # Initialize host tracking
        if host not in self.host_results:
            self.host_results[host] = {}

        # Capture gathered facts
        if 'ansible_facts' in task_result:
            if host not in self.host_facts:
                self.host_facts[host] = {}
            self.host_facts[host].update(task_result['ansible_facts'])

        # Capture task results (excluding internal ansible data)
        cleaned_result = {k: v for k, v in task_result.items()
                         if not k.startswith('_') and k not in ('changed', 'failed', 'skipped')}

        if cleaned_result:
            self.host_results[host][task_name] = cleaned_result

    def v2_playbook_on_stats(self, stats):
        """Called at the end of playbook - save collected data."""
        if not self._should_collect(self.current_playbook or ''):
            return

        if not self.storage:
            self._display.warning("CMDB Collector: No storage backend, skipping save")
            return

        collection_name = self._get_collection_name(self.current_playbook or 'unknown')

        for host in set(list(self.host_results.keys()) + list(self.host_facts.keys())):
            # Combine facts and task results
            data = {}

            # Add ansible facts if gathered
            if host in self.host_facts:
                data['ansible_facts'] = self.host_facts[host]

            # Add task results
            if host in self.host_results:
                data['task_results'] = self.host_results[host]

            # Add metadata
            data['_meta'] = {
                'playbook': self.current_playbook,
                'collected_at': datetime.now().isoformat(),
                'collector': 'callback_plugin'
            }

            if not data.get('ansible_facts') and not data.get('task_results'):
                continue

            try:
                # Get host groups from stats if available
                groups = []

                result = self.storage.save_host_facts(
                    host=host,
                    collection=collection_name,
                    data=data,
                    groups=groups,
                    source='callback'
                )

                status = result.get('status', 'unknown')
                if status == 'unchanged':
                    self._display.v(f"CMDB Collector: {host}/{collection_name} unchanged")
                else:
                    self._display.display(
                        f"CMDB Collector: Saved {collection_name} for {host} ({status})",
                        color='green'
                    )

            except Exception as e:
                self._display.warning(f"CMDB Collector: Error saving {host}: {e}")

        # Clear state
        self.host_results = {}
        self.host_facts = {}
