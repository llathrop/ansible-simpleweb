"""
Inventory Sync - Keep DB and static inventory in sync.

Ensures hosts in the database are written to static inventory (so workers
receive them via content sync), and hosts in static inventory files are
added to the database. Both directions can be scanned at intervals for
missing hosts.

Architecture:
- DB hosts are written to inventory/managed_hosts.ini (auto-generated)
- Static hosts (from hosts, routers, etc.) are added to DB if missing
- Workers sync inventory/ directory, so they get all hosts including DB-backed
"""

import os
import re
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

# File written by sync_db_to_static; excluded from static-to-DB scan
MANAGED_HOSTS_FILE = 'managed_hosts.ini'

# Extensions to skip when parsing static inventory
SKIP_EXTENSIONS = ('.example', '.sample', '.md', '.txt')


def _parse_ini_hosts(inventory_dir: str, exclude_files: Optional[set] = None) -> Dict[str, Dict]:
    """
    Parse INI inventory files and return {hostname: {group, variables}}.

    Args:
        inventory_dir: Path to inventory directory
        exclude_files: Set of basenames to skip (e.g. managed_hosts.ini)

    Returns:
        Dict mapping hostname to {group, variables}
    """
    exclude = exclude_files or set()
    hosts = {}

    if not os.path.isdir(inventory_dir):
        return hosts

    for name in os.listdir(inventory_dir):
        path = os.path.join(inventory_dir, name)
        if os.path.isdir(path):
            continue
        if any(name.endswith(ext) for ext in SKIP_EXTENSIONS):
            continue
        if name in exclude:
            continue
        if not (name.endswith('.ini') or '.' not in name):
            continue

        try:
            with open(path, 'r') as f:
                current_group = None
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if line.startswith('[') and line.endswith(']'):
                        group_name = line[1:-1]
                        if ':children' not in group_name:
                            current_group = group_name
                        continue
                    if current_group and not line.startswith('['):
                        parts = line.split(None, 1)
                        hostname = parts[0] if parts else ''
                        if hostname and not hostname.startswith('#'):
                            variables = {}
                            if len(parts) > 1:
                                for match in re.finditer(r'(\w+)=([^\s]+|"[^"]*")', parts[1]):
                                    k, v = match.group(1), match.group(2)
                                    if v.startswith('"') and v.endswith('"'):
                                        v = v[1:-1]
                                    variables[k] = v
                            hosts[hostname] = {'group': current_group, 'variables': variables}
        except Exception as e:
            print(f"Error parsing inventory file {path}: {e}")

    return hosts


def sync_db_to_static(
    storage_backend,
    inventory_dir: str,
    content_repo_commit: Optional[Callable[[str], None]] = None
) -> Tuple[int, Optional[str]]:
    """
    Write DB inventory hosts to inventory/managed_hosts.ini.

    Overwrites the file with all hosts from the database so workers
    receive them via content sync.

    Args:
        storage_backend: Storage backend with get_all_inventory()
        inventory_dir: Path to inventory directory (e.g. /app/inventory)
        content_repo_commit: Optional callback to commit content repo after write

    Returns:
        Tuple of (hosts_written, error_message)
    """
    if not storage_backend:
        return 0, "Storage backend not initialized"

    try:
        managed = storage_backend.get_all_inventory()
        if not managed:
            # Write empty file so old hosts are removed
            managed = []

        lines = [
            "# Auto-generated from database - do not edit manually",
            "# Managed hosts are synced here so workers receive them.",
            "# Edit hosts via the Inventory page in the web UI.",
            ""
        ]

        # Group by group name
        by_group: Dict[str, List[Dict]] = {}
        for item in managed:
            hostname = item.get('hostname')
            if not hostname:
                continue
            group = item.get('group', 'managed')
            variables = item.get('variables', {})
            if group not in by_group:
                by_group[group] = []
            by_group[group].append({'hostname': hostname, 'variables': variables})

        for group in sorted(by_group.keys()):
            lines.append(f"[{group}]")
            for entry in by_group[group]:
                hostname = entry['hostname']
                variables = entry['variables']
                var_parts = []
                for k, v in (variables or {}).items():
                    if isinstance(v, str) and ' ' in v:
                        var_parts.append(f'{k}="{v}"')
                    else:
                        var_parts.append(f'{k}={v}')
                host_line = hostname + (' ' + ' '.join(var_parts) if var_parts else '')
                lines.append(host_line)
            lines.append("")

        out_path = os.path.join(inventory_dir, MANAGED_HOSTS_FILE)
        os.makedirs(inventory_dir, exist_ok=True)
        with open(out_path, 'w') as f:
            f.write('\n'.join(lines))

        if content_repo_commit:
            try:
                content_repo_commit("Inventory sync: update managed_hosts.ini")
            except Exception as e:
                print(f"Inventory sync: content repo commit failed: {e}")

        return len(managed), None
    except Exception as e:
        return 0, str(e)


def sync_static_to_db(
    storage_backend,
    inventory_dir: str
) -> Tuple[int, Optional[str]]:
    """
    Add hosts from static inventory files to DB if missing.

    Parses INI files (excluding managed_hosts.ini) and adds any host
    not already in the database.

    Args:
        storage_backend: Storage backend with get_all_inventory, save_inventory_item
        inventory_dir: Path to inventory directory

    Returns:
        Tuple of (hosts_added, error_message)
    """
    if not storage_backend:
        return 0, "Storage backend not initialized"

    try:
        static_hosts = _parse_ini_hosts(inventory_dir, exclude_files={MANAGED_HOSTS_FILE})
        if not static_hosts:
            return 0, None

        db_hosts = {item.get('hostname') for item in storage_backend.get_all_inventory() if item.get('hostname')}
        added = 0

        for hostname, data in static_hosts.items():
            if hostname in db_hosts:
                continue
            item_id = str(uuid.uuid4())
            now = datetime.now().isoformat()
            item = {
                'id': item_id,
                'hostname': hostname,
                'display_name': hostname,
                'group': data.get('group', 'ungrouped'),
                'description': f'Auto-added from static inventory',
                'variables': data.get('variables', {}),
                'created': now,
                'updated': now
            }
            if storage_backend.save_inventory_item(item_id, item):
                added += 1
                db_hosts.add(hostname)

        return added, None
    except Exception as e:
        return 0, str(e)


def run_inventory_sync(
    storage_backend,
    inventory_dir: str,
    content_repo_commit: Optional[Callable[[str], None]] = None
) -> Dict[str, any]:
    """
    Run full inventory sync: DB to static, then static to DB.

    Args:
        storage_backend: Storage backend
        inventory_dir: Path to inventory directory
        content_repo_commit: Optional callback to commit content repo

    Returns:
        Dict with db_to_static, static_to_db, error
    """
    result = {'db_to_static': 0, 'static_to_db': 0, 'error': None}

    # 1. DB -> static (so workers get DB hosts)
    n, err = sync_db_to_static(storage_backend, inventory_dir, content_repo_commit)
    result['db_to_static'] = n
    if err:
        result['error'] = f"db_to_static: {err}"
        return result

    # 2. Static -> DB (so DB has all static hosts)
    n, err = sync_static_to_db(storage_backend, inventory_dir)
    result['static_to_db'] = n
    if err:
        result['error'] = (result['error'] or '') + f" static_to_db: {err}"
        return result

    # If we added hosts from static, re-run db_to_static to include them in file
    if result['static_to_db'] > 0:
        n, err = sync_db_to_static(storage_backend, inventory_dir, content_repo_commit)
        result['db_to_static'] = n
        if err:
            result['error'] = (result['error'] or '') + f" db_to_static (retry): {err}"

    return result
