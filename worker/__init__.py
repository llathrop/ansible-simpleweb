"""
Ansible SimpleWeb Worker Service

A standalone service that runs on worker nodes to:
- Register with the primary server
- Sync Ansible content (playbooks, inventory, etc.)
- Execute assigned jobs
- Report status via periodic check-ins
"""

__version__ = '1.0.0'
