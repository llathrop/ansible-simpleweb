from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
import requests
import os
import re
import glob
import json
import subprocess
import threading
import time
import uuid
import tempfile
from datetime import datetime

# Redact password-like values in log lines (Ansible may echo vars)
_LOG_SENSITIVE_PATTERN = re.compile(
    r'((?:ansible_ssh_pass|ansible_password|ansible_become_pass)\s*["\']?\s*[:=]\s*)(["\']?)[^"\'&\s\n]+(["\']?)',
    re.IGNORECASE
)

def _sanitize_log_line(line: str) -> str:
    """Redact sensitive variable values from a log line."""
    return _LOG_SENSITIVE_PATTERN.sub(r'\1*****', line)

# Import scheduler components (initialized after app creation)
from scheduler import ScheduleManager, build_recurrence_config

# Import storage backend
from storage import get_storage_backend

# Import content repository manager (for cluster sync)
from content_repo import ContentRepository, get_content_repo
from inventory_sync import run_inventory_sync

# Import auth module and routes
from auth_routes import (
    auth_bp,
    init_auth_middleware,
    bootstrap_admin_user,
    get_current_user,
    login_required,
    admin_required,
    worker_auth_required,
    service_auth_required,
    require_permission,
    require_any_permission
)

# Authentication settings
AUTH_ENABLED = os.environ.get('AUTH_ENABLED', 'false').lower() == 'true'

app = Flask(__name__)


def _run_inventory_sync():
    """Run inventory sync (DB <-> static). Called on inventory changes and periodically."""
    if not storage_backend:
        return
    def commit_fn(msg):
        repo = get_content_repo(CONTENT_DIR)
        if repo and repo.is_initialized():
            repo.commit_changes(msg)
    try:
        result = run_inventory_sync(storage_backend, INVENTORY_DIR, commit_fn)
        if result.get('error'):
            print(f"Inventory sync warning: {result['error']}")
    except Exception as e:
        print(f"Inventory sync error: {e}")
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ansible-simpleweb-dev-key')


@app.context_processor
def inject_nav_context():
    """Inject navigation context into all templates (nav_sections, active_section_id, active_page_url, current_user)."""
    try:
        from nav import get_nav_context
        from flask import g
        user = getattr(g, 'current_user', None)
        return get_nav_context(request.path, user)
    except Exception:
        return {'nav_sections': [], 'active_section_id': None, 'active_page_url': None, 'current_user': None}


# Initialize SocketIO with eventlet for async support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Paths
PLAYBOOKS_DIR = '/app/playbooks'
LOGS_DIR = '/app/logs'
RUN_SCRIPT = '/app/run-playbook.sh'
INVENTORY_FILE = '/app/inventory/hosts'
INVENTORY_DIR = os.path.dirname(INVENTORY_FILE)
THEMES_DIR = '/app/config/themes'

# Cluster configuration
# CLUSTER_MODE: 'standalone' (default), 'primary', or 'worker'
CLUSTER_MODE = os.environ.get('CLUSTER_MODE', 'standalone')
REGISTRATION_TOKEN = os.environ.get('REGISTRATION_TOKEN', '')
CHECKIN_INTERVAL = int(os.environ.get('CHECKIN_INTERVAL', '600'))  # seconds
LOCAL_WORKER_TAGS = [t.strip() for t in os.environ.get('LOCAL_WORKER_TAGS', 'local').split(',') if t.strip()]
CONTENT_DIR = os.environ.get('CONTENT_DIR', '/app')  # Base dir for syncable content

# Track running playbooks by run_id
# Structure: {run_id: {playbook, target, status, started, log_file, ...}}
active_runs = {}

# Lock for thread-safe access to active_runs
runs_lock = threading.Lock()

# Track active batch jobs by batch_id
# Structure: {batch_id: {playbooks, targets, status, total, completed, failed, ...}}
active_batch_jobs = {}

# Lock for thread-safe access to active_batch_jobs
batch_lock = threading.Lock()

# Schedule manager (initialized in main block)
schedule_manager = None

# Storage backend (initialized in main block)
storage_backend = None

# Content repository (initialized in main block for cluster mode)
content_repo = None

def get_inventory_targets():
    """
    Parse inventory sources and get available hosts and groups.

    Merges hosts from:
    1. Ansible inventory file (inventory/hosts) - INI format
    2. Managed inventory from storage backend - JSON/MongoDB

    Returns combined list for target dropdown.
    """
    targets = []
    seen_hosts = set()  # Track hosts to avoid duplicates
    seen_groups = set()

    # --- Source 1: Ansible INI inventory directory ---
    inventory_dir = os.path.dirname(INVENTORY_FILE)
    if os.path.exists(inventory_dir):
        inventory_files = glob.glob(os.path.join(inventory_dir, '*'))
        for inv_file in inventory_files:
            # Skip non-inventory files
            if inv_file.endswith('.example') or inv_file.endswith('.sample') or inv_file.endswith('.md'):
                continue
            if os.path.isdir(inv_file):
                continue

            try:
                with open(inv_file, 'r') as f:
                    current_group = None
                    for line in f:
                        line = line.strip()

                        # Skip empty lines and comments
                        if not line or line.startswith('#'):
                            continue

                        # Group header [groupname]
                        if line.startswith('[') and line.endswith(']'):
                            group_name = line[1:-1]
                            # Skip :children groups for now, just track regular groups
                            if ':children' not in group_name and group_name not in seen_groups:
                                current_group = group_name
                                seen_groups.add(group_name)
                                targets.append({
                                    'value': group_name,
                                    'label': f'{group_name} (group)',
                                    'type': 'group'
                                })
                        # Individual host line
                        elif current_group and not line.startswith('['):
                            # Extract hostname (first part before space)
                            hostname = line.split()[0]
                            if hostname and not hostname.startswith('#') and hostname not in seen_hosts:
                                seen_hosts.add(hostname)
                                targets.append({
                                    'value': hostname,
                                    'label': f'{hostname}',
                                    'type': 'host'
                                })
            except Exception as e:
                print(f"Error parsing INI inventory file {inv_file}: {e}")

    # --- Source 2: Managed inventory from storage backend ---
    try:
        if storage_backend:
            managed_inventory = storage_backend.get_all_inventory()
            for item in managed_inventory:
                hostname = item.get('hostname')
                group = item.get('group', 'managed')
                display_name = item.get('display_name', hostname)

                # Add group if new
                if group and group not in seen_groups:
                    seen_groups.add(group)
                    targets.append({
                        'value': group,
                        'label': f'{group} (managed group)',
                        'type': 'group'
                    })

                # Add host if new
                if hostname and hostname not in seen_hosts:
                    seen_hosts.add(hostname)
                    label = f'{hostname}' if hostname == display_name else f'{hostname} ({display_name})'
                    targets.append({
                        'value': hostname,
                        'label': f'{label} [managed]',
                        'type': 'managed_host',
                        'item_id': item.get('id'),
                        'variables': item.get('variables', {})
                    })
    except Exception as e:
        print(f"Error loading managed inventory: {e}")

    # Add special targets
    if targets:
        targets.insert(0, {
            'value': 'all',
            'label': 'all (all hosts)',
            'type': 'special'
        })

    # Fallback if no targets found
    if not targets:
        return [{'value': 'host_machine', 'label': 'host_machine (group)', 'type': 'group'}]

    return targets if targets else [{'value': 'host_machine', 'label': 'host_machine (group)', 'type': 'group'}]


def generate_managed_inventory(hostname):
    """
    Generate a temporary Ansible inventory file for a managed host.

    Looks up the host in the managed inventory storage and creates
    a temporary INI-format inventory file with all its variables.

    Args:
        hostname: The hostname/IP to look up

    Returns:
        Path to temporary inventory file, or None if host not found
    """
    if not storage_backend:
        return None

    # Find the managed host by hostname
    managed_inventory = storage_backend.get_all_inventory()
    host_item = None
    for item in managed_inventory:
        if item.get('hostname') == hostname:
            host_item = item
            break

    if not host_item:
        return None

    # Build inventory content
    group = host_item.get('group', 'managed')
    variables = host_item.get('variables', {})

    # Format: hostname var1=val1 var2=val2
    var_parts = []
    for key, value in variables.items():
        # Quote string values, leave others as-is
        if isinstance(value, str) and ' ' in value:
            var_parts.append(f'{key}="{value}"')
        else:
            var_parts.append(f'{key}={value}')

    host_line = hostname
    if var_parts:
        host_line += ' ' + ' '.join(var_parts)

    inventory_content = f"""# Temporary inventory for managed host
# Generated by ansible-simpleweb

[{group}]
{host_line}
"""

    # Write to temporary file (won't be deleted automatically - caller must clean up)
    fd, temp_path = tempfile.mkstemp(prefix='managed_inv_', suffix='.ini', dir='/tmp')
    try:
        os.write(fd, inventory_content.encode('utf-8'))
    finally:
        os.close(fd)

    return temp_path


def generate_batch_inventory(targets):
    """
    Generate a temporary Ansible inventory file for batch execution.

    Creates a combined inventory containing all selected hosts and groups,
    merging hosts from both the INI inventory file and managed inventory.

    Args:
        targets: List of target names (hostnames, group names, or 'all')

    Returns:
        Tuple of (temp_inventory_path, hosts_included, error_message)
        - temp_inventory_path: Path to temporary inventory file, or None on error
        - hosts_included: List of hostnames that will be targeted
        - error_message: Error description if failed, None on success
    """
    if not targets:
        return None, [], "No targets specified"

    # Special case: 'all' means use the default inventory
    if 'all' in targets:
        return None, ['all'], None  # None path means use default inventory

    # Collect hosts and their variables
    # Structure: {hostname: {'group': str, 'variables': dict, 'source': 'ini'|'managed'}}
    hosts_data = {}
    groups_to_include = set()

    # Parse the INI inventory files to get hosts and groups
    ini_hosts = {}  # {hostname: {'groups': [list], 'variables': {}}}
    ini_groups = {}  # {groupname: [list of hostnames]}

    inventory_dir = os.path.dirname(INVENTORY_FILE)
    if os.path.exists(inventory_dir):
        inventory_files = glob.glob(os.path.join(inventory_dir, '*'))
        for inv_file in inventory_files:
            # Skip non-inventory files
            if inv_file.endswith('.example') or inv_file.endswith('.sample') or inv_file.endswith('.md'):
                continue
            if os.path.isdir(inv_file):
                continue
            
            try:
                with open(inv_file, 'r') as f:
                    current_group = None
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue

                        if line.startswith('[') and line.endswith(']'):
                            group_name = line[1:-1]
                            if ':children' not in group_name:
                                current_group = group_name
                                if current_group not in ini_groups:
                                    ini_groups[current_group] = []
                        elif current_group and not line.startswith('['):
                            parts = line.split()
                            if parts:
                                hostname = parts[0]
                                # Parse variables from the line
                                variables = {}
                                for part in parts[1:]:
                                    if '=' in part:
                                        key, value = part.split('=', 1)
                                        # Remove quotes if present
                                        value = value.strip('"\'')
                                        variables[key] = value

                                if hostname not in ini_hosts:
                                    ini_hosts[hostname] = {'groups': [], 'variables': variables}
                                if current_group not in ini_hosts[hostname]['groups']:
                                    ini_hosts[hostname]['groups'].append(current_group)

                                if hostname not in ini_groups[current_group]:
                                    ini_groups[current_group].append(hostname)
            except Exception as e:
                print(f"Error parsing INI inventory file {inv_file}: {e}")

    # Get managed inventory
    managed_hosts = {}
    if storage_backend:
        managed_inventory = storage_backend.get_all_inventory()
        for item in managed_inventory:
            hostname = item.get('hostname')
            if hostname:
                managed_hosts[hostname] = {
                    'group': item.get('group', 'managed'),
                    'variables': item.get('variables', {})
                }

    # Process each target
    for target in targets:
        # Check if target is a group in INI inventory
        if target in ini_groups:
            groups_to_include.add(target)
            for hostname in ini_groups[target]:
                if hostname not in hosts_data:
                    hosts_data[hostname] = {
                        'groups': ini_hosts.get(hostname, {}).get('groups', [target]),
                        'variables': ini_hosts.get(hostname, {}).get('variables', {}),
                        'source': 'ini'
                    }

        # Check if target is a group in managed inventory
        elif storage_backend:
            managed_in_group = [h for h, data in managed_hosts.items() if data.get('group') == target]
            if managed_in_group:
                groups_to_include.add(target)
                for hostname in managed_in_group:
                    if hostname not in hosts_data:
                        hosts_data[hostname] = {
                            'groups': [managed_hosts[hostname]['group']],
                            'variables': managed_hosts[hostname]['variables'],
                            'source': 'managed'
                        }
                continue

        # Check if target is an individual host in INI
        if target in ini_hosts:
            if target not in hosts_data:
                hosts_data[target] = {
                    'groups': ini_hosts[target]['groups'],
                    'variables': ini_hosts[target]['variables'],
                    'source': 'ini'
                }

        # Check if target is a managed host
        elif target in managed_hosts:
            if target not in hosts_data:
                hosts_data[target] = {
                    'groups': [managed_hosts[target]['group']],
                    'variables': managed_hosts[target]['variables'],
                    'source': 'managed'
                }

    if not hosts_data:
        return None, [], f"No hosts found for targets: {targets}"

    # Build inventory content organized by group
    inventory_lines = [
        "# Temporary batch inventory",
        "# Generated by ansible-simpleweb",
        ""
    ]

    # Organize hosts by their primary group
    groups_with_hosts = {}
    for hostname, data in hosts_data.items():
        # Use first group as primary
        primary_group = data['groups'][0] if data['groups'] else 'batch_targets'
        if primary_group not in groups_with_hosts:
            groups_with_hosts[primary_group] = []

        # Format host line with variables
        var_parts = []
        for key, value in data['variables'].items():
            if isinstance(value, str) and ' ' in value:
                var_parts.append(f'{key}="{value}"')
            else:
                var_parts.append(f'{key}={value}')

        host_line = hostname
        if var_parts:
            host_line += ' ' + ' '.join(var_parts)

        groups_with_hosts[primary_group].append(host_line)

    # Write groups and hosts
    for group_name, host_lines in sorted(groups_with_hosts.items()):
        inventory_lines.append(f"[{group_name}]")
        for host_line in sorted(host_lines):
            inventory_lines.append(host_line)
        inventory_lines.append("")

    inventory_content = '\n'.join(inventory_lines)

    # Write to temporary file
    fd, temp_path = tempfile.mkstemp(prefix='batch_inv_', suffix='.ini', dir='/tmp')
    try:
        os.write(fd, inventory_content.encode('utf-8'))
    finally:
        os.close(fd)

    return temp_path, list(hosts_data.keys()), None


def is_managed_host(hostname):
    """
    Check if a hostname is in the managed inventory.

    Args:
        hostname: The hostname/IP to check

    Returns:
        True if the host is managed, False otherwise
    """
    if not storage_backend:
        return False

    managed_inventory = storage_backend.get_all_inventory()
    for item in managed_inventory:
        if item.get('hostname') == hostname:
            return True
    return False


def get_playbooks():
    """Get list of available playbooks"""
    playbooks = []
    if os.path.exists(PLAYBOOKS_DIR):
        for file in sorted(glob.glob(f'{PLAYBOOKS_DIR}/*.yml')):
            playbook_name = os.path.basename(file).replace('.yml', '')
            playbooks.append(playbook_name)
    return playbooks

def get_latest_log(playbook_name):
    """Get the most recent log file for a playbook"""
    pattern = f'{LOGS_DIR}/{playbook_name}-*.log'
    log_files = glob.glob(pattern)
    if log_files:
        # Sort by modification time, most recent first
        log_files.sort(key=os.path.getmtime, reverse=True)
        return os.path.basename(log_files[0])
    return None

def get_log_timestamp(log_file):
    """Get timestamp from log file"""
    if log_file and os.path.exists(f'{LOGS_DIR}/{log_file}'):
        mtime = os.path.getmtime(f'{LOGS_DIR}/{log_file}')
        return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
    return 'Never'

def is_playbook_target_running(playbook_name, target):
    """Check if a specific playbook+target combination is already running"""
    with runs_lock:
        for run_id, run_info in active_runs.items():
            if (run_info['playbook'] == playbook_name and
                run_info['target'] == target and
                run_info['status'] in ['running', 'starting']):
                return True, run_id
    return False, None

def get_running_playbooks():
    """Get dict of currently running playbooks for backward compatibility"""
    with runs_lock:
        running = {}
        for run_id, run_info in active_runs.items():
            if run_info['status'] in ['running', 'starting']:
                running[run_info['playbook']] = {
                    'status': 'running',
                    'run_id': run_id,
                    'target': run_info['target']
                }
        return running

def get_playbook_status(playbook_name):
    """Get status for a playbook (returns most recent active run or 'ready')"""
    with runs_lock:
        # Check for running/starting first (active states)
        for run_id, run_info in active_runs.items():
            if run_info['playbook'] == playbook_name and run_info['status'] in ['running', 'starting']:
                return 'running', run_id  # Normalize 'starting' to 'running' for display
        # Then check for recently completed
        for run_id, run_info in active_runs.items():
            if run_info['playbook'] == playbook_name and run_info['status'] in ['completed', 'failed']:
                return run_info['status'], run_id
    return 'ready', None

def get_active_runs_for_playbook(playbook_name):
    """Get all active runs for a specific playbook"""
    with runs_lock:
        return [
            {'run_id': run_id, **run_info}
            for run_id, run_info in active_runs.items()
            if run_info['playbook'] == playbook_name
        ]

def generate_log_filename(playbook_name, target, run_id):
    """Generate a unique log filename"""
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    # Sanitize target for filename (replace special chars)
    safe_target = target.replace('/', '-').replace(':', '-')
    short_id = run_id[:8]
    return f"{playbook_name}-{safe_target}-{timestamp}-{short_id}.log"

def run_playbook_streaming(run_id, playbook_name, target, log_file, inventory_path=None):
    """
    Run playbook with real-time streaming to WebSocket and log file.

    Args:
        run_id: Unique run identifier
        playbook_name: Name of the playbook to run
        target: Target host/group to limit playbook execution
        log_file: Filename for the log file
        inventory_path: Optional path to custom inventory file (for managed hosts)
    """
    log_path = os.path.join(LOGS_DIR, log_file)

    # Get worker info from active_runs (before try block for exception handling)
    with runs_lock:
        worker_name = active_runs.get(run_id, {}).get('worker_name', 'local-executor')

    try:
        # Update status to running
        with runs_lock:
            active_runs[run_id]['status'] = 'running'

        # Notify clients that playbook started
        socketio.emit('playbook_started', {
            'run_id': run_id,
            'playbook': playbook_name,
            'target': target,
            'log_file': log_file
        }, room=f'run:{run_id}')

        # Also broadcast to the main status room
        socketio.emit('status_update', {
            'run_id': run_id,
            'playbook': playbook_name,
            'target': target,
            'status': 'running',
            'worker_name': worker_name
        }, room='status')

        # Build command with optional custom inventory
        cmd = ['bash', RUN_SCRIPT, '--stream', playbook_name]
        if inventory_path:
            cmd.extend(['-i', inventory_path])
        cmd.extend(['-l', target])
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
            cwd='/app'
        )

        # Store process reference for potential cancellation
        with runs_lock:
            active_runs[run_id]['process'] = process

        # Open log file for writing
        with open(log_path, 'w', buffering=1) as log_f:  # Line buffered
            # Write header with worker info
            header = f"=== Playbook: {playbook_name} | Target: {target} | Worker: {worker_name} | Started: {datetime.now().isoformat()} ===\n"
            log_f.write(header)
            log_f.flush()
            socketio.emit('log_line', {'line': header, 'run_id': run_id}, room=f'run:{run_id}')

            # Stream output line by line (sanitize to avoid passwords in logs)
            for line in process.stdout:
                safe_line = _sanitize_log_line(line)
                # Write to file first (crash protection)
                log_f.write(safe_line)
                log_f.flush()
                os.fsync(log_f.fileno())  # Force OS to write to disk

                # Then emit to WebSocket
                socketio.emit('log_line', {'line': safe_line, 'run_id': run_id}, room=f'run:{run_id}')

            # Wait for process to complete
            process.wait()
            exit_code = process.returncode

            # Write footer
            status = 'completed' if exit_code == 0 else 'failed'
            footer = f"\n=== Finished: {datetime.now().isoformat()} | Exit Code: {exit_code} | Status: {status.upper()} ===\n"
            log_f.write(footer)
            log_f.flush()
            os.fsync(log_f.fileno())
            socketio.emit('log_line', {'line': footer, 'run_id': run_id}, room=f'run:{run_id}')

        # Update status
        with runs_lock:
            active_runs[run_id]['status'] = status
            active_runs[run_id]['finished'] = datetime.now().isoformat()
            active_runs[run_id]['exit_code'] = exit_code
            if 'process' in active_runs[run_id]:
                del active_runs[run_id]['process']

        # Notify completion
        socketio.emit('playbook_finished', {
            'run_id': run_id,
            'playbook': playbook_name,
            'target': target,
            'status': status,
            'exit_code': exit_code,
            'log_file': log_file
        }, room=f'run:{run_id}')

        socketio.emit('status_update', {
            'run_id': run_id,
            'playbook': playbook_name,
            'target': target,
            'status': status,
            'worker_name': worker_name
        }, room='status')

        # Clean up from active_runs after delay (keep for UI display)
        time.sleep(30)
        with runs_lock:
            if run_id in active_runs:
                del active_runs[run_id]

    except Exception as e:
        error_msg = f"Error: {str(e)}"
        with runs_lock:
            if run_id in active_runs:
                active_runs[run_id]['status'] = 'failed'
                active_runs[run_id]['error'] = str(e)

        socketio.emit('playbook_error', {
            'run_id': run_id,
            'error': str(e)
        }, room=f'run:{run_id}')

        socketio.emit('status_update', {
            'run_id': run_id,
            'playbook': playbook_name,
            'target': target,
            'status': 'failed',
            'worker_name': worker_name
        }, room='status')

    finally:
        # Clean up temporary inventory file if one was created
        if inventory_path and os.path.exists(inventory_path):
            try:
                os.remove(inventory_path)
            except Exception:
                pass  # Ignore cleanup errors


def run_batch_job_streaming(batch_id, playbooks, targets, name=None):
    """
    Execute a batch job - multiple playbooks against multiple targets sequentially.

    Playbooks run in order. Each playbook runs against the combined inventory
    of all targets before the next playbook starts.

    Args:
        batch_id: Unique batch job identifier
        playbooks: List of playbook names in execution order
        targets: List of target hosts/groups
        name: Optional display name for the batch job
    """
    inventory_path = None

    try:
        # Generate combined inventory for all targets
        inventory_path, hosts_included, inv_error = generate_batch_inventory(targets)

        if inv_error and not hosts_included:
            # Fatal error - can't proceed
            with batch_lock:
                if batch_id in active_batch_jobs:
                    active_batch_jobs[batch_id]['status'] = 'failed'
                    active_batch_jobs[batch_id]['error'] = inv_error
                    active_batch_jobs[batch_id]['finished'] = datetime.now().isoformat()

            if storage_backend:
                batch_job = storage_backend.get_batch_job(batch_id)
                if batch_job:
                    batch_job['status'] = 'failed'
                    batch_job['error'] = inv_error
                    batch_job['finished'] = datetime.now().isoformat()
                    storage_backend.save_batch_job(batch_id, batch_job)

            socketio.emit('batch_job_error', {
                'batch_id': batch_id,
                'error': inv_error
            }, room='batch_jobs')
            return

        # Update batch job status to running
        with batch_lock:
            active_batch_jobs[batch_id]['status'] = 'running'
            active_batch_jobs[batch_id]['started'] = datetime.now().isoformat()
            active_batch_jobs[batch_id]['hosts_included'] = hosts_included

        if storage_backend:
            batch_job = storage_backend.get_batch_job(batch_id)
            if batch_job:
                batch_job['status'] = 'running'
                batch_job['started'] = datetime.now().isoformat()
                batch_job['hosts_included'] = hosts_included
                storage_backend.save_batch_job(batch_id, batch_job)

        socketio.emit('batch_job_started', {
            'batch_id': batch_id,
            'playbooks': playbooks,
            'targets': targets,
            'hosts_included': hosts_included,
            'total': len(playbooks)
        }, room='batch_jobs')

        # Execute each playbook sequentially
        completed_count = 0
        failed_count = 0
        results = []

        # Check if we should dispatch to cluster workers
        use_cluster = CLUSTER_MODE == 'primary' and _has_remote_workers()
        current_worker_name = None

        for i, playbook_name in enumerate(playbooks):
            # Check if playbook exists
            if playbook_name not in get_playbooks():
                result = {
                    'playbook': playbook_name,
                    'status': 'failed',
                    'error': 'Playbook not found',
                    'started': datetime.now().isoformat(),
                    'finished': datetime.now().isoformat()
                }
                results.append(result)
                failed_count += 1

                # Update progress
                _update_batch_progress(batch_id, playbook_name, i + 1, len(playbooks),
                                       completed_count, failed_count, results, 'failed')
                continue

            playbook_started = datetime.now().isoformat()

            # Update current playbook in batch job
            with batch_lock:
                if batch_id in active_batch_jobs:
                    active_batch_jobs[batch_id]['current_playbook'] = playbook_name

            if use_cluster:
                # === CLUSTER MODE: Dispatch to worker via job queue ===
                # Submit jobs for each target (or combined if using batch inventory)
                target_str = ','.join(targets) if len(targets) <= 3 else targets[0]

                socketio.emit('batch_job_progress', {
                    'batch_id': batch_id,
                    'current_playbook': playbook_name,
                    'current_index': i + 1,
                    'total': len(playbooks),
                    'completed': completed_count,
                    'failed': failed_count,
                    'status': 'running',
                    'worker_name': current_worker_name
                }, room='batch_jobs')

                # Submit job to cluster queue
                job = _submit_cluster_job(
                    playbook=playbook_name,
                    target=target_str,
                    priority=50,
                    submitted_by=f'batch:{batch_id[:8]}'
                )

                if not job:
                    # Failed to submit - fall back to local execution marker
                    failed_count += 1
                    result = {
                        'playbook': playbook_name,
                        'status': 'failed',
                        'error': 'Failed to submit to cluster queue',
                        'started': playbook_started,
                        'finished': datetime.now().isoformat()
                    }
                    results.append(result)
                    continue

                job_id = job['id']

                # Update batch with current job
                with batch_lock:
                    if batch_id in active_batch_jobs:
                        active_batch_jobs[batch_id]['current_job_id'] = job_id

                # Emit header to batch log
                header = f"=== Batch Job: {batch_id[:8]} | Playbook: {playbook_name} | Targets: {', '.join(targets)} | Cluster Job: {job_id[:8]} | Started: {playbook_started} ===\n"
                socketio.emit('batch_log_line', {
                    'batch_id': batch_id,
                    'playbook': playbook_name,
                    'line': header
                }, room=f'batch:{batch_id}')

                # Wait for job completion with progress updates and log streaming
                import time
                poll_start = time.time()
                last_status = 'queued'
                last_log_pos = 0  # Track how much of partial log we've sent

                while time.time() - poll_start < 600:  # 10 min timeout
                    job_state = storage_backend.get_job(job_id) if storage_backend else None
                    if not job_state:
                        break

                    current_status = job_state.get('status', 'unknown')

                    # Update worker name when job is assigned
                    if job_state.get('assigned_worker') and not current_worker_name:
                        current_worker_name = _get_worker_name(job_state['assigned_worker'])
                        socketio.emit('batch_job_progress', {
                            'batch_id': batch_id,
                            'current_playbook': playbook_name,
                            'worker_name': current_worker_name,
                            'worker_id': job_state['assigned_worker'],
                            'status': 'running'
                        }, room='batch_jobs')

                    # Emit status change
                    if current_status != last_status:
                        socketio.emit('batch_log_line', {
                            'batch_id': batch_id,
                            'playbook': playbook_name,
                            'line': f"[Cluster] Job status: {current_status} (worker: {current_worker_name or 'pending'})\n"
                        }, room=f'batch:{batch_id}')
                        last_status = current_status

                    # Stream partial log content to batch view
                    partial_log_file = job_state.get('partial_log_file')
                    if partial_log_file:
                        partial_log_path = os.path.join(LOGS_DIR, partial_log_file)
                        try:
                            if os.path.exists(partial_log_path):
                                with open(partial_log_path, 'r') as pf:
                                    pf.seek(last_log_pos)
                                    new_content = pf.read()
                                    if new_content:
                                        last_log_pos = pf.tell()
                                        # Emit each line separately for proper display
                                        for line in new_content.splitlines(keepends=True):
                                            socketio.emit('batch_log_line', {
                                                'batch_id': batch_id,
                                                'playbook': playbook_name,
                                                'line': line
                                            }, room=f'batch:{batch_id}')
                        except Exception:
                            pass  # Ignore partial log read errors

                    if current_status in ['completed', 'failed', 'cancelled']:
                        break

                    time.sleep(0.5)  # Poll more frequently for smoother log streaming

                # Get final job state
                final_job = storage_backend.get_job(job_id) if storage_backend else None
                playbook_finished = datetime.now().isoformat()

                if final_job:
                    exit_code = final_job.get('exit_code', -1)
                    playbook_status = 'completed' if exit_code == 0 else 'failed'
                    log_file = final_job.get('log_file')
                    worker_id = final_job.get('assigned_worker')
                    current_worker_name = _get_worker_name(worker_id)

                    if exit_code == 0:
                        completed_count += 1
                    else:
                        failed_count += 1

                    result = {
                        'playbook': playbook_name,
                        'status': playbook_status,
                        'job_id': job_id,
                        'log_file': log_file,
                        'exit_code': exit_code,
                        'started': playbook_started,
                        'finished': playbook_finished,
                        'worker_id': worker_id,
                        'worker_name': current_worker_name
                    }

                    footer = f"\n=== Finished: {playbook_finished} | Exit Code: {exit_code} | Worker: {current_worker_name} | Status: {playbook_status.upper()} ===\n"
                else:
                    failed_count += 1
                    result = {
                        'playbook': playbook_name,
                        'status': 'failed',
                        'error': 'Job timeout or not found',
                        'job_id': job_id,
                        'started': playbook_started,
                        'finished': playbook_finished
                    }
                    footer = f"\n=== Finished: {playbook_finished} | Status: FAILED (timeout) ===\n"

                socketio.emit('batch_log_line', {
                    'batch_id': batch_id,
                    'playbook': playbook_name,
                    'line': footer
                }, room=f'batch:{batch_id}')
                results.append(result)

            else:
                # === LOCAL MODE: Execute directly via subprocess ===
                run_id = str(uuid.uuid4())
                target_label = f"batch-{len(targets)}targets"
                log_file = generate_log_filename(playbook_name, target_label, run_id)
                log_path = os.path.join(LOGS_DIR, log_file)

                with batch_lock:
                    if batch_id in active_batch_jobs:
                        active_batch_jobs[batch_id]['current_run_id'] = run_id

                socketio.emit('batch_job_progress', {
                    'batch_id': batch_id,
                    'current_playbook': playbook_name,
                    'current_index': i + 1,
                    'total': len(playbooks),
                    'completed': completed_count,
                    'failed': failed_count,
                    'status': 'running',
                    'worker_name': 'local-executor'
                }, room='batch_jobs')

                # Build and execute the playbook command
                try:
                    cmd = ['bash', RUN_SCRIPT, '--stream', playbook_name]
                    if inventory_path:
                        cmd.extend(['-i', inventory_path])

                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        cwd='/app'
                    )

                    with open(log_path, 'w', buffering=1) as log_f:
                        header = f"=== Batch Job: {batch_id[:8]} | Playbook: {playbook_name} | Targets: {', '.join(targets)} | Worker: local-executor | Started: {playbook_started} ===\n"
                        log_f.write(header)
                        log_f.flush()

                        socketio.emit('batch_log_line', {
                            'batch_id': batch_id,
                            'playbook': playbook_name,
                            'line': header
                        }, room=f'batch:{batch_id}')

                        for line in process.stdout:
                            safe_line = _sanitize_log_line(line)
                            log_f.write(safe_line)
                            log_f.flush()
                            socketio.emit('batch_log_line', {
                                'batch_id': batch_id,
                                'playbook': playbook_name,
                                'line': safe_line
                            }, room=f'batch:{batch_id}')

                        process.wait()
                        exit_code = process.returncode

                        playbook_status = 'completed' if exit_code == 0 else 'failed'
                        footer = f"\n=== Finished: {datetime.now().isoformat()} | Exit Code: {exit_code} | Worker: local-executor | Status: {playbook_status.upper()} ===\n"
                        log_f.write(footer)
                        log_f.flush()
                        socketio.emit('batch_log_line', {
                            'batch_id': batch_id,
                            'playbook': playbook_name,
                            'line': footer
                        }, room=f'batch:{batch_id}')

                    playbook_finished = datetime.now().isoformat()

                    if exit_code == 0:
                        completed_count += 1
                    else:
                        failed_count += 1

                    result = {
                        'playbook': playbook_name,
                        'status': playbook_status,
                        'run_id': run_id,
                        'log_file': log_file,
                        'exit_code': exit_code,
                        'started': playbook_started,
                        'finished': playbook_finished,
                        'worker_name': 'local-executor'
                    }
                    results.append(result)

                except Exception as e:
                    failed_count += 1
                    result = {
                        'playbook': playbook_name,
                        'status': 'failed',
                        'error': str(e),
                        'started': playbook_started,
                        'finished': datetime.now().isoformat()
                    }
                    results.append(result)

            # Update progress after each playbook
            _update_batch_progress(batch_id, playbook_name, i + 1, len(playbooks),
                                   completed_count, failed_count, results, 'running',
                                   worker_name=current_worker_name)

        # Determine final batch status
        if failed_count == 0:
            final_status = 'completed'
        elif completed_count == 0:
            final_status = 'failed'
        else:
            final_status = 'partial'

        finished_time = datetime.now().isoformat()

        # Update final batch job status
        with batch_lock:
            if batch_id in active_batch_jobs:
                active_batch_jobs[batch_id]['status'] = final_status
                active_batch_jobs[batch_id]['finished'] = finished_time
                active_batch_jobs[batch_id]['completed'] = completed_count
                active_batch_jobs[batch_id]['failed'] = failed_count
                active_batch_jobs[batch_id]['results'] = results
                active_batch_jobs[batch_id]['current_playbook'] = None
                active_batch_jobs[batch_id]['current_run_id'] = None

        if storage_backend:
            batch_job = storage_backend.get_batch_job(batch_id)
            if batch_job:
                batch_job['status'] = final_status
                batch_job['finished'] = finished_time
                batch_job['completed'] = completed_count
                batch_job['failed'] = failed_count
                batch_job['results'] = results
                batch_job['current_playbook'] = None
                batch_job['current_run_id'] = None
                storage_backend.save_batch_job(batch_id, batch_job)

        socketio.emit('batch_job_finished', {
            'batch_id': batch_id,
            'status': final_status,
            'completed': completed_count,
            'failed': failed_count,
            'total': len(playbooks),
            'results': results
        }, room='batch_jobs')

        # Clean up from active_batch_jobs after delay
        time.sleep(60)
        with batch_lock:
            if batch_id in active_batch_jobs:
                del active_batch_jobs[batch_id]

    except Exception as e:
        error_msg = str(e)
        with batch_lock:
            if batch_id in active_batch_jobs:
                active_batch_jobs[batch_id]['status'] = 'failed'
                active_batch_jobs[batch_id]['error'] = error_msg
                active_batch_jobs[batch_id]['finished'] = datetime.now().isoformat()

        if storage_backend:
            batch_job = storage_backend.get_batch_job(batch_id)
            if batch_job:
                batch_job['status'] = 'failed'
                batch_job['error'] = error_msg
                batch_job['finished'] = datetime.now().isoformat()
                storage_backend.save_batch_job(batch_id, batch_job)

        socketio.emit('batch_job_error', {
            'batch_id': batch_id,
            'error': error_msg
        }, room='batch_jobs')

    finally:
        # Clean up temporary inventory file
        if inventory_path and os.path.exists(inventory_path):
            try:
                os.remove(inventory_path)
            except Exception:
                pass


def _update_batch_progress(batch_id, current_playbook, current_index, total,
                           completed, failed, results, status, worker_name=None):
    """Helper to update batch job progress in memory and storage."""
    with batch_lock:
        if batch_id in active_batch_jobs:
            active_batch_jobs[batch_id]['completed'] = completed
            active_batch_jobs[batch_id]['failed'] = failed
            active_batch_jobs[batch_id]['results'] = results
            if worker_name:
                active_batch_jobs[batch_id]['worker_name'] = worker_name

    if storage_backend:
        batch_job = storage_backend.get_batch_job(batch_id)
        if batch_job:
            batch_job['completed'] = completed
            batch_job['failed'] = failed
            batch_job['results'] = results
            if worker_name:
                batch_job['worker_name'] = worker_name
            storage_backend.save_batch_job(batch_id, batch_job)

    emit_data = {
        'batch_id': batch_id,
        'current_playbook': current_playbook,
        'current_index': current_index,
        'total': total,
        'completed': completed,
        'failed': failed,
        'status': status
    }
    if worker_name:
        emit_data['worker_name'] = worker_name

    socketio.emit('batch_job_progress', emit_data, room='batch_jobs')


def create_batch_job(playbooks, targets, name=None):
    """
    Create and start a new batch job.

    Args:
        playbooks: List of playbook names in execution order
        targets: List of target hosts/groups
        name: Optional display name for the batch job

    Returns:
        Tuple of (batch_id, error_message)
    """
    if not playbooks:
        return None, "No playbooks specified"

    if not targets:
        return None, "No targets specified"

    # Validate playbooks exist
    available_playbooks = get_playbooks()
    invalid_playbooks = [p for p in playbooks if p not in available_playbooks]
    if invalid_playbooks:
        return None, f"Invalid playbooks: {', '.join(invalid_playbooks)}"

    batch_id = str(uuid.uuid4())
    created_time = datetime.now().isoformat()

    batch_job = {
        'id': batch_id,
        'name': name or f"Batch {batch_id[:8]}",
        'playbooks': playbooks,
        'targets': targets,
        'status': 'pending',
        'total': len(playbooks),
        'completed': 0,
        'failed': 0,
        'current_playbook': None,
        'current_run_id': None,
        'results': [],
        'created': created_time,
        'started': None,
        'finished': None
    }

    # Save to storage
    if storage_backend:
        storage_backend.save_batch_job(batch_id, batch_job)

    # Add to active tracking
    with batch_lock:
        active_batch_jobs[batch_id] = batch_job.copy()

    # Start execution in background thread
    thread = threading.Thread(
        target=run_batch_job_streaming,
        args=(batch_id, playbooks, targets, name)
    )
    thread.daemon = True
    thread.start()

    return batch_id, None


def get_batch_job_status(batch_id):
    """
    Get the current status of a batch job.

    Args:
        batch_id: Batch job identifier

    Returns:
        Batch job dict or None if not found
    """
    # Check active jobs first (most up-to-date)
    with batch_lock:
        if batch_id in active_batch_jobs:
            return active_batch_jobs[batch_id].copy()

    # Fall back to storage
    if storage_backend:
        return storage_backend.get_batch_job(batch_id)

    return None


@app.route('/')
@require_permission('playbooks:view')
def index():
    """Main page - list all playbooks"""
    playbooks = get_playbooks()
    targets = get_inventory_targets()
    playbook_data = []

    for playbook in playbooks:
        latest_log = get_latest_log(playbook)
        status, run_id = get_playbook_status(playbook)
        active_runs_list = get_active_runs_for_playbook(playbook)

        playbook_data.append({
            'name': playbook,
            'display_name': playbook.replace('-', ' ').title(),
            'latest_log': latest_log,
            'last_run': get_log_timestamp(latest_log),
            'status': status,
            'run_id': run_id,
            'active_runs': active_runs_list
        })

    return render_template('index.html', playbooks=playbook_data, targets=targets)

def _has_remote_workers():
    """Check if there are remote workers available (not just local)."""
    if not storage_backend:
        return False
    workers = storage_backend.get_all_workers()
    return any(not w.get('is_local') and w.get('status') == 'online' for w in workers)


def _should_use_cluster_dispatch():
    """
    Check if cluster dispatch should be used for job execution.

    Returns True when:
    - Running in 'primary' cluster mode
    - There are remote workers available
    """
    return CLUSTER_MODE == 'primary' and _has_remote_workers()


def _submit_cluster_job(playbook: str, target: str, priority: int = 50,
                        required_tags: list = None, preferred_tags: list = None,
                        extra_vars: dict = None, submitted_by: str = 'internal') -> dict:
    """
    Submit a job to the cluster queue and return the job info.

    This helper is used by batch jobs and scheduled jobs to dispatch
    work through the cluster job queue instead of running locally.

    Args:
        playbook: Name of playbook to execute
        target: Target host/group
        priority: Job priority (0-100, higher = more important)
        required_tags: Tags worker must have
        preferred_tags: Tags that boost worker selection score
        extra_vars: Extra variables to pass to ansible
        submitted_by: Source of job submission

    Returns:
        dict: Job info including 'id', or None if submission failed
    """
    if not storage_backend:
        return None

    job_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    job = {
        'id': job_id,
        'playbook': playbook,
        'target': target,
        'required_tags': required_tags or [],
        'preferred_tags': preferred_tags or [],
        'priority': priority,
        'job_type': 'normal',
        'extra_vars': extra_vars or {},
        'status': 'queued',
        'assigned_worker': None,
        'submitted_by': submitted_by,
        'submitted_at': now,
        'assigned_at': None,
        'started_at': None,
        'completed_at': None,
        'log_file': None,
        'exit_code': None,
        'error_message': None
    }

    if storage_backend.save_job(job):
        # Route the job immediately
        try:
            router = get_job_router()
            router.route_job(job_id)
        except Exception as e:
            print(f"Warning: Auto-routing failed for job {job_id}: {e}")
        return job
    return None


def _wait_for_job_completion(job_id: str, timeout: int = 600, poll_interval: float = 1.0) -> dict:
    """
    Wait for a cluster job to complete.

    Polls job status until it reaches a terminal state (completed/failed/cancelled)
    or timeout is reached.

    Args:
        job_id: Job ID to monitor
        timeout: Maximum seconds to wait
        poll_interval: Seconds between status checks

    Returns:
        dict: Final job state, or None if timeout/error
    """
    if not storage_backend:
        return None

    import time
    start_time = time.time()

    while time.time() - start_time < timeout:
        job = storage_backend.get_job(job_id)
        if not job:
            return None

        status = job.get('status')
        if status in ['completed', 'failed', 'cancelled']:
            return job

        time.sleep(poll_interval)

    # Timeout - return current state
    return storage_backend.get_job(job_id)


def _get_worker_name(worker_id: str) -> str:
    """Get worker name from ID, with fallback."""
    if not worker_id or not storage_backend:
        return 'local-executor'
    if worker_id == '__local__':
        return 'local-executor'
    worker = storage_backend.get_worker(worker_id)
    if worker:
        return worker.get('name', worker_id[:8])
    return worker_id[:8] if len(worker_id) > 8 else worker_id


@app.route('/run/<playbook_name>')
@require_permission('playbooks:run')
def run_playbook(playbook_name):
    """Trigger playbook execution with streaming"""
    if playbook_name not in get_playbooks():
        return jsonify({'error': 'Playbook not found'}), 404

    # Get target from query parameter, default to host_machine
    target = request.args.get('target', 'host_machine')

    # Check if we should use the cluster job queue
    # Use job queue if: cluster mode is 'primary' AND there are remote workers online
    use_cluster = CLUSTER_MODE == 'primary' and _has_remote_workers()

    if use_cluster:
        # Submit to job queue for cluster dispatch
        job_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        extra_vars = {}
        if is_managed_host(target) and storage_backend:
            managed_inventory = storage_backend.get_all_inventory()
            for item in managed_inventory:
                if item.get('hostname') == target:
                    extra_vars = dict(item.get('variables') or {})
                    break

        job = {
            'id': job_id,
            'playbook': playbook_name,
            'target': target,
            'required_tags': [],
            'preferred_tags': [],
            'priority': 50,
            'job_type': 'normal',
            'extra_vars': extra_vars,
            'status': 'queued',
            'assigned_worker': None,
            'submitted_by': 'web-ui',
            'submitted_at': now,
            'assigned_at': None,
            'started_at': None,
            'completed_at': None,
            'log_file': None,
            'exit_code': None,
            'error_message': None
        }

        if storage_backend.save_job(job):
            # Trigger automatic job routing
            try:
                router = get_job_router()
                router.route_job(job_id)
            except Exception as e:
                print(f"Warning: Auto-routing failed for job {job_id}: {e}")

            # Redirect to job status page
            return redirect(url_for('job_status_page', job_id=job_id))
        else:
            return jsonify({'error': 'Failed to submit job to cluster'}), 500

    # Local execution path (standalone mode or no remote workers)
    # Check if this playbook+target combination is already running
    is_running, existing_run_id = is_playbook_target_running(playbook_name, target)
    if is_running:
        # Redirect to watch the existing run instead of error
        return redirect(url_for('live_log', run_id=existing_run_id))

    # Generate unique run ID and log filename
    run_id = str(uuid.uuid4())
    log_file = generate_log_filename(playbook_name, target, run_id)

    # Check if target is a managed host and generate temp inventory if needed
    inventory_path = None
    if is_managed_host(target):
        inventory_path = generate_managed_inventory(target)
        if not inventory_path:
            return jsonify({'error': f'Failed to generate inventory for managed host: {target}'}), 500

    # Register the run
    with runs_lock:
        active_runs[run_id] = {
            'playbook': playbook_name,
            'target': target,
            'status': 'starting',
            'started': datetime.now().isoformat(),
            'log_file': log_file,
            'managed_host': inventory_path is not None,
            'worker_id': '__local__',
            'worker_name': 'local-executor'
        }

    # Start playbook in background thread with streaming
    thread = threading.Thread(
        target=run_playbook_streaming,
        args=(run_id, playbook_name, target, log_file, inventory_path)
    )
    thread.daemon = True
    thread.start()

    # Redirect to live log view
    return redirect(url_for('live_log', run_id=run_id))

@app.route('/live/<run_id>')
@require_permission('logs:view')
def live_log(run_id):
    """View live streaming log for a run"""
    with runs_lock:
        run_info = active_runs.get(run_id)

    if not run_info:
        # Check if there's a log file we can show (run may have completed)
        # Try to find the log file by run_id pattern
        pattern = f'{LOGS_DIR}/*-{run_id[:8]}.log'
        log_files = glob.glob(pattern)
        if log_files:
            # Redirect to static log view
            return redirect(url_for('view_log', log_file=os.path.basename(log_files[0])))
        return "Run not found", 404

    return render_template('live_log.html',
                          run_id=run_id,
                          playbook=run_info['playbook'],
                          target=run_info['target'],
                          status=run_info['status'],
                          log_file=run_info.get('log_file', ''),
                          worker_name=run_info.get('worker_name', 'local-executor'))


@app.route('/job/<job_id>')
@require_permission('jobs:view')
def job_status_page(job_id):
    """View job status page for cluster jobs."""
    if not storage_backend:
        return "Storage backend not initialized", 500

    job = storage_backend.get_job(job_id)
    if not job:
        return "Job not found", 404

    # Get worker info if assigned
    worker_name = None
    if job.get('assigned_worker'):
        worker = storage_backend.get_worker(job['assigned_worker'])
        if worker:
            worker_name = worker.get('name', job['assigned_worker'])

    return render_template('job_status.html',
                          job=job,
                          worker_name=worker_name)


@app.route('/live/batch/<batch_id>')
@require_permission('jobs:view')
def batch_live_log(batch_id):
    """View live streaming log for a batch job"""
    batch_job = get_batch_job_status(batch_id)

    if not batch_job:
        return "Batch job not found", 404

    return render_template('batch_live_log.html',
                          batch_id=batch_id,
                          batch_name=batch_job.get('name', f'Batch {batch_id[:8]}'),
                          playbooks=batch_job.get('playbooks', []),
                          targets=batch_job.get('targets', []),
                          status=batch_job.get('status', 'pending'),
                          total=batch_job.get('total', 0),
                          current_playbook=batch_job.get('current_playbook'))


@app.route('/playbooks')
@require_permission('playbooks:view')
def playbooks_page():
    """Individual playbooks page - run single playbooks against targets"""
    playbooks = get_playbooks()
    targets = get_inventory_targets()
    playbook_data = []

    for playbook in playbooks:
        latest_log = get_latest_log(playbook)
        status, run_id = get_playbook_status(playbook)
        active_runs_list = get_active_runs_for_playbook(playbook)

        playbook_data.append({
            'name': playbook,
            'display_name': playbook.replace('-', ' ').title(),
            'latest_log': latest_log,
            'last_run': get_log_timestamp(latest_log),
            'status': status,
            'run_id': run_id,
            'active_runs': active_runs_list
        })

    return render_template('playbooks.html', playbooks=playbook_data, targets=targets)


@app.route('/logs')
@require_permission('logs:view')
def list_logs():
    """List all log files"""
    log_files = []
    if os.path.exists(LOGS_DIR):
        for file in sorted(glob.glob(f'{LOGS_DIR}/*.log'), key=os.path.getmtime, reverse=True):
            if 'ansible.log' not in file:  # Skip main ansible.log
                log_files.append({
                    'name': os.path.basename(file),
                    'size': os.path.getsize(file),
                    'modified': datetime.fromtimestamp(os.path.getmtime(file)).strftime('%Y-%m-%d %H:%M:%S')
                })
    return render_template('logs.html', logs=log_files)

@app.route('/logs/<log_file>')
@require_permission('logs:view')
def view_log(log_file):
    """View a specific log file"""
    log_path = os.path.join(LOGS_DIR, log_file)
    if not os.path.exists(log_path):
        return "Log file not found", 404

    # Read log file
    with open(log_path, 'r') as f:
        content = f.read()

    # Try to extract metadata from log header
    # Format: === Playbook: name | Target: target | Worker: worker | Started: timestamp ===
    playbook_name = None
    target = None
    worker_name = None
    started = None

    first_line = content.split('\n')[0] if content else ''
    if first_line.startswith('===') and '|' in first_line:
        import re
        # Extract playbook name
        pb_match = re.search(r'Playbook:\s*([^|]+)', first_line)
        if pb_match:
            playbook_name = pb_match.group(1).strip()
        # Extract target
        tgt_match = re.search(r'Target:\s*([^|]+)', first_line)
        if tgt_match:
            target = tgt_match.group(1).strip()
        # Extract worker
        wkr_match = re.search(r'Worker:\s*([^|]+)', first_line)
        if wkr_match:
            worker_name = wkr_match.group(1).strip()
        # Extract started time
        st_match = re.search(r'Started:\s*([^=]+)', first_line)
        if st_match:
            started = st_match.group(1).strip()

    # Find Job ID for Agent Review
    job_id = None
    if storage_backend:
        try:
            # Check recent history for matching log file
            # Limit 100 to catch recent logs
            history = storage_backend.get_history(limit=100)
            for job in history:
                if job.get('log_file') == log_file:
                    job_id = job.get('run_id') or job.get('id')
                    break
        except Exception as e:
            print(f"Error finding job_id for log: {e}")
            
    # Fallback: Check log header for Job ID (if added in newer logs)
    if not job_id and first_line and 'Job ID:' in first_line:
        import re
        jid_match = re.search(r'Job ID:\s*([a-f0-9-]+)', first_line)
        if jid_match:
            job_id = jid_match.group(1).strip()

    return render_template('log_view.html',
                          log_file=log_file,
                          content=content,
                          playbook_name=playbook_name,
                          target=target,
                          worker_name=worker_name,
                          started=started,
                          job_id=job_id)

@app.route('/api/status')
@require_permission('playbooks:view')
def api_status():
    """Get status of all playbooks"""
    playbooks = get_playbooks()
    status_data = {}

    for playbook in playbooks:
        status, run_id = get_playbook_status(playbook)
        status_data[playbook] = {
            'status': status,
            'run_id': run_id
        }

    return jsonify(status_data)

@app.route('/api/playbooks')
@require_permission('playbooks:view')
def api_playbooks():
    """API endpoint to get playbook information"""
    playbooks = get_playbooks()
    result = []

    for playbook in playbooks:
        latest_log = get_latest_log(playbook)
        status, run_id = get_playbook_status(playbook)
        active_runs_list = get_active_runs_for_playbook(playbook)

        result.append({
            'name': playbook,
            'latest_log': latest_log,
            'last_run': get_log_timestamp(latest_log),
            'status': status,
            'run_id': run_id,
            'active_runs': active_runs_list
        })

    return jsonify(result)

@app.route('/api/runs')
@require_permission('jobs:view')
def api_runs():
    """Get all active runs"""
    with runs_lock:
        # Filter out process objects (not serializable)
        runs = {}
        for run_id, run_info in active_runs.items():
            runs[run_id] = {k: v for k, v in run_info.items() if k != 'process'}
    return jsonify(runs)

@app.route('/api/runs/<run_id>')
@require_permission('jobs:view')
def api_run_detail(run_id):
    """Get details of a specific run"""
    with runs_lock:
        run_info = active_runs.get(run_id)
        if run_info:
            return jsonify({k: v for k, v in run_info.items() if k != 'process'})
    return jsonify({'error': 'Run not found'}), 404

@app.route('/api/runs/<run_id>/log')
@require_permission('logs:view')
def api_run_log(run_id):
    """Get the log content for a run (for reconnection/catch-up)"""
    with runs_lock:
        run_info = active_runs.get(run_id)

    if not run_info:
        return jsonify({'error': 'Run not found'}), 404

    log_file = run_info.get('log_file')
    if not log_file:
        return jsonify({'error': 'No log file'}), 404

    log_path = os.path.join(LOGS_DIR, log_file)
    if not os.path.exists(log_path):
        return jsonify({'content': '', 'status': run_info['status']})

    with open(log_path, 'r') as f:
        content = f.read()

    return jsonify({
        'content': content,
        'status': run_info['status'],
        'playbook': run_info['playbook'],
        'target': run_info['target']
    })


# =============================================================================
# Batch Job API Endpoints
# Handles batch execution of multiple playbooks against multiple targets
# =============================================================================

@app.route('/api/batch', methods=['GET'])
@require_permission('jobs:view')
def api_batch_list():
    """
    Get all batch jobs.

    Query params:
        - status: Filter by status (pending, running, completed, failed, partial)
        - limit: Max number of jobs to return (default 50)
    """
    status_filter = request.args.get('status')
    limit = request.args.get('limit', 50, type=int)

    if storage_backend:
        if status_filter:
            batch_jobs = storage_backend.get_batch_jobs_by_status(status_filter)
        else:
            batch_jobs = storage_backend.get_all_batch_jobs()
    else:
        # Fall back to in-memory only
        with batch_lock:
            batch_jobs = list(active_batch_jobs.values())
            if status_filter:
                batch_jobs = [j for j in batch_jobs if j.get('status') == status_filter]

    # Apply limit
    batch_jobs = batch_jobs[:limit]

    return jsonify({
        'batch_jobs': batch_jobs,
        'count': len(batch_jobs)
    })


@app.route('/api/batch/<batch_id>', methods=['GET'])
@require_permission('jobs:view')
def api_batch_detail(batch_id):
    """Get details of a specific batch job."""
    batch_job = get_batch_job_status(batch_id)
    if batch_job:
        return jsonify(batch_job)
    return jsonify({'error': 'Batch job not found'}), 404


@app.route('/api/batch', methods=['POST'])
@require_permission('jobs:submit')
def api_batch_create():
    """
    Create and start a new batch job.

    Request body:
    {
        "playbooks": ["playbook1", "playbook2"],  // Required, in execution order
        "targets": ["host1", "group1"],           // Required
        "name": "Optional display name"           // Optional
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    playbooks = data.get('playbooks', [])
    targets = data.get('targets', [])
    name = data.get('name')

    if not playbooks:
        return jsonify({'error': 'playbooks list is required'}), 400

    if not targets:
        return jsonify({'error': 'targets list is required'}), 400

    # Ensure playbooks is a list
    if isinstance(playbooks, str):
        playbooks = [playbooks]

    # Ensure targets is a list
    if isinstance(targets, str):
        targets = [targets]

    batch_id, error = create_batch_job(playbooks, targets, name)

    if error:
        return jsonify({'error': error}), 400

    return jsonify({
        'batch_id': batch_id,
        'status': 'pending',
        'message': 'Batch job created and started'
    }), 201


@app.route('/api/batch/<batch_id>', methods=['DELETE'])
@require_permission('jobs:cancel')
def api_batch_delete(batch_id):
    """
    Delete a batch job.

    Note: Cannot delete a running batch job.
    """
    batch_job = get_batch_job_status(batch_id)

    if not batch_job:
        return jsonify({'error': 'Batch job not found'}), 404

    if batch_job.get('status') == 'running':
        return jsonify({'error': 'Cannot delete a running batch job'}), 400

    # Remove from active tracking
    with batch_lock:
        if batch_id in active_batch_jobs:
            del active_batch_jobs[batch_id]

    # Remove from storage
    if storage_backend:
        storage_backend.delete_batch_job(batch_id)

    return jsonify({'message': 'Batch job deleted', 'batch_id': batch_id})


@app.route('/api/batch/<batch_id>/logs', methods=['GET'])
@require_permission('logs:view')
def api_batch_logs(batch_id):
    """
    Get log files for a batch job.

    Returns list of log files for each playbook execution in the batch.
    """
    batch_job = get_batch_job_status(batch_id)

    if not batch_job:
        return jsonify({'error': 'Batch job not found'}), 404

    results = batch_job.get('results', [])
    logs = []

    for result in results:
        log_file = result.get('log_file')
        if log_file:
            log_path = os.path.join(LOGS_DIR, log_file)
            logs.append({
                'playbook': result.get('playbook'),
                'log_file': log_file,
                'status': result.get('status'),
                'exists': os.path.exists(log_path)
            })

    return jsonify({
        'batch_id': batch_id,
        'logs': logs
    })


@app.route('/api/batch/<batch_id>/logs/<log_file>', methods=['GET'])
@require_permission('logs:view')
def api_batch_log_content(batch_id, log_file):
    """Get the content of a specific log file from a batch job."""
    batch_job = get_batch_job_status(batch_id)

    if not batch_job:
        return jsonify({'error': 'Batch job not found'}), 404

    # Verify the log file belongs to this batch job
    valid_log = False
    for result in batch_job.get('results', []):
        if result.get('log_file') == log_file:
            valid_log = True
            break

    if not valid_log:
        return jsonify({'error': 'Log file not found for this batch job'}), 404

    log_path = os.path.join(LOGS_DIR, log_file)
    if not os.path.exists(log_path):
        return jsonify({'error': 'Log file does not exist'}), 404

    with open(log_path, 'r') as f:
        content = f.read()

    return jsonify({
        'batch_id': batch_id,
        'log_file': log_file,
        'content': content
    })


@app.route('/api/batch/active', methods=['GET'])
@require_permission('jobs:view')
def api_batch_active():
    """Get all currently active (running) batch jobs."""
    with batch_lock:
        active = {
            batch_id: {k: v for k, v in job.items()}
            for batch_id, job in active_batch_jobs.items()
            if job.get('status') in ['pending', 'running']
        }
    return jsonify(active)


@app.route('/api/batch/<batch_id>/export', methods=['GET'])
@require_permission('jobs:view')
def api_batch_export(batch_id):
    """
    Export a batch job configuration for reuse or version control.

    Returns the batch job configuration without execution-specific data.
    """
    batch_job = get_batch_job_status(batch_id)

    if not batch_job:
        return jsonify({'error': 'Batch job not found'}), 404

    # Export only the configuration, not execution state
    export_data = {
        'name': batch_job.get('name'),
        'playbooks': batch_job.get('playbooks', []),
        'targets': batch_job.get('targets', []),
        'exported_from': batch_id,
        'exported_at': datetime.now().isoformat()
    }

    return jsonify(export_data)


# =============================================================================
# Theme API Endpoints
# Serves theme configuration from config/themes/*.json files
# Used by web/static/js/theme.js to load and apply themes
# =============================================================================

# PUBLIC ROUTE: Theme list is public to allow login page styling
@app.route('/api/themes')
def api_themes():
    """
    Get list of available themes.

    Returns JSON array of theme metadata:
    [
        {"id": "default", "name": "Default", "description": "Light theme..."},
        {"id": "dark", "name": "Dark", "description": "Dark theme..."},
        ...
    ]

    Themes are discovered by scanning config/themes/*.json files.
    The 'default' theme is always sorted first.
    """
    themes = []
    if os.path.exists(THEMES_DIR):
        for file in sorted(glob.glob(f'{THEMES_DIR}/*.json')):
            theme_id = os.path.basename(file).replace('.json', '')
            try:
                with open(file, 'r') as f:
                    theme_data = json.load(f)
                    themes.append({
                        'id': theme_id,
                        'name': theme_data.get('name', theme_id.title()),
                        'description': theme_data.get('description', '')
                    })
            except (json.JSONDecodeError, IOError) as e:
                # Skip invalid theme files
                print(f"Error loading theme {theme_id}: {e}")
                continue

    # Ensure default theme is first if it exists
    themes.sort(key=lambda t: (t['id'] != 'default', t['name']))

    return jsonify(themes)


# PUBLIC ROUTE: Theme details are public to allow login page styling
@app.route('/api/themes/<theme_name>')
def api_theme(theme_name):
    """
    Get a specific theme's full configuration.

    Args:
        theme_name: Theme identifier (e.g., 'dark', 'colorblind')

    Returns:
        Full theme JSON including all color definitions.
        Used by theme.js to apply CSS variables.

    Security:
        - Sanitizes theme_name to prevent path traversal attacks
        - Only serves files from THEMES_DIR with .json extension
    """
    # Sanitize theme name to prevent path traversal (e.g., '../../../etc/passwd')
    if '/' in theme_name or '\\' in theme_name or '..' in theme_name:
        return jsonify({'error': 'Invalid theme name'}), 400

    theme_path = os.path.join(THEMES_DIR, f'{theme_name}.json')

    if not os.path.exists(theme_path):
        return jsonify({'error': 'Theme not found'}), 404

    try:
        with open(theme_path, 'r') as f:
            theme_data = json.load(f)
        return jsonify(theme_data)
    except json.JSONDecodeError as e:
        return jsonify({'error': f'Invalid theme file: {str(e)}'}), 500
    except IOError as e:
        return jsonify({'error': f'Error reading theme: {str(e)}'}), 500


# =============================================================================
# Config API Endpoints
# Application config (app_config.yaml): view, edit, backup, restore
# =============================================================================

@app.route('/api/config', methods=['GET'])
@require_permission('config:view')
def api_config_get():
    """
    Get current application configuration (from app_config.yaml or defaults).
    """
    try:
        from config_manager import load_config, config_file_exists, get_config_path
        cfg = load_config()
        return jsonify({
            'config': cfg,
            'config_file_exists': config_file_exists(),
            'config_path': get_config_path(),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/config', methods=['PUT'])
@require_permission('config:edit')
def api_config_put():
    """
    Update application configuration. Expects JSON body with config keys to merge.
    Validates and writes to app_config.yaml.
    """
    try:
        from config_manager import load_config, save_config, validate_config
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify({'error': 'JSON body must be a dict'}), 400
        current = load_config()
        merged = {**current, **data}
        success, err = save_config(merged)
        if not success:
            return jsonify({'error': err}), 400
        return jsonify({'ok': True, 'message': 'Config saved'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/backup', methods=['GET'])
@require_permission('config:view')
def api_config_backup():
    """
    Return current config as a downloadable YAML file (config backup).
    """
    try:
        from config_manager import load_config
        import yaml
        from io import BytesIO
        cfg = load_config()
        content = yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False)
        buf = BytesIO(content.encode('utf-8'))
        return send_file(
            buf,
            as_attachment=True,
            download_name=f'app_config_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.yaml',
            mimetype='application/x-yaml',
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/config/restore', methods=['POST'])
@require_permission('config:edit')
def api_config_restore():
    """
    Restore config from uploaded YAML file. Expects multipart file or raw YAML body.
    """
    try:
        from config_manager import save_config, validate_config
        import yaml
        content = None
        if request.content_type and 'multipart/form-data' in request.content_type:
            f = request.files.get('file')
            if not f:
                return jsonify({'error': 'No file in multipart request'}), 400
            content = f.read().decode('utf-8')
        else:
            content = request.get_data(as_text=True)
        if not content or not content.strip():
            return jsonify({'error': 'No YAML content provided'}), 400
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return jsonify({'error': 'YAML must define a dict'}), 400
        success, err = save_config(data)
        if not success:
            return jsonify({'error': err}), 400
        return jsonify({'ok': True, 'message': 'Config restored'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Data backup/restore (schedules, inventory, history, etc. — separate from config)
# =============================================================================

# Data file names used by flatfile storage (relative to config_dir)
FLATFILE_DATA_FILES = [
    'schedules.json', 'schedule_history.json', 'inventory.json',
    'host_facts.json', 'batch_jobs.json', 'workers.json', 'job_queue.json',
]


def _json_serial(obj):
    """JSON serializer for objects not serializable by default (e.g. datetime)."""
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')


@app.route('/api/data/backup', methods=['GET'])
@admin_required
def api_data_backup():
    """
    Download a zip of data files. Flatfile: copies JSON files. MongoDB: exports collections to same JSON structure and zips (so backup panel works for DB too).
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500
    try:
        from io import BytesIO
        import zipfile
        import json as json_mod
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            if storage_backend.get_backend_type() == 'flatfile':
                config_dir = getattr(storage_backend, 'config_dir', os.environ.get('CONFIG_DIR', '/app/config'))
                for name in FLATFILE_DATA_FILES:
                    path = os.path.join(config_dir, name)
                    if os.path.isfile(path):
                        zf.write(path, name)
            else:
                # MongoDB: export to same filenames/structure as flatfile for consistency
                schedules = storage_backend.get_all_schedules()
                zf.writestr('schedules.json', json_mod.dumps({'schedules': schedules}, indent=2, default=_json_serial))
                history = storage_backend.get_history(limit=100000)
                zf.writestr('schedule_history.json', json_mod.dumps({'version': '1.0', 'history': history}, indent=2, default=_json_serial))
                inventory = storage_backend.get_all_inventory()
                zf.writestr('inventory.json', json_mod.dumps({'inventory': inventory}, indent=2, default=_json_serial))
                # host_facts: build {hosts: {host: doc}} from MongoDB
                try:
                    hosts = {}
                    for doc in storage_backend.host_facts_collection.find():
                        h = doc.get('host')
                        if h:
                            hosts[h] = {k: v for k, v in doc.items() if k != '_id'}
                    zf.writestr('host_facts.json', json_mod.dumps({'version': '1.0', 'hosts': hosts}, indent=2, default=_json_serial))
                except Exception:
                    zf.writestr('host_facts.json', json_mod.dumps({'version': '1.0', 'hosts': {}}))
                batch_jobs = storage_backend.get_all_batch_jobs()
                zf.writestr('batch_jobs.json', json_mod.dumps({'version': '1.0', 'batch_jobs': batch_jobs}, indent=2, default=_json_serial))
                workers = storage_backend.get_all_workers()
                zf.writestr('workers.json', json_mod.dumps({'version': '1.0', 'workers': workers}, indent=2, default=_json_serial))
                jobs = storage_backend.get_all_jobs() if hasattr(storage_backend, 'get_all_jobs') else []
                zf.writestr('job_queue.json', json_mod.dumps({'version': '1.0', 'jobs': jobs}, indent=2, default=_json_serial))
        buf.seek(0)
        return send_file(
            buf,
            as_attachment=True,
            download_name=f'ansible_simpleweb_data_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip',
            mimetype='application/zip',
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/data/restore', methods=['POST'])
@admin_required
def api_data_restore():
    """
    Restore data from uploaded zip. Flatfile: extract to config dir. MongoDB: import JSON into collections (same zip format as backup).
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500
    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'No file provided'}), 400
    try:
        from io import BytesIO
        import zipfile
        import json as json_mod
        data = f.read()
        with zipfile.ZipFile(BytesIO(data), 'r') as zf:
            if storage_backend.get_backend_type() == 'flatfile':
                config_dir = getattr(storage_backend, 'config_dir', os.environ.get('CONFIG_DIR', '/app/config'))
                os.makedirs(config_dir, mode=0o755, exist_ok=True)
                for name in zf.namelist():
                    if name != os.path.basename(name) or name not in FLATFILE_DATA_FILES:
                        continue
                    path = os.path.join(config_dir, name)
                    with open(path, 'wb') as out:
                        out.write(zf.read(name))
            else:
                # MongoDB: parse each known file and replace collection data
                if 'schedules.json' in zf.namelist():
                    payload = json_mod.loads(zf.read('schedules.json').decode('utf-8'))
                    schedules = payload.get('schedules', {})
                    storage_backend.save_all_schedules(schedules)
                if 'schedule_history.json' in zf.namelist():
                    payload = json_mod.loads(zf.read('schedule_history.json').decode('utf-8'))
                    history = payload.get('history', [])
                    storage_backend.history_collection.delete_many({})
                    if history:
                        for entry in history:
                            entry.pop('_id', None)
                        storage_backend.history_collection.insert_many(history)
                if 'inventory.json' in zf.namelist():
                    payload = json_mod.loads(zf.read('inventory.json').decode('utf-8'))
                    inventory = payload.get('inventory', [])
                    storage_backend.inventory_collection.delete_many({})
                    if inventory:
                        for item in inventory:
                            item.pop('_id', None)
                        storage_backend.inventory_collection.insert_many(inventory)
                if 'host_facts.json' in zf.namelist():
                    payload = json_mod.loads(zf.read('host_facts.json').decode('utf-8'))
                    hosts = payload.get('hosts', {})
                    for host, host_data in hosts.items():
                        if host and isinstance(host_data, dict):
                            storage_backend.import_host_facts(host_data)
                if 'batch_jobs.json' in zf.namelist():
                    payload = json_mod.loads(zf.read('batch_jobs.json').decode('utf-8'))
                    batch_jobs = payload.get('batch_jobs', [])
                    storage_backend.batch_jobs_collection.delete_many({})
                    if batch_jobs:
                        for j in batch_jobs:
                            j.pop('_id', None)
                        storage_backend.batch_jobs_collection.insert_many(batch_jobs)
                if 'workers.json' in zf.namelist():
                    payload = json_mod.loads(zf.read('workers.json').decode('utf-8'))
                    workers = payload.get('workers', [])
                    storage_backend.workers_collection.delete_many({})
                    if workers:
                        for w in workers:
                            w.pop('_id', None)
                        storage_backend.workers_collection.insert_many(workers)
                if 'job_queue.json' in zf.namelist():
                    payload = json_mod.loads(zf.read('job_queue.json').decode('utf-8'))
                    jobs = payload.get('jobs', [])
                    storage_backend.job_queue_collection.delete_many({})
                    if jobs:
                        for j in jobs:
                            j.pop('_id', None)
                        storage_backend.job_queue_collection.insert_many(jobs)
        return jsonify({'ok': True, 'message': 'Data restored'})
    except zipfile.BadZipFile:
        return jsonify({'error': 'Invalid zip file'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Storage API Endpoints
# Information about the active storage backend
# =============================================================================

@app.route('/api/storage')
@require_permission('config:view')
def api_storage():
    """
    Get information about the active storage backend.

    Returns:
        JSON with backend type, health status, and configuration.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    return jsonify({
        'backend_type': storage_backend.get_backend_type(),
        'healthy': storage_backend.health_check(),
        'config': {
            'STORAGE_BACKEND': os.environ.get('STORAGE_BACKEND', 'flatfile'),
            'MONGODB_HOST': os.environ.get('MONGODB_HOST', 'mongodb') if storage_backend.get_backend_type() == 'mongodb' else None,
            'MONGODB_DATABASE': os.environ.get('MONGODB_DATABASE', 'ansible_simpleweb') if storage_backend.get_backend_type() == 'mongodb' else None
        }
    })


# =============================================================================
# Certificate API Endpoints
# SSL/TLS certificate management (admin only)
# =============================================================================

@app.route('/api/certificates/info')
@require_permission('config:view')
def api_cert_info():
    """
    Get current SSL certificate information.

    Returns:
        JSON with certificate details (subject, issuer, expiry, etc.)
        or error if no certificate exists.
    """
    from certificates import get_cert_info, check_cert_expiry, CertificateError
    from config_manager import get_effective_security_settings

    settings = get_effective_security_settings()
    cert_path = settings['ssl_cert_path']
    key_path = settings['ssl_key_path']

    result = {
        'ssl_enabled': settings['ssl_enabled'],
        'ssl_mode': settings['ssl_mode'],
        'cert_path': cert_path,
        'key_path': key_path,
        'cert_exists': os.path.exists(cert_path),
        'key_exists': os.path.exists(key_path),
    }

    if result['cert_exists']:
        try:
            info = get_cert_info(cert_path)
            status, days = check_cert_expiry(cert_path)
            result.update({
                'cert_info': info,
                'status': status,
                'days_until_expiry': days
            })
        except CertificateError as e:
            result['cert_error'] = str(e)

    return jsonify(result)


@app.route('/api/certificates/generate', methods=['POST'])
@require_permission('config:edit')
def api_cert_generate():
    """
    Generate a new self-signed certificate.

    Request body (optional):
        {
            "hostname": "...",      # Hostname for CN (default: from config)
            "days": 365,            # Validity period (default: 365)
            "force": false          # Force regeneration even if valid
        }

    Returns:
        {"ok": true, "cert_info": {...}} on success
        {"error": "..."} on failure
    """
    from certificates import generate_self_signed_cert, get_cert_info, CertificateError
    from config_manager import get_effective_security_settings
    from auth_routes import add_audit_entry

    settings = get_effective_security_settings()
    data = request.get_json() or {}

    hostname = data.get('hostname') or settings['ssl_hostname']
    days = int(data.get('days') or settings['ssl_validity_days'])
    cert_path = settings['ssl_cert_path']
    key_path = settings['ssl_key_path']

    try:
        generate_self_signed_cert(
            hostname=hostname,
            days=days,
            cert_path=cert_path,
            key_path=key_path
        )

        info = get_cert_info(cert_path)

        # Audit log
        add_audit_entry(
            action='create',
            resource='certificates',
            resource_id=hostname,
            details={'validity_days': days, 'self_signed': True},
            success=True
        )

        return jsonify({
            'ok': True,
            'cert_info': info,
            'message': f'Generated self-signed certificate for {hostname}'
        })

    except CertificateError as e:
        add_audit_entry(
            action='create',
            resource='certificates',
            resource_id=hostname,
            details={'error': str(e)},
            success=False
        )
        return jsonify({'error': str(e)}), 500


@app.route('/api/certificates/upload', methods=['POST'])
@require_permission('config:edit')
def api_cert_upload():
    """
    Upload a certificate and private key.

    Expects multipart form data with:
        - certificate: PEM file
        - private_key: PEM file

    Returns:
        {"ok": true, "cert_info": {...}} on success
        {"error": "..."} on failure
    """
    from certificates import save_uploaded_certificate, get_cert_info, CertificateError
    from config_manager import get_effective_security_settings
    from auth_routes import add_audit_entry

    settings = get_effective_security_settings()
    cert_path = settings['ssl_cert_path']
    key_path = settings['ssl_key_path']

    cert_file = request.files.get('certificate')
    key_file = request.files.get('private_key')

    if not cert_file:
        return jsonify({'error': 'Certificate file is required'}), 400
    if not key_file:
        return jsonify({'error': 'Private key file is required'}), 400

    try:
        cert_data = cert_file.read()
        key_data = key_file.read()

        success, error = save_uploaded_certificate(
            cert_data=cert_data,
            key_data=key_data,
            cert_path=cert_path,
            key_path=key_path
        )

        if not success:
            add_audit_entry(
                action='update',
                resource='certificates',
                details={'error': error},
                success=False
            )
            return jsonify({'error': error}), 400

        info = get_cert_info(cert_path)

        # Audit log
        add_audit_entry(
            action='update',
            resource='certificates',
            details={'uploaded': True, 'hostname': info['subject'].get('commonName')},
            success=True
        )

        return jsonify({
            'ok': True,
            'cert_info': info,
            'message': 'Certificate uploaded successfully'
        })

    except Exception as e:
        add_audit_entry(
            action='update',
            resource='certificates',
            details={'error': str(e)},
            success=False
        )
        return jsonify({'error': f'Failed to upload certificate: {e}'}), 500


# =============================================================================
# Inventory API Endpoints
# CRUD operations for managed inventory items (hosts/servers)
# Stored via the pluggable storage backend (flatfile or MongoDB)
# =============================================================================

@app.route('/api/inventory')
@require_permission('inventory:view')
def api_inventory_list():
    """
    Get all inventory items.

    Returns:
        JSON array of inventory items with their metadata.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    inventory = storage_backend.get_all_inventory()
    return jsonify(inventory)


@app.route('/api/inventory/<item_id>')
@require_permission('inventory:view')
def api_inventory_get(item_id):
    """
    Get a single inventory item by ID.

    Args:
        item_id: UUID of the inventory item

    Returns:
        JSON inventory item or 404 if not found.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    item = storage_backend.get_inventory_item(item_id)
    if not item:
        return jsonify({'error': 'Inventory item not found'}), 404

    return jsonify(item)


@app.route('/api/inventory', methods=['POST'])
@require_permission('inventory:edit')
def api_inventory_create():
    """
    Create a new inventory item.

    Expected JSON body:
    {
        "hostname": "server.example.com",
        "display_name": "Web Server 1",
        "group": "webservers",
        "description": "Primary web server",
        "variables": {"ansible_user": "deploy", "ansible_port": 22}
    }

    Returns:
        JSON with created item including generated ID.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Validate required fields
    if not data.get('hostname'):
        return jsonify({'error': 'hostname is required'}), 400

    # Generate ID and timestamps
    item_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    item = {
        'id': item_id,
        'hostname': data.get('hostname'),
        'display_name': data.get('display_name', data.get('hostname')),
        'group': data.get('group', 'ungrouped'),
        'description': data.get('description', ''),
        'variables': data.get('variables', {}),
        'created': now,
        'updated': now
    }

    if storage_backend.save_inventory_item(item_id, item):
        _run_inventory_sync()
        resp = dict(item)
        warn = _validate_ssh_key_path(item.get('variables'))
        if warn:
            resp['_warning'] = warn
        return jsonify(resp), 201
    else:
        return jsonify({'error': 'Failed to save inventory item'}), 500


@app.route('/api/inventory/<item_id>', methods=['PUT'])
@require_permission('inventory:edit')
def api_inventory_update(item_id):
    """
    Update an existing inventory item.

    Args:
        item_id: UUID of the inventory item

    Expected JSON body with fields to update.

    Returns:
        JSON with updated item.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    existing = storage_backend.get_inventory_item(item_id)
    if not existing:
        return jsonify({'error': 'Inventory item not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Update allowed fields
    allowed_fields = ['hostname', 'display_name', 'group', 'description', 'variables']
    for field in allowed_fields:
        if field in data:
            existing[field] = data[field]

    existing['updated'] = datetime.now().isoformat()

    if storage_backend.save_inventory_item(item_id, existing):
        _run_inventory_sync()
        resp = dict(existing)
        warn = _validate_ssh_key_path(existing.get('variables'))
        if warn:
            resp['_warning'] = warn
        return jsonify(resp)
    else:
        return jsonify({'error': 'Failed to update inventory item'}), 500


@app.route('/api/inventory/<item_id>', methods=['DELETE'])
@require_permission('inventory:edit')
def api_inventory_delete(item_id):
    """
    Delete an inventory item.

    Args:
        item_id: UUID of the inventory item

    Returns:
        JSON with success status.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    if storage_backend.delete_inventory_item(item_id):
        _run_inventory_sync()
        return jsonify({'success': True, 'deleted': item_id})
    else:
        return jsonify({'error': 'Inventory item not found'}), 404


@app.route('/api/inventory/validate-keys')
@require_permission('inventory:view')
def api_inventory_validate_keys():
    """
    Validate that SSH key paths in inventory exist.
    Returns hosts with missing key files (cluster mode: workers need same paths).
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500
    issues = []
    for item in storage_backend.get_all_inventory():
        path = (item.get('variables') or {}).get('ansible_ssh_private_key_file')
        if path and isinstance(path, str) and path.strip():
            if not os.path.isfile(path.strip()):
                issues.append({
                    'hostname': item.get('hostname'),
                    'id': item.get('id'),
                    'key_path': path.strip(),
                    'message': 'Key file not found. Use /app/ssh-keys/your-key or ensure ./.ssh is mounted on workers.'
                })
    return jsonify({'valid': len(issues) == 0, 'issues': issues})


@app.route('/api/inventory/sync', methods=['POST'])
@require_permission('inventory:edit')
def api_inventory_sync():
    """
    Manually trigger inventory sync (DB <-> static).
    Ensures DB hosts are in managed_hosts.ini and static hosts are in DB.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500
    try:
        def _commit(msg):
            repo = get_content_repo(CONTENT_DIR)
            if repo and repo.is_initialized():
                repo.commit_changes(msg)
        result = run_inventory_sync(storage_backend, INVENTORY_DIR, _commit)
        return jsonify({
            'success': result.get('error') is None,
            'db_to_static': result.get('db_to_static', 0),
            'static_to_db': result.get('static_to_db', 0),
            'error': result.get('error')
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/inventory/search', methods=['POST'])
@require_permission('inventory:view')
def api_inventory_search():
    """
    Search inventory items by criteria.

    Expected JSON body with search criteria:
    {
        "hostname": "web*",      // Supports wildcards
        "group": "webservers"
    }

    Returns:
        JSON array of matching inventory items.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    query = request.get_json() or {}
    results = storage_backend.search_inventory(query)
    return jsonify(results)


# =============================================================================
# Suggested fix API (for errors shown in the UI; no container access required)
# =============================================================================

def _suggested_fix_for_error(error_text):
    """Detect known error patterns and return built-in fix steps for the web UI."""
    if not error_text or not isinstance(error_text, str):
        return None
    text = error_text.strip().lower()
    # SSH public key authentication failed
    if any(x in text for x in [
        'failed to authenticate public key',
        "access denied for 'publickey'",
        'permission denied (publickey)',
        'permission denied for \'publickey\'',
        'no supported authentication methods',
    ]):
        steps = [
            'On the **target machine** (one-time): add your public key to the target user. For Linux/Unix: add the key below to ~/.ssh/authorized_keys (chmod 700 ~/.ssh, chmod 600 ~/.ssh/authorized_keys).',
            'For **MikroTik RouterOS**: connect via Winbox or SSH, then run: `/user ssh-keys add user=YOUR_USER public-key="PASTE_KEY_BELOW"` (replace YOUR_USER with your ansible_user, e.g. llathrop).',
            'For hosts in **inventory files** (e.g. inventory/routers): edit the file and add `ansible_ssh_private_key_file=/app/ssh-keys/your-key` to the host line, or set `ansible_password=YOUR_PASSWORD` if using password auth. Upload keys via **Inventory** page.',
            'For **managed hosts** (Inventory page): set **SSH Username**, **SSH Key** path (/app/ssh-keys/your-key), or **Password**.',
            'Re-run the playbook.',
        ]
        result = {
            'detected': True,
            'title': 'SSH public key authentication failed',
            'steps': steps,
            'link': {'label': 'Open Inventory', 'url': '/inventory'},
        }
        pubkey = _get_default_public_key()
        if pubkey:
            result['public_key'] = pubkey
        return result
    # Connection refused (SSH not running or wrong port)
    if 'connection refused' in text and ('ssh' in text or '22' in error_text):
        return {
            'detected': True,
            'title': 'SSH connection refused',
            'steps': [
                'The target host refused the connection. On the **target machine**, ensure SSH is running (e.g. sudo systemctl start sshd).',
                'If SSH runs on a different port, set **SSH Port** for that host in **Inventory** (e.g. 2222).',
                'Re-run the playbook from the web UI.',
            ],
            'link': {'label': 'Open Inventory', 'url': '/inventory'},
        }
    # Host unreachable / no route
    if 'unreachable' in text or 'no route to host' in text:
        return {
            'detected': True,
            'title': 'Host unreachable',
            'steps': [
                'Check that the host hostname or IP in **Inventory** is correct and that the host is on the network.',
                'If you use hostnames, ensure the runner (primary or worker) can resolve them. Re-run the playbook after fixing.',
            ],
            'link': {'label': 'Open Inventory', 'url': '/inventory'},
        }
    return None


@app.route('/api/suggested-fix')
@require_permission('logs:view')
def api_suggested_fix():
    """
    Return a suggested fix for an error message, for display in the web UI.
    No container access required; fixes are actionable from the UI or target host.
    """
    error = request.args.get('error', '') or request.args.get('q', '')
    suggestion = _suggested_fix_for_error(error)
    if suggestion:
        return jsonify(suggestion)
    return jsonify({'detected': False})


# =============================================================================
# SSH Key Management API
# =============================================================================

SSH_KEYS_DIR = '/app/ssh-keys'


def _validate_ssh_key_path(variables):
    """If ansible_ssh_private_key_file is set, check file exists. Return warning or None."""
    if not variables:
        return None
    path = variables.get('ansible_ssh_private_key_file')
    if not path or not isinstance(path, str):
        return None
    path = path.strip()
    if not path:
        return None
    if not os.path.isfile(path):
        return f'SSH key file not found: {path}. In cluster mode, workers need the same path. Use /app/ssh-keys/your-key (uploaded) or ensure ./.ssh is mounted on workers.'
    return None


@app.route('/api/ssh-keys')
@require_permission('inventory:view')
def api_ssh_keys_list():
    """
    List available SSH keys from the ssh-keys directory.

    Returns:
        JSON with list of key names and paths.
    """
    keys = []

    # Check multiple locations for SSH keys (docker-compose mounts)
    key_dirs = [
        '/app/.ssh',       # Project .ssh (e.g. svc-ansible-key)
        SSH_KEYS_DIR,      # Uploaded keys
        '/root/.ssh',      # Mounted host keys
    ]

    for key_dir in key_dirs:
        if os.path.isdir(key_dir):
            for filename in os.listdir(key_dir):
                filepath = os.path.join(key_dir, filename)
                # Skip public keys and non-files
                if os.path.isfile(filepath) and not filename.endswith('.pub'):
                    keys.append({
                        'name': filename,
                        'path': filepath,
                        'source': 'uploaded' if key_dir == SSH_KEYS_DIR else 'system'
                    })

    return jsonify({'keys': keys})


def _get_default_public_key():
    """Return content of first available SSH public key for display/copy-to-target."""
    # Check mounted host keys (docker-compose: ~/.ssh:/root/.ssh)
    for name in ['id_ed25519.pub', 'id_rsa.pub', 'id_ecdsa.pub']:
        path = os.path.join('/root/.ssh', name)
        if os.path.isfile(path):
            try:
                with open(path, 'r') as f:
                    return f.read().strip()
            except (IOError, OSError):
                pass
    # Check ssh-keys dir for .pub files (uploaded keys may have companion .pub)
    if os.path.isdir(SSH_KEYS_DIR):
        for f in sorted(os.listdir(SSH_KEYS_DIR)):
            if f.endswith('.pub'):
                try:
                    with open(os.path.join(SSH_KEYS_DIR, f), 'r') as fp:
                        return fp.read().strip()
                except (IOError, OSError):
                    pass
    return None


@app.route('/api/ssh-keys/default-public')
@require_permission('inventory:view')
def api_ssh_keys_default_public():
    """
    Return the default SSH public key for copy-to-target (e.g. add to MikroTik).
    Used when SSH publickey auth fails so the user can add the key to the target.
    """
    key = _get_default_public_key()
    if key:
        return jsonify({'public_key': key})
    return jsonify({'public_key': None})


@app.route('/api/ssh-keys', methods=['POST'])
@require_permission('inventory:edit')
def api_ssh_keys_upload():
    """
    Upload a new SSH private key.

    Expected JSON body:
    {
        "name": "my-key",
        "content": "-----BEGIN RSA PRIVATE KEY-----\n..."
    }

    Returns:
        JSON with the saved key path.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    name = data.get('name', '').strip()
    content = data.get('content', '')

    if not name:
        return jsonify({'error': 'Key name is required'}), 400
    if not content:
        return jsonify({'error': 'Key content is required'}), 400

    # Sanitize name - only allow alphanumeric, dash, underscore
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return jsonify({'error': 'Key name can only contain letters, numbers, dashes, and underscores'}), 400

    # Create directory if it doesn't exist
    os.makedirs(SSH_KEYS_DIR, exist_ok=True)

    key_path = os.path.join(SSH_KEYS_DIR, name)

    # Check if key already exists
    if os.path.exists(key_path):
        return jsonify({'error': f'Key "{name}" already exists'}), 409

    try:
        # Write key file with secure permissions
        with open(key_path, 'w') as f:
            f.write(content)
        os.chmod(key_path, 0o600)

        return jsonify({
            'success': True,
            'name': name,
            'path': key_path
        })
    except Exception as e:
        return jsonify({'error': f'Failed to save key: {str(e)}'}), 500


@app.route('/api/inventory/test-connection', methods=['POST'])
@require_permission('inventory:edit')
def api_inventory_test_connection():
    """
    Test SSH connection to a host.

    Expected JSON body:
    {
        "hostname": "192.168.1.50",
        "variables": {
            "ansible_user": "deploy",
            "ansible_ssh_private_key_file": "/app/ssh-keys/my-key"
        }
    }

    Returns:
        JSON with success status and message.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    hostname = data.get('hostname', '').strip()
    variables = data.get('variables', {})

    if not hostname:
        return jsonify({'error': 'Hostname is required'}), 400

    # Create temporary inventory file for the test
    import tempfile
    import subprocess

    try:
        # Build inventory content
        host_vars = []
        for key, value in variables.items():
            if isinstance(value, str):
                host_vars.append(f'{key}="{value}"')
            else:
                host_vars.append(f'{key}={value}')

        vars_str = ' '.join(host_vars)
        inventory_content = f"[test]\n{hostname} {vars_str}\n"

        # Write temporary inventory
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as f:
            f.write(inventory_content)
            inventory_path = f.name

        try:
            # Run ansible ping module
            result = subprocess.run(
                [
                    'ansible', hostname,
                    '-i', inventory_path,
                    '-m', 'ping',
                    '--timeout', '10'
                ],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return jsonify({
                    'success': True,
                    'message': 'Connection successful'
                })
            else:
                # Extract error message, combining stdout and stderr
                error_msg = (result.stderr or '') + (result.stdout or '')

                # Filter out deprecation warnings and other noise
                lines = [l for l in error_msg.split('\n')
                         if l.strip() and not l.startswith('[DEPRECATION WARNING]')
                         and not l.startswith('[WARNING]')
                         and 'is a more generic version' not in l
                         and 'M(ansible.builtin' not in l]
                error_msg = '\n'.join(lines[:5])  # Limit to first 5 meaningful lines

                # Clean up the error message
                if 'UNREACHABLE' in error_msg or not error_msg.strip():
                    error_msg = 'Host unreachable - check hostname and network'
                elif 'Permission denied' in error_msg:
                    error_msg = 'Permission denied - check credentials'
                elif 'No route to host' in error_msg:
                    error_msg = 'No route to host - check network configuration'
                elif 'Connection refused' in error_msg:
                    error_msg = 'Connection refused - SSH service may not be running'
                elif 'Connection timed out' in error_msg or 'timed out' in error_msg.lower():
                    error_msg = 'Connection timed out - host may be unreachable'
                else:
                    # Truncate long errors
                    error_msg = error_msg[:200] if len(error_msg) > 200 else error_msg

                return jsonify({
                    'success': False,
                    'error': error_msg.strip() or 'Connection failed'
                })

        finally:
            # Clean up temp file
            os.unlink(inventory_path)

    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'error': 'Connection timed out after 30 seconds'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Test failed: {str(e)}'
        })


# =============================================================================
# Inventory Management Page
# =============================================================================

@app.route('/inventory')
@require_permission('inventory:view')
def inventory_page():
    """
    Inventory management page - view and manage stored inventory items.
    """
    if not storage_backend:
        return "Storage backend not initialized", 500

    inventory = storage_backend.get_all_inventory()

    # Get unique groups
    groups = sorted(set(item.get('group', 'ungrouped') for item in inventory))

    return render_template('inventory.html',
                          inventory=inventory,
                          inventory_json=json.dumps(inventory),
                          groups=groups,
                          backend_type=storage_backend.get_backend_type())


# =============================================================================
# Storage Info Page
# =============================================================================

@app.route('/storage')
@require_permission('config:view')
def storage_page():
    """
    Storage information page - view DB stats, config, and execution history.
    """
    if not storage_backend:
        return "Storage backend not initialized", 500

    # Get storage info
    storage_info = {
        'backend_type': storage_backend.get_backend_type(),
        'healthy': storage_backend.health_check(),
        'config': {
            'STORAGE_BACKEND': os.environ.get('STORAGE_BACKEND', 'flatfile'),
            'MONGODB_HOST': os.environ.get('MONGODB_HOST', 'mongodb') if storage_backend.get_backend_type() == 'mongodb' else None,
            'MONGODB_DATABASE': os.environ.get('MONGODB_DATABASE', 'ansible_simpleweb') if storage_backend.get_backend_type() == 'mongodb' else None
        }
    }

    # Get stats
    schedules = schedule_manager.get_all_schedules() if schedule_manager else []
    inventory = storage_backend.get_all_inventory()
    history = storage_backend.get_history(limit=100)

    # Add schedule names to history entries
    schedule_map = {s['id']: s['name'] for s in schedules}
    for entry in history:
        entry['schedule_name'] = schedule_map.get(entry.get('schedule_id'), None)

    stats = {
        'schedules': len(schedules),
        'inventory': len(inventory),
        'history': len(history)
    }

    return render_template('storage.html',
                          storage_info=storage_info,
                          stats=stats,
                          schedules=schedules,
                          inventory=inventory,
                          history=history)


@app.route('/api/history')
@require_permission('logs:view')
def api_history():
    """
    Get execution history with optional filtering.

    Query params:
        limit: Max entries to return (default 50)
        schedule_id: Filter by specific schedule

    Returns:
        JSON array of history entries.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    limit = request.args.get('limit', 50, type=int)
    schedule_id = request.args.get('schedule_id', None)

    history = storage_backend.get_history(schedule_id=schedule_id, limit=limit)

    # Add schedule names and format for display
    if schedule_manager:
        schedules = schedule_manager.get_all_schedules()
        schedule_map = {s['id']: s['name'] for s in schedules}
        for entry in history:
            entry['schedule_name'] = schedule_map.get(entry.get('schedule_id'), None)

            # Format duration
            if entry.get('duration_seconds'):
                mins, secs = divmod(int(entry['duration_seconds']), 60)
                entry['duration_display'] = f"{mins}m {secs}s"
            else:
                entry['duration_display'] = 'N/A'

            # Format started time
            if entry.get('started'):
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(entry['started'])
                    entry['started_display'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    entry['started_display'] = entry['started']

    return jsonify(history)


# =============================================================================
# Host Facts API (CMDB)
# Endpoints for collected host data from playbook runs
# =============================================================================

@app.route('/api/hosts')
@require_permission('cmdb:view')
def api_hosts_list():
    """
    Get summary of all hosts with collected facts.

    Returns:
        JSON array of host summaries with collections and timestamps.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    hosts = storage_backend.get_all_hosts()
    return jsonify(hosts)


@app.route('/api/hosts/<host>')
@require_permission('cmdb:view')
def api_host_facts(host):
    """
    Get all collected facts for a specific host.

    Args:
        host: Hostname or IP address

    Returns:
        JSON with all host facts and collections.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    facts = storage_backend.get_host_facts(host)
    if not facts:
        return jsonify({'error': 'Host not found'}), 404

    return jsonify(facts)


@app.route('/api/hosts/<host>/<collection>')
@require_permission('cmdb:view')
def api_host_collection(host, collection):
    """
    Get a specific collection for a host.

    Args:
        host: Hostname or IP address
        collection: Collection name (hardware, software, etc.)

    Query params:
        history: Include history (default: false)

    Returns:
        JSON with collection data.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    include_history = request.args.get('history', 'false').lower() == 'true'
    data = storage_backend.get_host_collection(host, collection, include_history)

    if not data:
        return jsonify({'error': 'Collection not found'}), 404

    return jsonify(data)


@app.route('/api/hosts/<host>/<collection>/history')
@require_permission('cmdb:view')
def api_host_collection_history(host, collection):
    """
    Get history of changes for a host's collection.

    Args:
        host: Hostname or IP address
        collection: Collection name

    Query params:
        limit: Max entries (default: 50)

    Returns:
        JSON array of historical changes with diffs.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    limit = request.args.get('limit', 50, type=int)
    history = storage_backend.get_host_history(host, collection, limit)
    return jsonify(history)


@app.route('/api/hosts', methods=['POST'])
@require_permission('cmdb:edit')
def api_save_host_facts():
    """
    Save collected facts for a host.

    Expected JSON body:
    {
        "host": "192.168.1.50",
        "collection": "hardware",
        "data": { ... collected data ... },
        "groups": ["webservers", "production"]  // optional
    }

    Returns:
        JSON with save result (created/updated/unchanged).
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    host = data.get('host')
    collection = data.get('collection')
    facts_data = data.get('data')

    if not host or not collection or not facts_data:
        return jsonify({'error': 'host, collection, and data are required'}), 400

    groups = data.get('groups', [])
    source = data.get('source', 'api')

    result = storage_backend.save_host_facts(
        host=host,
        collection=collection,
        data=facts_data,
        groups=groups,
        source=source
    )

    return jsonify(result)


@app.route('/api/hosts/<host>', methods=['DELETE'])
@require_permission('cmdb:edit')
def api_delete_host(host):
    """
    Delete all facts for a host.

    Args:
        host: Hostname or IP address

    Returns:
        JSON with success status.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    if storage_backend.delete_host_facts(host):
        return jsonify({'success': True, 'deleted': host})
    else:
        return jsonify({'error': 'Host not found'}), 404


@app.route('/api/hosts/<host>/<collection>', methods=['DELETE'])
@require_permission('cmdb:edit')
def api_delete_host_collection(host, collection):
    """
    Delete a specific collection for a host.

    Args:
        host: Hostname or IP address
        collection: Collection to delete

    Returns:
        JSON with success status.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    if storage_backend.delete_host_facts(host, collection):
        return jsonify({'success': True, 'deleted': f'{host}/{collection}'})
    else:
        return jsonify({'error': 'Collection not found'}), 404


@app.route('/api/hosts/by-group/<group>')
@require_permission('cmdb:view')
def api_hosts_by_group(group):
    """
    Get all hosts in a specific group.

    Args:
        group: Ansible group name

    Returns:
        JSON array of host summaries.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    hosts = storage_backend.get_hosts_by_group(group)
    return jsonify(hosts)


@app.route('/cmdb')
@require_permission('cmdb:view')
def cmdb_page():
    """
    CMDB browser page - view collected host facts.
    """
    if not storage_backend:
        return "Storage backend not initialized", 500

    hosts = storage_backend.get_all_hosts()

    # Get all unique groups
    all_groups = set()
    for h in hosts:
        all_groups.update(h.get('groups', []))

    # Get all unique collections
    all_collections = set()
    for h in hosts:
        all_collections.update(h.get('collections', []))

    return render_template('cmdb.html',
                          hosts=hosts,
                          groups=sorted(all_groups),
                          collections=sorted(all_collections),
                          backend_type=storage_backend.get_backend_type())


# =============================================================================
# Schedule Routes
# Playbook scheduling with APScheduler backend
# =============================================================================

@app.route('/schedules')
@require_permission('schedules:view')
def schedules_page():
    """Main schedule management page - list all schedules"""
    if not schedule_manager:
        return "Scheduler not initialized", 500

    schedules = schedule_manager.get_all_schedules()
    playbooks = get_playbooks()
    targets = get_inventory_targets()

    return render_template('schedules.html',
                          schedules=schedules,
                          playbooks=playbooks,
                          targets=targets)


@app.route('/schedules/new')
@require_permission('schedules:edit')
def new_schedule():
    """Form to create a new schedule"""
    playbooks = get_playbooks()
    targets = get_inventory_targets()

    # Pre-select playbook if provided in query param
    selected_playbook = request.args.get('playbook', '')

    # Check for batch mode from URL params (from "Schedule Batch" button)
    batch_mode = request.args.get('batch') == 'true'
    batch_playbooks = request.args.get('playbooks', '')
    batch_targets = request.args.get('targets', '')
    batch_name = request.args.get('name', '')

    # Convert to lists for template
    batch_playbooks_list = [p.strip() for p in batch_playbooks.split(',') if p.strip()] if batch_playbooks else []
    batch_targets_list = [t.strip() for t in batch_targets.split(',') if t.strip()] if batch_targets else []

    return render_template('schedule_form.html',
                          playbooks=playbooks,
                          targets=targets,
                          selected_playbook=selected_playbook,
                          edit_mode=False,
                          schedule=None,
                          batch_mode=batch_mode,
                          batch_playbooks=batch_playbooks,
                          batch_targets=batch_targets,
                          batch_name=batch_name,
                          batch_playbooks_list=batch_playbooks_list,
                          batch_targets_list=batch_targets_list)


@app.route('/schedules/create', methods=['POST'])
@require_permission('schedules:edit')
def create_schedule():
    """Create a new schedule from form submission"""
    if not schedule_manager:
        return "Scheduler not initialized", 500

    # Check if this is a batch schedule
    is_batch = request.form.get('is_batch') == 'true'

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()

    # Build recurrence config from form data
    recurrence_config = build_recurrence_config(request.form)

    if is_batch:
        # Batch schedule - multiple playbooks and targets
        playbooks_str = request.form.get('playbooks', '')
        targets_str = request.form.get('targets', '')

        playbooks = [p.strip() for p in playbooks_str.split(',') if p.strip()]
        targets = [t.strip() for t in targets_str.split(',') if t.strip()]

        # Validate
        available_playbooks = get_playbooks()
        invalid = [p for p in playbooks if p not in available_playbooks]
        if invalid:
            return f"Invalid playbooks: {', '.join(invalid)}", 400

        if not playbooks:
            return "No playbooks specified", 400
        if not targets:
            return "No targets specified", 400

        if not name:
            name = f"Batch: {len(playbooks)} playbooks - {len(targets)} targets"

        # Create batch schedule
        schedule_id = schedule_manager.create_batch_schedule(
            playbooks=playbooks,
            targets=targets,
            name=name,
            recurrence_config=recurrence_config,
            description=description
        )
    else:
        # Single playbook schedule (original behavior)
        playbook = request.form.get('playbook')
        target = request.form.get('target', 'host_machine')

        # Validate required fields
        if not playbook or playbook not in get_playbooks():
            return "Invalid playbook", 400
        if not name:
            name = f"{playbook} - {target}"

        # Create the schedule
        schedule_id = schedule_manager.create_schedule(
            playbook=playbook,
            target=target,
            name=name,
            recurrence_config=recurrence_config,
            description=description
        )

    return redirect(url_for('schedules_page'))


@app.route('/schedules/<schedule_id>/edit')
@require_permission('schedules:edit')
def edit_schedule(schedule_id):
    """Form to edit an existing schedule"""
    if not schedule_manager:
        return "Scheduler not initialized", 500

    schedule = schedule_manager.get_schedule(schedule_id)
    if not schedule:
        return "Schedule not found", 404

    playbooks = get_playbooks()
    targets = get_inventory_targets()

    ctx = {
        'playbooks': playbooks,
        'targets': targets,
        'selected_playbook': schedule.get('playbook'),
        'edit_mode': True,
        'schedule': schedule,
    }

    if schedule.get('is_batch'):
        ctx['batch_mode'] = True
        ctx['batch_playbooks'] = ','.join(schedule.get('playbooks', []))
        ctx['batch_targets'] = ','.join(schedule.get('targets', []))
        ctx['batch_playbooks_list'] = schedule.get('playbooks', [])
        ctx['batch_targets_list'] = schedule.get('targets', [])

    return render_template('schedule_form.html', **ctx)


@app.route('/schedules/<schedule_id>/update', methods=['POST'])
@require_permission('schedules:edit')
def update_schedule(schedule_id):
    """Update an existing schedule"""
    if not schedule_manager:
        return "Scheduler not initialized", 500

    schedule = schedule_manager.get_schedule(schedule_id)
    if not schedule:
        return "Schedule not found", 404

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    target = request.form.get('target', 'host_machine')
    recurrence_config = build_recurrence_config(request.form)

    updates = {
        'name': name,
        'description': description,
        'target': target,
        'recurrence': recurrence_config
    }

    if schedule.get('is_batch'):
        playbooks_raw = request.form.get('playbooks', '')
        targets_raw = request.form.get('targets', '')
        playbooks = [p.strip() for p in playbooks_raw.split(',') if p.strip()]
        targets = [t.strip() for t in targets_raw.split(',') if t.strip()]
        updates['playbooks'] = playbooks
        updates['targets'] = targets

    schedule_manager.update_schedule(schedule_id, updates)
    return redirect(url_for('schedules_page'))


@app.route('/schedules/<schedule_id>/history')
@require_permission('schedules:view')
def schedule_history(schedule_id):
    """View execution history for a schedule"""
    if not schedule_manager:
        return "Scheduler not initialized", 500

    schedule = schedule_manager.get_schedule(schedule_id)
    if not schedule:
        return "Schedule not found", 404

    history = schedule_manager.get_schedule_history(schedule_id, limit=100)

    return render_template('schedule_history.html',
                          schedule=schedule,
                          history=history)


# Schedule API endpoints
@app.route('/api/schedules')
@require_permission('schedules:view')
def api_schedules():
    """Get all schedules as JSON"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    return jsonify(schedule_manager.get_all_schedules())


@app.route('/api/schedules/<schedule_id>')
@require_permission('schedules:view')
def api_schedule_detail(schedule_id):
    """Get a single schedule"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    schedule = schedule_manager.get_schedule(schedule_id)
    if not schedule:
        return jsonify({'error': 'Schedule not found'}), 404
    return jsonify(schedule)


@app.route('/api/schedules/<schedule_id>/pause', methods=['POST'])
@require_permission('schedules:edit')
def api_pause_schedule(schedule_id):
    """Pause a schedule"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    success = schedule_manager.pause_schedule(schedule_id)
    return jsonify({'success': success})


@app.route('/api/schedules/<schedule_id>/resume', methods=['POST'])
@require_permission('schedules:edit')
def api_resume_schedule(schedule_id):
    """Resume a paused schedule"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    success = schedule_manager.resume_schedule(schedule_id)
    return jsonify({'success': success})


@app.route('/api/schedules/<schedule_id>/delete', methods=['POST'])
@require_permission('schedules:edit')
def api_delete_schedule(schedule_id):
    """Delete a schedule"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    success = schedule_manager.delete_schedule(schedule_id)
    return jsonify({'success': success})


@app.route('/api/schedules/<schedule_id>/stop', methods=['POST'])
@require_permission('schedules:edit')
def api_stop_schedule(schedule_id):
    """Stop a currently running scheduled job"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    success = schedule_manager.stop_running_job(schedule_id)
    return jsonify({'success': success})


@app.route('/api/schedules/<schedule_id>/run_now', methods=['POST'])
@require_permission('schedules:edit')
def api_run_schedule_now(schedule_id):
    """Run a scheduled playbook immediately (one-off execution)"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    success = schedule_manager.run_schedule_now(schedule_id)
    if not success:
        return jsonify({'success': False, 'error': 'Schedule not found or already running'}), 400
    return jsonify({'success': True})


@app.route('/api/schedules/<schedule_id>/history')
@require_permission('schedules:view')
def api_schedule_history(schedule_id):
    """Get execution history for a schedule"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    limit = request.args.get('limit', 50, type=int)
    history = schedule_manager.get_schedule_history(schedule_id, limit=limit)
    return jsonify(history)


# =============================================================================
# Worker Registration API (Cluster Support)
# =============================================================================

def init_local_worker():
    """
    Initialize the local executor as an implicit worker.
    Called on startup when running in standalone or primary mode.
    """
    if not storage_backend:
        return

    local_worker = {
        'id': '__local__',
        'name': 'local-executor',
        'tags': LOCAL_WORKER_TAGS,
        'priority_boost': -1000,  # Always lowest priority
        'status': 'online',
        'is_local': True,
        'registered_at': datetime.now().isoformat(),
        'last_checkin': datetime.now().isoformat(),
        'sync_revision': None,
        'current_jobs': [],
        'stats': {
            'load_1m': 0.0,
            'memory_percent': 0,
            'jobs_completed': 0,
            'jobs_failed': 0,
            'avg_job_duration': 0
        }
    }
    storage_backend.save_worker(local_worker)
    print(f"Local worker initialized with tags: {LOCAL_WORKER_TAGS}")


@app.route('/api/workers/register', methods=['POST'])
def api_worker_register():
    """
    Register a new worker with the primary server.

    Expected JSON body:
    {
        "name": "worker-01",
        "tags": ["network-a", "gpu"],
        "token": "registration-secret"
    }

    Returns:
    {
        "worker_id": "uuid",
        "sync_url": "http://primary:3001/api/sync",
        "api_base": "http://primary:3001/api",
        "checkin_interval": 600,
        "current_revision": "abc123" or null
    }
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    # Validate required fields
    name = data.get('name')
    token = data.get('token')
    tags = data.get('tags', [])

    if not name:
        return jsonify({'error': 'Worker name is required'}), 400

    if not token:
        return jsonify({'error': 'Registration token is required'}), 400

    # Validate registration token
    if not REGISTRATION_TOKEN:
        return jsonify({'error': 'Server registration token not configured'}), 500

    if token != REGISTRATION_TOKEN:
        return jsonify({'error': 'Invalid registration token'}), 401

    # Check if worker with this name already exists
    existing_workers = storage_backend.get_all_workers()
    for w in existing_workers:
        if w.get('name') == name and not w.get('is_local'):
            # Update existing worker instead of creating new
            worker_id = w['id']
            worker = {
                'id': worker_id,
                'name': name,
                'tags': tags,
                'priority_boost': w.get('priority_boost', 0),
                'status': 'online',
                'is_local': False,
                'registered_at': w.get('registered_at', datetime.now().isoformat()),
                'last_checkin': datetime.now().isoformat(),
                'sync_revision': None,
                'current_jobs': w.get('current_jobs', []),
                'stats': w.get('stats', {
                    'load_1m': 0.0,
                    'memory_percent': 0,
                    'jobs_completed': 0,
                    'jobs_failed': 0,
                    'avg_job_duration': 0
                })
            }
            storage_backend.save_worker(worker)

            # Emit event for real-time updates
            socketio.emit('worker_registered', {
                'worker_id': worker_id,
                'name': name,
                'tags': tags,
                'status': 'online',
                'is_reconnect': True
            }, room='workers')

            return jsonify({
                'worker_id': worker_id,
                'sync_url': f"{request.host_url.rstrip('/')}/api/sync",
                'api_base': f"{request.host_url.rstrip('/')}/api",
                'checkin_interval': CHECKIN_INTERVAL,
                'current_revision': None,  # Will be set when git sync is implemented
                'message': 'Worker re-registered successfully'
            })

    # Create new worker
    worker_id = str(uuid.uuid4())
    worker = {
        'id': worker_id,
        'name': name,
        'tags': tags,
        'priority_boost': 0,
        'status': 'online',
        'is_local': False,
        'registered_at': datetime.now().isoformat(),
        'last_checkin': datetime.now().isoformat(),
        'sync_revision': None,
        'current_jobs': [],
        'stats': {
            'load_1m': 0.0,
            'memory_percent': 0,
            'jobs_completed': 0,
            'jobs_failed': 0,
            'avg_job_duration': 0
        }
    }

    if not storage_backend.save_worker(worker):
        return jsonify({'error': 'Failed to save worker'}), 500

    # Emit event for real-time updates
    socketio.emit('worker_registered', {
        'worker_id': worker_id,
        'name': name,
        'tags': tags,
        'status': 'online',
        'is_reconnect': False
    }, room='workers')

    print(f"Worker registered: {name} ({worker_id}) with tags {tags}")

    return jsonify({
        'worker_id': worker_id,
        'sync_url': f"{request.host_url.rstrip('/')}/api/sync",
        'api_base': f"{request.host_url.rstrip('/')}/api",
        'checkin_interval': CHECKIN_INTERVAL,
        'current_revision': None,  # Will be set when git sync is implemented
        'message': 'Worker registered successfully'
    }), 201


@app.route('/api/workers', methods=['GET'])
@require_permission('workers:view')
def api_get_workers():
    """
    Get all registered workers.

    Query parameters:
    - status: Filter by status (comma-separated, e.g., 'online,busy')

    Returns list of worker objects.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    status_filter = request.args.get('status')

    if status_filter:
        statuses = [s.strip() for s in status_filter.split(',')]
        workers = storage_backend.get_workers_by_status(statuses)
    else:
        workers = storage_backend.get_all_workers()

    return jsonify(workers)


@app.route('/api/workers/<worker_id>', methods=['GET'])
@require_permission('workers:view')
def api_get_worker(worker_id):
    """Get a single worker by ID."""
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    worker = storage_backend.get_worker(worker_id)
    if not worker:
        return jsonify({'error': 'Worker not found'}), 404

    return jsonify(worker)


@app.route('/api/workers/<worker_id>', methods=['DELETE'])
@require_permission('workers:admin')
def api_delete_worker(worker_id):
    """
    Unregister/delete a worker.

    Cannot delete the local executor (__local__).
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    if worker_id == '__local__':
        return jsonify({'error': 'Cannot delete local executor'}), 400

    worker = storage_backend.get_worker(worker_id)
    if not worker:
        return jsonify({'error': 'Worker not found'}), 404

    # Check if worker has active jobs
    active_jobs = storage_backend.get_worker_jobs(worker_id, statuses=['assigned', 'running'])
    if active_jobs:
        return jsonify({
            'error': 'Worker has active jobs',
            'active_jobs': len(active_jobs),
            'hint': 'Wait for jobs to complete or reassign them first'
        }), 409

    if not storage_backend.delete_worker(worker_id):
        return jsonify({'error': 'Failed to delete worker'}), 500

    # Emit event for real-time updates
    socketio.emit('worker_removed', {
        'worker_id': worker_id,
        'name': worker.get('name')
    }, room='workers')

    print(f"Worker removed: {worker.get('name')} ({worker_id})")

    return jsonify({'message': 'Worker deleted successfully'})


@app.route('/api/workers/<worker_id>/checkin', methods=['POST'])
@worker_auth_required
def api_worker_checkin(worker_id):
    """
    Worker check-in endpoint.

    Expected JSON body:
    {
        "sync_revision": "abc123",
        "active_jobs": [
            {"job_id": "uuid", "status": "running", "progress": 45}
        ],
        "system_stats": {
            "load_1m": 0.5,
            "memory_percent": 67,
            "disk_percent": 45
        }
    }
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    worker = storage_backend.get_worker(worker_id)
    if not worker:
        return jsonify({'error': 'Worker not found'}), 404

    data = request.get_json() or {}

    # Build checkin data
    checkin_data = {}

    if 'sync_revision' in data:
        checkin_data['sync_revision'] = data['sync_revision']

    if 'system_stats' in data:
        checkin_data['stats'] = data['system_stats']

    if 'status' in data:
        checkin_data['status'] = data['status']

    # Update worker with checkin data
    if not storage_backend.update_worker_checkin(worker_id, checkin_data):
        return jsonify({'error': 'Failed to update worker'}), 500

    # Update job progress if provided
    if 'active_jobs' in data:
        for job_info in data['active_jobs']:
            job_id = job_info.get('job_id')
            if job_id:
                storage_backend.update_job(job_id, {
                    'progress': job_info.get('progress')
                })

    # Emit event for real-time updates
    socketio.emit('worker_checkin', {
        'worker_id': worker_id,
        'name': worker.get('name'),
        'status': checkin_data.get('status', worker.get('status')),
        'stats': checkin_data.get('stats', {})
    }, room='workers')

    # Check if worker needs to sync
    needs_sync = False
    current_revision = None
    repo = get_content_repo(CONTENT_DIR)
    if repo.is_initialized():
        current_revision = repo.get_current_revision()
        worker_revision = data.get('sync_revision')
        if current_revision and worker_revision != current_revision:
            needs_sync = True

    return jsonify({
        'message': 'Checkin successful',
        'next_checkin_seconds': CHECKIN_INTERVAL,
        'sync_needed': needs_sync,
        'current_revision': current_revision[:7] if current_revision else None
    })


# =============================================================================
# Cluster Dashboard Routes
# =============================================================================

def _get_stack_status():
    """
    Get status of stack components: DB, Agent, Ollama, and other related containers.
    Per memory.md: cluster dashboard should include DB, agent, workers, and any
    other related containers (Ollama, etc.) as they are added to the stack.
    """
    stack = []
    try:
        from config_manager import load_config, get_effective_storage_backend
        from deployment import get_current_services
        cfg = load_config()
        features = cfg.get('features') or {}
        db_enabled = bool(features.get('db_enabled'))
        agent_enabled = bool(features.get('agent_enabled'))
        backend = get_effective_storage_backend().lower()

        # DB: shown when MongoDB is the storage backend
        db_in_use = backend == 'mongodb'
        db_healthy = False
        if db_in_use and storage_backend:
            db_healthy = storage_backend.health_check()
        stack.append({
            'name': 'DB',
            'enabled': db_in_use,
            'status': 'healthy' if (db_in_use and db_healthy) else ('unhealthy' if db_in_use else 'not_used'),
        })

        # Agent: shown when agent is enabled in config
        agent_reachable = False
        if agent_enabled:
            current = get_current_services(storage_backend=storage_backend)
            agent_reachable = current.get('agent_reachable', False)
        stack.append({
            'name': 'Agent',
            'enabled': agent_enabled,
            'status': 'healthy' if (agent_enabled and agent_reachable) else ('unhealthy' if agent_enabled else 'not_used'),
        })

        # Ollama: shown when agent is enabled (agent depends on Ollama)
        ollama_healthy = False
        if agent_enabled:
            ollama_url = os.environ.get('OLLAMA_URL', 'http://ollama:11434')
            try:
                r = requests.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=2)
                ollama_healthy = r.status_code == 200
            except Exception:
                pass
        stack.append({
            'name': 'Ollama',
            'enabled': agent_enabled,
            'status': 'healthy' if (agent_enabled and ollama_healthy) else ('unhealthy' if agent_enabled else 'not_used'),
        })
    except Exception:
        pass
    return stack


@app.route('/cluster')
@require_permission('workers:view')
def cluster_page():
    """Cluster dashboard page showing workers, jobs, and sync status."""
    return render_template('cluster.html')


@app.route('/api/cluster/status', methods=['GET'])
@require_permission('workers:view')
def api_cluster_status():
    """
    Get cluster status summary.

    Returns overview of cluster health and statistics.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    workers = storage_backend.get_all_workers()
    jobs = storage_backend.get_all_jobs()

    # Count workers by status
    worker_counts = {'online': 0, 'offline': 0, 'busy': 0, 'stale': 0}
    for w in workers:
        status = w.get('status', 'unknown')
        if status in worker_counts:
            worker_counts[status] += 1

    # Count jobs by status
    job_counts = {'queued': 0, 'assigned': 0, 'running': 0, 'completed': 0, 'failed': 0}
    for j in jobs:
        status = j.get('status', 'unknown')
        if status in job_counts:
            job_counts[status] += 1

    # Find stale workers (no checkin in 2x interval)
    stale_threshold = datetime.now().timestamp() - (CHECKIN_INTERVAL * 2)
    stale_workers = []
    for w in workers:
        if w.get('is_local'):
            continue
        last_checkin = w.get('last_checkin', '')
        if last_checkin:
            try:
                checkin_time = datetime.fromisoformat(last_checkin).timestamp()
                if checkin_time < stale_threshold:
                    stale_workers.append({
                        'id': w['id'],
                        'name': w.get('name'),
                        'last_checkin': last_checkin
                    })
            except (ValueError, TypeError):
                pass

    # Stack status: DB, Agent, Ollama, and other related containers (per memory.md)
    stack = _get_stack_status()

    return jsonify({
        'cluster_mode': CLUSTER_MODE,
        'checkin_interval': CHECKIN_INTERVAL,
        'stack': stack,
        'workers': {
            'total': len(workers),
            'online': worker_counts.get('online', 0),
            'offline': worker_counts.get('offline', 0),
            'busy': worker_counts.get('busy', 0),
            'by_status': worker_counts,
            'stale': stale_workers
        },
        'jobs': {
            'total': len(jobs),
            'queued': job_counts.get('queued', 0),
            'assigned': job_counts.get('assigned', 0),
            'running': job_counts.get('running', 0),
            'completed': job_counts.get('completed', 0),
            'failed': job_counts.get('failed', 0),
            'by_status': job_counts
        }
    })


def detect_stale_workers(mark_stale=False, requeue_jobs=False):
    """
    Detect workers that have missed check-ins.

    A worker is considered stale if no checkin received within 2x checkin_interval.

    Args:
        mark_stale: If True, update worker status to 'stale'
        requeue_jobs: If True, requeue jobs assigned to stale workers

    Returns:
        dict with stale_workers list and requeued_jobs list
    """
    if not storage_backend:
        return {'stale_workers': [], 'requeued_jobs': []}

    workers = storage_backend.get_all_workers()
    stale_threshold = datetime.now().timestamp() - (CHECKIN_INTERVAL * 2)

    stale_workers = []
    requeued_jobs = []

    for worker in workers:
        # Skip local worker
        if worker.get('is_local'):
            continue

        # Skip already offline/stale workers unless we're refreshing
        current_status = worker.get('status', 'unknown')
        if current_status in ('offline',) and not mark_stale:
            continue

        # Check last checkin time
        last_checkin = worker.get('last_checkin', '')
        is_stale = False

        if last_checkin:
            try:
                checkin_time = datetime.fromisoformat(last_checkin).timestamp()
                if checkin_time < stale_threshold:
                    is_stale = True
            except (ValueError, TypeError):
                # Invalid timestamp - consider stale if we can't parse it
                is_stale = True
        else:
            # No checkin recorded - worker just registered, give it time
            registered_at = worker.get('registered_at', '')
            if registered_at:
                try:
                    reg_time = datetime.fromisoformat(registered_at).timestamp()
                    if reg_time < stale_threshold:
                        is_stale = True
                except (ValueError, TypeError):
                    pass

        if is_stale:
            stale_info = {
                'id': worker['id'],
                'name': worker.get('name'),
                'last_checkin': last_checkin,
                'previous_status': current_status
            }
            stale_workers.append(stale_info)

            # Mark as stale if requested
            if mark_stale and current_status != 'stale':
                storage_backend.update_worker_status(worker['id'], 'stale')
                stale_info['marked_stale'] = True

                # Emit status change event
                socketio.emit('worker_status', {
                    'worker_id': worker['id'],
                    'name': worker.get('name'),
                    'status': 'stale',
                    'previous_status': current_status
                }, room='workers')

            # Requeue jobs if requested
            if requeue_jobs:
                worker_jobs = storage_backend.get_all_jobs({
                    'assigned_worker': worker['id'],
                    'status': ['assigned', 'running']
                })
                for job in worker_jobs:
                    storage_backend.update_job(job['id'], {
                        'status': 'queued',
                        'assigned_worker': None,
                        'assigned_at': None,
                        'started_at': None,
                        'error_message': f"Requeued: Worker {worker.get('name', worker['id'])} became stale"
                    })
                    requeued_jobs.append({
                        'job_id': job['id'],
                        'playbook': job.get('playbook'),
                        'previous_worker': worker['id']
                    })

                    # Emit job requeued event
                    socketio.emit('job_requeued', {
                        'job_id': job['id'],
                        'playbook': job.get('playbook'),
                        'reason': 'worker_stale',
                        'worker_id': worker['id']
                    }, room='jobs')

    return {
        'stale_workers': stale_workers,
        'requeued_jobs': requeued_jobs
    }


@app.route('/api/workers/stale', methods=['GET'])
@require_permission('workers:view')
def api_get_stale_workers():
    """
    Get list of stale workers.

    Returns workers that have missed check-ins (2x interval).
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    result = detect_stale_workers(mark_stale=False, requeue_jobs=False)
    return jsonify({
        'stale_workers': result['stale_workers'],
        'stale_threshold_seconds': CHECKIN_INTERVAL * 2
    })


@app.route('/api/workers/stale/handle', methods=['POST'])
@require_permission('workers:admin')
def api_handle_stale_workers():
    """
    Handle stale workers by marking them and requeuing their jobs.

    Optional JSON body:
    {
        "mark_stale": true,      // Update worker status to 'stale'
        "requeue_jobs": true     // Requeue jobs from stale workers
    }

    Returns list of affected workers and requeued jobs.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    data = request.get_json() or {}
    mark_stale = data.get('mark_stale', True)
    requeue_jobs = data.get('requeue_jobs', True)

    result = detect_stale_workers(mark_stale=mark_stale, requeue_jobs=requeue_jobs)

    return jsonify({
        'message': 'Stale workers handled',
        'stale_workers_found': len(result['stale_workers']),
        'jobs_requeued': len(result['requeued_jobs']),
        'details': result
    })


# =============================================================================
# Job Queue API (Cluster Support)
# =============================================================================

@app.route('/api/jobs', methods=['POST'])
@require_permission('jobs:submit')
def api_submit_job():
    """
    Submit a new job to the queue.

    Expected JSON body:
    {
        "playbook": "hardware-inventory.yml",
        "target": "webservers",
        "required_tags": ["network-a"],        // Optional: worker must have ALL tags
        "preferred_tags": ["high-memory"],     // Optional: prefer workers with tags
        "priority": 50,                        // Optional: 1-100, higher = more urgent
        "job_type": "normal",                  // Optional: "normal" or "long_running"
        "extra_vars": {"var1": "value"},       // Optional: extra vars for playbook
        "submitted_by": "user@example.com"     // Optional: who submitted
    }

    Returns:
    {
        "job_id": "uuid",
        "status": "queued",
        "message": "Job submitted successfully"
    }
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    data = request.get_json() or {}

    # Validate required fields
    playbook = data.get('playbook')
    if not playbook:
        return jsonify({'error': 'playbook is required'}), 400

    # Validate playbook exists
    available_playbooks = get_playbooks()
    if playbook not in available_playbooks:
        return jsonify({'error': f'Playbook not found: {playbook}'}), 400

    # Build job object
    job_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    job = {
        'id': job_id,
        'playbook': playbook,
        'target': data.get('target', 'all'),
        'required_tags': data.get('required_tags', []),
        'preferred_tags': data.get('preferred_tags', []),
        'priority': min(100, max(1, data.get('priority', 50))),
        'job_type': data.get('job_type', 'normal'),
        'extra_vars': data.get('extra_vars', {}),
        'status': 'queued',
        'assigned_worker': None,
        'submitted_by': data.get('submitted_by', 'api'),
        'submitted_at': now,
        'assigned_at': None,
        'started_at': None,
        'completed_at': None,
        'log_file': None,
        'exit_code': None,
        'error_message': None
    }

    # Validate job_type
    if job['job_type'] not in ('normal', 'long_running'):
        return jsonify({'error': 'job_type must be "normal" or "long_running"'}), 400

    # Save to storage
    if not storage_backend.save_job(job):
        return jsonify({'error': 'Failed to save job'}), 500

    return jsonify({
        'job_id': job_id,
        'status': 'queued',
        'message': 'Job submitted successfully'
    }), 201


@app.route('/api/jobs', methods=['GET'])
@require_permission('jobs:view')
def api_list_jobs():
    """
    List jobs with optional filters.

    Query parameters:
    - status: Filter by status (comma-separated, e.g., 'queued,running')
    - playbook: Filter by playbook name
    - worker: Filter by assigned worker ID
    - limit: Maximum number of results (default: 100)
    - offset: Skip first N results (default: 0)

    Returns list of job objects.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    # Build filters from query params
    filters = {}

    status_filter = request.args.get('status')
    if status_filter:
        filters['status'] = [s.strip() for s in status_filter.split(',')]

    playbook_filter = request.args.get('playbook')
    if playbook_filter:
        filters['playbook'] = playbook_filter

    worker_filter = request.args.get('worker')
    if worker_filter:
        filters['assigned_worker'] = worker_filter

    # Get jobs from storage
    jobs = storage_backend.get_all_jobs(filters)

    # Apply limit/offset
    limit = min(500, max(1, int(request.args.get('limit', 100))))
    offset = max(0, int(request.args.get('offset', 0)))

    total = len(jobs)
    jobs = jobs[offset:offset + limit]

    return jsonify({
        'jobs': jobs,
        'total': total,
        'limit': limit,
        'offset': offset
    })


@app.route('/api/jobs/<job_id>', methods=['GET'])
@require_permission('jobs:view')
def api_get_job(job_id):
    """Get a single job by ID."""
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    job = storage_backend.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    return jsonify(job)


@app.route('/api/jobs/<job_id>', methods=['DELETE'])
@require_permission('jobs:cancel')
def api_cancel_job(job_id):
    """
    Cancel a job.

    Only jobs with status 'queued' or 'assigned' can be cancelled.
    Running jobs will be marked for cancellation (worker must check).
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    job = storage_backend.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    current_status = job.get('status', '')

    if current_status in ('completed', 'failed', 'cancelled'):
        return jsonify({
            'error': f'Cannot cancel job with status: {current_status}'
        }), 400

    # Update job status
    updates = {
        'status': 'cancelled',
        'completed_at': datetime.now().isoformat(),
        'error_message': 'Job cancelled by user'
    }

    if not storage_backend.update_job(job_id, updates):
        return jsonify({'error': 'Failed to update job'}), 500

    return jsonify({
        'job_id': job_id,
        'status': 'cancelled',
        'message': 'Job cancelled successfully'
    })


@app.route('/api/jobs/<job_id>/log/stream', methods=['POST'])
@worker_auth_required
def api_stream_job_log(job_id):
    """
    Stream log content from worker during job execution.

    This endpoint allows workers to send partial log content while a job
    is running, enabling live log viewing in the web UI.

    Expected JSON body:
    {
        "worker_id": "worker-uuid",
        "content": "log content chunk...",
        "append": true,           // true to append, false to replace
        "offset": 0               // byte offset for append (optional)
    }

    The log content is written to a partial log file that is served
    to the web UI during execution.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    job = storage_backend.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    if job.get('status') not in ('assigned', 'running'):
        return jsonify({'error': 'Job is not running'}), 400

    data = request.get_json() or {}
    worker_id = data.get('worker_id')
    content = data.get('content', '')
    append = data.get('append', True)

    # Sanitize so passwords never stored or broadcast (defense-in-depth; worker should already redact)
    content_safe = '\n'.join(_sanitize_log_line(l) for l in content.split('\n'))

    # Verify worker owns this job
    if job.get('assigned_worker') != worker_id:
        return jsonify({'error': 'Worker does not own this job'}), 403

    # Create partial log filename
    partial_log_file = f"partial-{job_id}.log"
    partial_log_path = os.path.join(LOGS_DIR, partial_log_file)

    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        mode = 'a' if append else 'w'
        with open(partial_log_path, mode) as f:
            f.write(content_safe)

        # Update job with partial log reference if not set
        if not job.get('partial_log_file'):
            storage_backend.update_job(job_id, {'partial_log_file': partial_log_file})

        # Broadcast log update via WebSocket for live viewing
        if socketio:
            socketio.emit('job_log_update', {
                'job_id': job_id,
                'content': content_safe,
                'append': append
            }, room=f'job_{job_id}')

    except IOError as e:
        return jsonify({'error': f'Failed to write log: {str(e)}'}), 500

    return jsonify({
        'status': 'ok',
        'bytes_written': len(content_safe)
    })


@app.route('/api/jobs/<job_id>/log', methods=['GET'])
@require_permission('logs:view')
def api_get_job_log(job_id):
    """
    Get job execution log.

    Query parameters:
    - lines: Number of lines to return (default: all, use negative for tail)
    - format: 'text' (default) or 'json'

    Returns the job log content. During execution, returns partial log
    streamed from the worker. After completion, returns the full log.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    job = storage_backend.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    # Determine which log file to use
    # During execution, use partial log if available
    # After completion, use final log
    log_file = job.get('log_file')
    partial_log_file = job.get('partial_log_file')

    # For running jobs, prefer partial log
    if job.get('status') in ('assigned', 'running') and partial_log_file:
        log_path = os.path.join(LOGS_DIR, partial_log_file)
        if os.path.exists(log_path):
            log_file = partial_log_file

    if not log_file:
        return jsonify({
            'job_id': job_id,
            'status': job.get('status'),
            'log': None,
            'content': None,
            'message': 'No log file available (job may not have started)'
        })

    log_path = os.path.join(LOGS_DIR, log_file)

    if not os.path.exists(log_path):
        return jsonify({
            'job_id': job_id,
            'status': job.get('status'),
            'log': None,
            'content': None,
            'message': 'Log file not found'
        })

    # Read log file
    try:
        with open(log_path, 'r') as f:
            log_content = f.read()
    except IOError as e:
        return jsonify({'error': f'Failed to read log: {str(e)}'}), 500

    # Apply line limit if requested
    lines_param = request.args.get('lines')
    if lines_param:
        try:
            num_lines = int(lines_param)
            log_lines = log_content.splitlines()
            if num_lines < 0:
                # Tail: last N lines
                log_lines = log_lines[num_lines:]
            else:
                # Head: first N lines
                log_lines = log_lines[:num_lines]
            log_content = '\n'.join(log_lines)
        except ValueError:
            pass

    # Return format
    output_format = request.args.get('format', 'text')
    if output_format == 'json':
        return jsonify({
            'job_id': job_id,
            'status': job.get('status'),
            'log_file': log_file,
            'log': log_content,
            'lines': len(log_content.splitlines())
        })
    else:
        return log_content, 200, {'Content-Type': 'text/plain'}


@app.route('/api/jobs/pending', methods=['GET'])
@worker_auth_required
def api_get_pending_jobs():
    """
    Get pending jobs awaiting assignment.

    Used by workers to poll for available jobs.
    Returns jobs sorted by priority (highest first).
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    jobs = storage_backend.get_pending_jobs()
    return jsonify({'jobs': jobs})


@app.route('/api/jobs/<job_id>/assign', methods=['POST'])
@service_auth_required
def api_assign_job(job_id):
    """
    Assign a job to a worker.

    Expected JSON body:
    {
        "worker_id": "worker-uuid"
    }

    This is typically called by the job router, not directly by workers.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    data = request.get_json() or {}
    worker_id = data.get('worker_id')

    if not worker_id:
        return jsonify({'error': 'worker_id is required'}), 400

    # Verify worker exists
    worker = storage_backend.get_worker(worker_id)
    if not worker:
        return jsonify({'error': 'Worker not found'}), 404

    # Verify worker is available
    worker_status = worker.get('status', '')
    if worker_status not in ('online', 'busy'):
        return jsonify({
            'error': f'Worker not available (status: {worker_status})'
        }), 400

    # Get and verify job
    job = storage_backend.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    if job.get('status') != 'queued':
        return jsonify({
            'error': f'Job cannot be assigned (status: {job.get("status")})'
        }), 400

    # Assign the job
    updates = {
        'status': 'assigned',
        'assigned_worker': worker_id,
        'assigned_at': datetime.now().isoformat()
    }

    if not storage_backend.update_job(job_id, updates):
        return jsonify({'error': 'Failed to assign job'}), 500

    return jsonify({
        'job_id': job_id,
        'worker_id': worker_id,
        'status': 'assigned',
        'message': 'Job assigned successfully'
    })


@app.route('/api/jobs/<job_id>/start', methods=['POST'])
@worker_auth_required
def api_start_job(job_id):
    """
    Mark a job as started (called by worker when execution begins).

    Expected JSON body:
    {
        "worker_id": "worker-uuid",
        "log_file": "job-uuid-2024-01-01.log"  // Optional
    }
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    data = request.get_json() or {}
    worker_id = data.get('worker_id')

    if not worker_id:
        return jsonify({'error': 'worker_id is required'}), 400

    job = storage_backend.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    if job.get('assigned_worker') != worker_id:
        return jsonify({'error': 'Job not assigned to this worker'}), 403

    if job.get('status') not in ('assigned', 'running'):
        return jsonify({
            'error': f'Job cannot be started (status: {job.get("status")})'
        }), 400

    updates = {
        'status': 'running',
        'started_at': datetime.now().isoformat()
    }

    if data.get('log_file'):
        updates['log_file'] = data['log_file']

    if not storage_backend.update_job(job_id, updates):
        return jsonify({'error': 'Failed to update job'}), 500

    return jsonify({
        'job_id': job_id,
        'status': 'running',
        'message': 'Job started'
    })


@app.route('/api/jobs/<job_id>/complete', methods=['POST'])
@worker_auth_required
def api_complete_job(job_id):
    """
    Mark a job as completed (called by worker when execution finishes).

    Expected JSON body:
    {
        "worker_id": "worker-uuid",
        "exit_code": 0,
        "log_file": "job-uuid-2024-01-01.log",    // Optional: log filename on worker
        "log_content": "...",                      // Optional: full log content
        "error_message": null,                     // Optional: error details if failed
        "duration_seconds": 120,                   // Optional: execution duration
        "cmdb_facts": {                            // Optional: CMDB facts to store
            "hostname": {...},
            ...
        },
        "checkin": {                               // Optional: piggyback checkin data
            "sync_revision": "abc123",
            "system_stats": {...}
        }
    }

    Returns job status and updated worker statistics.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    data = request.get_json() or {}
    worker_id = data.get('worker_id')

    if not worker_id:
        return jsonify({'error': 'worker_id is required'}), 400

    job = storage_backend.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    if job.get('assigned_worker') != worker_id:
        return jsonify({'error': 'Job not assigned to this worker'}), 403

    exit_code = data.get('exit_code', 0)
    status = 'completed' if exit_code == 0 else 'failed'
    completed_at = datetime.now().isoformat()

    # Calculate duration if started_at is available
    duration_seconds = data.get('duration_seconds')
    if duration_seconds is None and job.get('started_at'):
        try:
            started = datetime.fromisoformat(job['started_at'])
            completed = datetime.fromisoformat(completed_at)
            duration_seconds = (completed - started).total_seconds()
        except (ValueError, TypeError):
            pass

    updates = {
        'status': status,
        'exit_code': exit_code,
        'completed_at': completed_at
    }

    if duration_seconds is not None:
        updates['duration_seconds'] = duration_seconds

    if data.get('log_file'):
        updates['log_file'] = data['log_file']

    if data.get('error_message'):
        updates['error_message'] = data['error_message']

    # Store log content if provided
    log_stored = False
    if data.get('log_content'):
        log_filename = data.get('log_file') or f"job-{job_id}-{completed_at[:10]}.log"
        log_path = os.path.join(LOGS_DIR, log_filename)
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            with open(log_path, 'w') as f:
                f.write(data['log_content'])
            updates['log_file'] = log_filename
            log_stored = True
        except Exception as e:
            print(f"Error storing log for job {job_id}: {e}")

    if not storage_backend.update_job(job_id, updates):
        return jsonify({'error': 'Failed to update job'}), 500

    # Update worker statistics
    worker = storage_backend.get_worker(worker_id)
    worker_stats_updated = False
    if worker:
        current_stats = worker.get('stats', {})

        # Update completion counts
        jobs_completed = current_stats.get('jobs_completed', 0)
        jobs_failed = current_stats.get('jobs_failed', 0)

        if status == 'completed':
            jobs_completed += 1
        else:
            jobs_failed += 1

        # Update average duration
        avg_duration = current_stats.get('avg_job_duration', 0)
        if duration_seconds is not None and jobs_completed > 0:
            # Running average
            total_jobs = jobs_completed + jobs_failed
            if total_jobs > 1:
                avg_duration = ((avg_duration * (total_jobs - 1)) + duration_seconds) / total_jobs
            else:
                avg_duration = duration_seconds

        updated_stats = {
            'jobs_completed': jobs_completed,
            'jobs_failed': jobs_failed,
            'avg_job_duration': round(avg_duration, 2),
            'last_job_completed': completed_at
        }

        # Merge with existing stats (preserve other fields like load, memory)
        merged_stats = {**current_stats, **updated_stats}

        # Update worker with new stats
        storage_backend.update_worker_checkin(worker_id, {'stats': merged_stats})
        worker_stats_updated = True

    # Process CMDB facts if provided
    cmdb_facts_stored = 0
    if data.get('cmdb_facts') and isinstance(data['cmdb_facts'], dict):
        for host, facts in data['cmdb_facts'].items():
            try:
                # Derive collection from playbook name
                playbook = job.get('playbook', 'unknown')
                collection = playbook.replace('.yml', '').replace('.yaml', '')

                # Add metadata
                facts_with_meta = {
                    **facts,
                    '_meta': {
                        'job_id': job_id,
                        'playbook': playbook,
                        'collected_at': completed_at,
                        'collector': 'job_completion'
                    }
                }

                storage_backend.save_host_facts(
                    host=host,
                    collection=collection,
                    data=facts_with_meta,
                    groups=[],
                    source='job'
                )
                cmdb_facts_stored += 1
            except Exception as e:
                print(f"Error storing CMDB facts for {host}: {e}")

    # Process piggyback checkin if provided
    checkin_processed = False
    if data.get('checkin') and isinstance(data['checkin'], dict):
        checkin_data = data['checkin']
        # Add completion status to checkin
        checkin_data['status'] = 'online' if not data.get('checkin', {}).get('status') else data['checkin']['status']
        storage_backend.update_worker_checkin(worker_id, checkin_data)
        checkin_processed = True

    # Emit job completion event
    socketio.emit('job_completed', {
        'job_id': job_id,
        'playbook': job.get('playbook'),
        'target': job.get('target'),
        'status': status,
        'exit_code': exit_code,
        'worker_id': worker_id,
        'duration_seconds': duration_seconds,
        'completed_at': completed_at
    }, room='jobs')

    # Trigger Agent Review (Fire and Forget)
    # Set AGENT_TRIGGER_ENABLED=false to disable (e.g. if host Ollama keeps starting; helps isolate cause)
    if AGENT_SERVICE_URL and os.environ.get('AGENT_TRIGGER_ENABLED', 'true').lower() in ('1', 'true', 'yes'):
        def trigger_agent_async():
            try:
                r = requests.post(
                    f"{AGENT_SERVICE_URL}/trigger/log-review",
                    json={'job_id': job_id, 'exit_code': exit_code},
                    timeout=10
                )
                if r.status_code == 200:
                    print(f"Agent review triggered for job {job_id}")
                else:
                    print(f"Agent trigger returned {r.status_code} for job {job_id}: {r.text[:200]}")
            except Exception as e:
                print(f"Failed to trigger agent review for job {job_id}: {e}")
        
        threading.Thread(target=trigger_agent_async, daemon=True).start()

    return jsonify({
        'job_id': job_id,
        'status': status,
        'exit_code': exit_code,
        'duration_seconds': duration_seconds,
        'message': f'Job {status}',
        'log_stored': log_stored,
        'worker_stats_updated': worker_stats_updated,
        'cmdb_facts_stored': cmdb_facts_stored,
        'checkin_processed': checkin_processed
    })


# =============================================================================
# Job Routing API (Cluster Support)
# =============================================================================

def get_job_router():
    """Get or create the job router instance."""
    from job_router import JobRouter
    return JobRouter(storage_backend)


@app.route('/api/jobs/route', methods=['POST'])
@service_auth_required
def api_route_pending_jobs():
    """
    Route pending jobs to available workers.

    Query parameters:
    - limit: Maximum number of jobs to route (default: 10)

    Returns list of routing results.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    limit = min(50, max(1, int(request.args.get('limit', 10))))
    router = get_job_router()

    results = router.route_pending_jobs(limit)

    assigned_count = sum(1 for r in results if r.get('assigned'))

    return jsonify({
        'routed': len(results),
        'assigned': assigned_count,
        'results': results
    })


@app.route('/api/jobs/<job_id>/route', methods=['POST'])
@service_auth_required
def api_route_specific_job(job_id):
    """
    Route a specific job to a worker.

    Finds the best available worker and assigns the job.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    router = get_job_router()
    result = router.route_job(job_id)

    if result.get('error'):
        return jsonify(result), 400

    return jsonify(result)


@app.route('/api/jobs/<job_id>/recommendations', methods=['GET'])
@require_permission('workers:admin')
def api_job_worker_recommendations(job_id):
    """
    Get worker recommendations for a job.

    Returns ranked list of workers with eligibility and scores.
    """
    if not storage_backend:
        return jsonify({'error': 'Storage backend not initialized'}), 500

    job = storage_backend.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    router = get_job_router()
    recommendations = router.get_worker_recommendations(job_id)

    return jsonify({
        'job_id': job_id,
        'playbook': job.get('playbook'),
        'required_tags': job.get('required_tags', []),
        'preferred_tags': job.get('preferred_tags', []),
        'recommendations': recommendations
    })


# =============================================================================
# Content Sync API (Cluster Support)
# =============================================================================

@app.route('/api/sync/status', methods=['GET'])
@require_permission('workers:view')
def api_sync_status():
    """
    Get content repository status.

    Returns:
    {
        "initialized": true,
        "revision": "abc123...",
        "short_revision": "abc123",
        "has_uncommitted_changes": false,
        "tracked_files": 15,
        "tracked_dirs": ["playbooks", "inventory", ...]
    }
    """
    repo = get_content_repo(CONTENT_DIR)

    if not repo.is_initialized():
        return jsonify({
            'initialized': False,
            'error': 'Content repository not initialized'
        })

    return jsonify(repo.get_status())


@app.route('/api/sync/revision', methods=['GET'])
@worker_auth_required
def api_sync_revision():
    """
    Get current content revision (HEAD SHA).

    Used by workers to check if they need to sync.
    Checks for uncommitted changes and commits them first.

    Returns:
    {
        "revision": "abc123def456...",
        "short_revision": "abc123"
    }
    """
    repo = get_content_repo(CONTENT_DIR)

    if not repo.is_initialized():
        return jsonify({'error': 'Content repository not initialized'}), 500

    # Auto-commit any changes detected
    if repo.has_changes():
        try:
            repo.commit_changes("Auto-commit from sync check")
        except Exception as e:
            print(f"Error auto-committing changes: {e}")

    revision = repo.get_current_revision()
    return jsonify({
        'revision': revision,
        'short_revision': revision[:7] if revision else None
    })


@app.route('/api/sync/manifest', methods=['GET'])
@worker_auth_required
def api_sync_manifest():
    """
    Get file manifest with checksums.

    Used by workers to verify sync state and identify changed files.
    Checks for uncommitted changes and commits them first.

    Returns:
    {
        "revision": "abc123...",
        "files": {
            "playbooks/test.yml": {
                "size": 1234,
                "sha256": "...",
                "mtime": "2024-01-01T12:00:00"
            },
            ...
        }
    }
    """
    repo = get_content_repo(CONTENT_DIR)

    if not repo.is_initialized():
        return jsonify({'error': 'Content repository not initialized'}), 500

    # Auto-commit any changes detected
    if repo.has_changes():
        try:
            repo.commit_changes("Auto-commit from sync manifest")
        except Exception as e:
            print(f"Error auto-committing changes: {e}")

    return jsonify({
        'revision': repo.get_current_revision(),
        'files': repo.get_file_manifest()
    })


@app.route('/api/sync/archive', methods=['GET'])
@worker_auth_required
def api_sync_archive():
    """
    Download content archive (tar.gz).

    Used by workers for initial sync or full re-sync.

    Returns:
        tar.gz file of all tracked content
    """
    repo = get_content_repo(CONTENT_DIR)

    if not repo.is_initialized():
        return jsonify({'error': 'Content repository not initialized'}), 500

    archive_path = repo.create_archive()
    if not archive_path:
        return jsonify({'error': 'Failed to create archive'}), 500

    try:
        return send_file(
            archive_path,
            mimetype='application/gzip',
            as_attachment=True,
            download_name=f'ansible-content-{repo.get_short_revision()}.tar.gz'
        )
    finally:
        # Clean up temp archive after sending
        if os.path.exists(archive_path):
            os.remove(archive_path)


@app.route('/api/sync/file/<path:filepath>', methods=['GET'])
@worker_auth_required
def api_sync_file(filepath):
    """
    Download a single file from the content repository.

    Used by workers for incremental sync of changed files.

    Args:
        filepath: Relative path within content dir (e.g., "playbooks/test.yml")

    Returns:
        File content with appropriate mime type
    """
    repo = get_content_repo(CONTENT_DIR)

    if not repo.is_initialized():
        return jsonify({'error': 'Content repository not initialized'}), 500

    # Security: Validate path is within tracked directories
    allowed_prefixes = repo.TRACKED_DIRS + repo.TRACKED_FILES
    path_ok = False
    for prefix in allowed_prefixes:
        if filepath == prefix or filepath.startswith(prefix + '/'):
            path_ok = True
            break

    if not path_ok:
        return jsonify({'error': 'File not in tracked content'}), 403

    # Resolve full path and check for traversal attacks
    full_path = os.path.normpath(os.path.join(CONTENT_DIR, filepath))
    if not full_path.startswith(os.path.normpath(CONTENT_DIR)):
        return jsonify({'error': 'Invalid path'}), 403

    if not os.path.isfile(full_path):
        return jsonify({'error': 'File not found'}), 404

    # Determine mime type
    if filepath.endswith('.yml') or filepath.endswith('.yaml'):
        mimetype = 'text/yaml'
    elif filepath.endswith('.py'):
        mimetype = 'text/x-python'
    elif filepath.endswith('.cfg') or filepath.endswith('.ini'):
        mimetype = 'text/plain'
    else:
        mimetype = 'application/octet-stream'

    return send_file(full_path, mimetype=mimetype)


@app.route('/api/sync/history', methods=['GET'])
@require_permission('config:view')
def api_sync_history():
    """
    Get content commit history.

    Query parameters:
    - limit: Maximum number of entries (default 10)

    Returns:
    {
        "commits": [
            {
                "sha": "abc123...",
                "message": "Updated playbook",
                "date": "2024-01-01 12:00:00 +0000",
                "author": "Ansible SimpleWeb"
            },
            ...
        ]
    }
    """
    repo = get_content_repo(CONTENT_DIR)

    if not repo.is_initialized():
        return jsonify({'error': 'Content repository not initialized'}), 500

    limit = request.args.get('limit', 10, type=int)
    commits = repo.get_commit_log(limit=limit)

    return jsonify({'commits': commits})


@app.route('/api/sync/commit', methods=['POST'])
@require_permission('config:edit')
def api_sync_commit():
    """
    Manually commit current content state.

    Used to explicitly commit after file uploads/changes.

    Request body (optional):
    {
        "message": "Custom commit message"
    }

    Returns:
    {
        "revision": "abc123...",
        "message": "Content committed successfully"
    }
    """
    repo = get_content_repo(CONTENT_DIR)

    if not repo.is_initialized():
        return jsonify({'error': 'Content repository not initialized'}), 500

    data = request.get_json() or {}
    message = data.get('message')

    if not repo.has_changes():
        return jsonify({
            'revision': repo.get_current_revision(),
            'message': 'No changes to commit'
        })

    new_revision = repo.commit_changes(message)
    if not new_revision:
        return jsonify({'error': 'Failed to commit changes'}), 500

    # Notify workers of new content
    socketio.emit('sync_available', {
        'revision': new_revision,
        'short_revision': new_revision[:7]
    }, room='workers')

    return jsonify({
        'revision': new_revision,
        'message': 'Content committed successfully'
    })


# WebSocket handlers for cluster events
@socketio.on('join_workers')
def handle_join_workers():
    """Join the workers room for real-time worker updates"""
    join_room('workers')


@socketio.on('leave_workers')
def handle_leave_workers():
    """Leave the workers room"""
    leave_room('workers')


# WebSocket event handlers
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    # Automatically join the status room for updates
    join_room('status')

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    leave_room('status')

@socketio.on('join_run')
def handle_join_run(data):
    """Join a specific run's room to receive log updates"""
    run_id = data.get('run_id')
    if run_id:
        join_room(f'run:{run_id}')
        # Send current log content for catch-up
        with runs_lock:
            run_info = active_runs.get(run_id)

        if run_info:
            log_file = run_info.get('log_file')
            if log_file:
                log_path = os.path.join(LOGS_DIR, log_file)
                if os.path.exists(log_path):
                    with open(log_path, 'r') as f:
                        content = f.read()
                    emit('log_catchup', {
                        'content': content,
                        'status': run_info['status'],
                        'run_id': run_id
                    })

@socketio.on('leave_run')
def handle_leave_run(data):
    """Leave a specific run's room"""
    run_id = data.get('run_id')
    if run_id:
        leave_room(f'run:{run_id}')


@socketio.on('join_schedules')
def handle_join_schedules():
    """Join the schedules room for real-time schedule updates"""
    join_room('schedules')


@socketio.on('leave_schedules')
def handle_leave_schedules():
    """Leave the schedules room"""
    leave_room('schedules')


@socketio.on('join_batch_jobs')
def handle_join_batch_jobs():
    """Join the batch_jobs room for real-time batch job updates"""
    join_room('batch_jobs')


@socketio.on('leave_batch_jobs')
def handle_leave_batch_jobs():
    """Leave the batch_jobs room"""
    leave_room('batch_jobs')


@socketio.on('join_batch')
def handle_join_batch(data):
    """Join a specific batch job's room to receive log updates"""
    batch_id = data.get('batch_id')
    if batch_id:
        join_room(f'batch:{batch_id}')
        # Send current status for catch-up
        batch_job = get_batch_job_status(batch_id)
        if batch_job:
            emit('batch_catchup', {
                'batch_id': batch_id,
                'status': batch_job.get('status'),
                'completed': batch_job.get('completed', 0),
                'failed': batch_job.get('failed', 0),
                'total': batch_job.get('total', 0),
                'current_playbook': batch_job.get('current_playbook'),
                'results': batch_job.get('results', []),
                'worker_name': batch_job.get('worker_name')
            })

            # Send log catchup for completed/in-progress playbooks
            results = batch_job.get('results', [])
            for result in results:
                playbook = result.get('playbook')
                log_file = result.get('log_file')
                job_id = result.get('job_id')

                # Try to read from final log file first, then partial log
                log_content = None
                if log_file:
                    log_path = os.path.join(LOGS_DIR, log_file)
                    if os.path.exists(log_path):
                        try:
                            with open(log_path, 'r') as f:
                                log_content = f.read()
                        except:
                            pass

                if not log_content and job_id:
                    # Try partial log
                    partial_path = os.path.join(LOGS_DIR, f'partial-{job_id}.log')
                    if os.path.exists(partial_path):
                        try:
                            with open(partial_path, 'r') as f:
                                log_content = f.read()
                        except:
                            pass

                if log_content:
                    # Send log lines for this playbook
                    for line in log_content.splitlines(keepends=True):
                        emit('batch_log_line', {
                            'batch_id': batch_id,
                            'playbook': playbook,
                            'line': line
                        })

            # Also check for current running job's partial log
            current_job_id = batch_job.get('current_job_id')
            current_playbook = batch_job.get('current_playbook')
            if current_job_id and current_playbook and batch_job.get('status') == 'running':
                partial_path = os.path.join(LOGS_DIR, f'partial-{current_job_id}.log')
                if os.path.exists(partial_path):
                    try:
                        with open(partial_path, 'r') as f:
                            log_content = f.read()
                            for line in log_content.splitlines(keepends=True):
                                emit('batch_log_line', {
                                    'batch_id': batch_id,
                                    'playbook': current_playbook,
                                    'line': line
                                })
                    except:
                        pass


@socketio.on('leave_batch')
def handle_leave_batch(data):
    """Leave a specific batch job's room"""
    batch_id = data.get('batch_id')
    if batch_id:
        leave_room(f'batch:{batch_id}')


@socketio.on('join_job')
def handle_join_job(data):
    """
    Join a specific cluster job's room to receive live log updates.

    This is used for jobs executed on remote workers. Workers stream
    log content to the primary, which broadcasts to connected clients.
    """
    job_id = data.get('job_id')
    if job_id:
        join_room(f'job_{job_id}')

        # Send current log content for catch-up
        if storage_backend:
            job = storage_backend.get_job(job_id)
            if job:
                # Check for partial log (during execution)
                partial_log_file = job.get('partial_log_file')
                log_file = job.get('log_file')

                log_content = None
                log_path = None

                # Prefer partial log for running jobs
                if job.get('status') in ('assigned', 'running') and partial_log_file:
                    log_path = os.path.join(LOGS_DIR, partial_log_file)
                elif log_file:
                    log_path = os.path.join(LOGS_DIR, log_file)

                if log_path and os.path.exists(log_path):
                    try:
                        with open(log_path, 'r') as f:
                            log_content = f.read()
                    except IOError:
                        pass

                emit('job_log_catchup', {
                    'job_id': job_id,
                    'content': log_content or '',
                    'status': job.get('status')
                })


@socketio.on('leave_job')
def handle_leave_job(data):
    """Leave a specific cluster job's room"""
    job_id = data.get('job_id')
    if job_id:
        leave_room(f'job_{job_id}')



# -----------------------------------------------------------------------------
# Agent Integration Routes
# -----------------------------------------------------------------------------

AGENT_SERVICE_URL = os.environ.get('AGENT_SERVICE_URL', 'http://agent-service:5000')


# =============================================================================
# Deployment status and bootstrap (Stage 4)
# =============================================================================

@app.route('/api/deployment/status', methods=['GET'])
@require_permission('config:view')
def api_deployment_status():
    """
    Return desired vs current services and deployment delta (what needs to be deployed).
    Used by Config panel and bootstrap logic.
    """
    try:
        from deployment import get_deployment_delta
        delta = get_deployment_delta(storage_backend=storage_backend)
        return jsonify({
            'desired': delta.get('desired', {}),
            'current': delta.get('current', {}),
            'deploy_db': delta.get('deploy_db', False),
            'deploy_agent': delta.get('deploy_agent', False),
            'deploy_workers': delta.get('deploy_workers', False),
            'worker_count_to_add': delta.get('worker_count_to_add', 0),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/deployment/run', methods=['POST'])
@admin_required
def api_deployment_run():
    """
    Run deployment playbook for current delta (bootstrap or expand).
    Requires ansible-playbook and (for docker) Docker socket in container.
    """
    try:
        from deployment import get_deployment_delta, run_bootstrap
        delta = get_deployment_delta(storage_backend=storage_backend)
        success, message = run_bootstrap(delta)
        if success:
            return jsonify({'ok': True, 'message': message})
        return jsonify({'ok': False, 'error': message}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/config')
@require_permission('config:view')
def config_page():
    """Config panel: view/edit app config, backup/restore config and data."""
    return render_template('config.html')


@app.route('/agent')
@require_permission('agent:view')
def agent_dashboard():
    """Render Agent Dashboard."""
    return render_template('agent.html')

@app.route('/api/agent/overview')
@require_permission('agent:view')
def agent_overview():
    """Proxy to get agent health status."""
    try:
        resp = requests.get(f"{AGENT_SERVICE_URL}/health", timeout=5)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'offline'}), 503

@app.route('/api/agent/reviews')
@require_permission('agent:view')
def agent_reviews():
    """Proxy to get recent log reviews."""
    try:
        resp = requests.get(f"{AGENT_SERVICE_URL}/agent/reviews", timeout=5)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/agent/reviews/<job_id>')
@require_permission('agent:view')
def agent_get_review(job_id):
    """Proxy to get specific review."""
    try:
        resp = requests.get(f"{AGENT_SERVICE_URL}/reviews/{job_id}", timeout=5)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/agent/review-status/<job_id>')
@require_permission('agent:view')
def agent_review_status(job_id):
    """Proxy to get review status only (pending | running | completed | error) for polling."""
    try:
        resp = requests.get(f"{AGENT_SERVICE_URL}/review-status/{job_id}", timeout=5)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/agent/review-stats')
@require_permission('agent:view')
def agent_review_stats():
    """Proxy to get avg response time for agent reviews."""
    try:
        resp = requests.get(f"{AGENT_SERVICE_URL}/review-stats", timeout=5)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'avg_response_time_seconds': 0, 'count': 0, 'error': str(e)}), 200


@app.route('/api/agent/review-ready', methods=['POST'])
@service_auth_required
def agent_review_ready():
    """Called by agent when a review is ready; push to UI via socket so clients don't need to poll."""
    try:
        data = request.get_json() or {}
        job_id = data.get('job_id')
        status = data.get('status', 'completed')
        if not job_id:
            return jsonify({'error': 'job_id required'}), 400
        room = f'job_{job_id}'
        if socketio:
            socketio.emit('agent_review_ready', {'job_id': job_id, 'status': status}, room=room)
        return jsonify({'ok': True, 'room': room})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/agent/proposals')
@require_permission('agent:view')
def agent_proposals():
    """Proxy to get recent playbook proposals."""
    try:
        resp = requests.get(f"{AGENT_SERVICE_URL}/agent/proposals", timeout=5)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/agent/reports')
@require_permission('agent:view')
def agent_reports():
    """Proxy to get recent config reports."""
    try:
        resp = requests.get(f"{AGENT_SERVICE_URL}/agent/reports", timeout=5)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/agent/generate', methods=['POST'])
@require_permission('agent:generate')
def agent_generate():
    """Proxy to generate playbook."""
    try:
        resp = requests.post(
            f"{AGENT_SERVICE_URL}/agent/generate", 
            json=request.get_json(),
            timeout=60 # LLM can be slow
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/agent/analyze-config', methods=['POST'])
@require_permission('agent:analyze')
def agent_analyze_config():
    """Proxy to analyze config."""
    try:
        resp = requests.post(
            f"{AGENT_SERVICE_URL}/agent/analyze-config", 
            json=request.get_json(),
            timeout=30
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Initialize storage backend
    storage_backend = get_storage_backend()
    backend_type = storage_backend.get_backend_type()
    print(f"Storage backend initialized: {backend_type}")
    if storage_backend.health_check():
        print(f"Storage backend health check: OK")
    else:
        print(f"WARNING: Storage backend health check failed!")

    # Register auth blueprint
    app.register_blueprint(auth_bp)
    print(f"Auth blueprint registered")

    # Initialize authentication middleware
    init_auth_middleware(app, storage_backend, auth_enabled=AUTH_ENABLED)
    print(f"Authentication {'ENABLED' if AUTH_ENABLED else 'DISABLED'}")

    # Bootstrap admin user if auth is enabled and no users exist
    if AUTH_ENABLED:
        bootstrap_admin_user(storage_backend)

    # Initial inventory sync: DB <-> static so workers get all hosts
    _run_inventory_sync()

    # Initialize cluster support
    print(f"Cluster mode: {CLUSTER_MODE}")
    if CLUSTER_MODE in ('standalone', 'primary'):
        init_local_worker()

        # Initialize content repository for syncing to workers
        content_repo = get_content_repo(CONTENT_DIR)
        if content_repo.init_repo():
            status = content_repo.get_status()
            print(f"Content repository initialized: {status['short_revision'] or 'empty'}")
            print(f"  Tracked files: {status['tracked_files']}")
        else:
            print("WARNING: Content repository initialization failed")

    # Initialize the schedule manager with storage backend and managed inventory functions
    schedule_manager = ScheduleManager(
        socketio=socketio,
        run_playbook_fn=run_playbook_streaming,
        active_runs=active_runs,
        runs_lock=runs_lock,
        storage=storage_backend,
        is_managed_host_fn=is_managed_host,
        generate_managed_inventory_fn=generate_managed_inventory,
        create_batch_job_fn=create_batch_job,
        # Cluster dispatch functions for scheduled jobs
        use_cluster_dispatch_fn=_should_use_cluster_dispatch,
        submit_cluster_job_fn=_submit_cluster_job,
        wait_for_job_completion_fn=_wait_for_job_completion,
        get_worker_name_fn=_get_worker_name
    )
    schedule_manager.start()
    print("Schedule manager initialized and started")

    # Periodic inventory sync: DB <-> static (every 5 minutes)
    from apscheduler.triggers.interval import IntervalTrigger
    schedule_manager.scheduler.add_job(
        _run_inventory_sync,
        trigger=IntervalTrigger(minutes=5),
        id='inventory_sync',
        name='Inventory sync (DB <-> static)',
        replace_existing=True
    )
    print("Inventory sync job registered (every 5 minutes)")

    # Bootstrap: if config requests DB/agent/workers but they are not deployed, run deploy playbook (background)
    def _bootstrap_if_needed():
        try:
            from deployment import get_deployment_delta, run_bootstrap
            delta = get_deployment_delta(storage_backend=storage_backend)
            if delta.get('deploy_db') or delta.get('deploy_agent') or delta.get('deploy_workers'):
                print("Bootstrap: config requests services not yet deployed, running deploy playbook...")
                ok, msg = run_bootstrap(delta)
                print(f"Bootstrap: {'OK' if ok else 'Failed'} - {msg}")
        except Exception as e:
            print(f"Bootstrap: {e}")
    _bootstrap_thread = threading.Thread(target=_bootstrap_if_needed, daemon=True)
    _bootstrap_thread.start()

    # Use socketio.run instead of app.run for WebSocket support
    socketio.run(app, host='0.0.0.0', port=3001, debug=True)
