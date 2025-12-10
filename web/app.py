from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
import glob
import json
import subprocess
import threading
import time
import uuid
from datetime import datetime

# Import scheduler components (initialized after app creation)
from scheduler import ScheduleManager, build_recurrence_config

# Import storage backend
from storage import get_storage_backend

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ansible-simpleweb-dev-key')

# Initialize SocketIO with eventlet for async support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Paths
PLAYBOOKS_DIR = '/app/playbooks'
LOGS_DIR = '/app/logs'
RUN_SCRIPT = '/app/run-playbook.sh'
INVENTORY_FILE = '/app/inventory/hosts'
THEMES_DIR = '/app/config/themes'

# Track running playbooks by run_id
# Structure: {run_id: {playbook, target, status, started, log_file, ...}}
active_runs = {}

# Lock for thread-safe access to active_runs
runs_lock = threading.Lock()

# Schedule manager (initialized in main block)
schedule_manager = None

# Storage backend (initialized in main block)
storage_backend = None

def get_inventory_targets():
    """Parse inventory file and get available hosts and groups"""
    targets = []

    if not os.path.exists(INVENTORY_FILE):
        return ['host_machine']  # Default fallback

    try:
        with open(INVENTORY_FILE, 'r') as f:
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
                    if ':children' not in group_name:
                        current_group = group_name
                        targets.append({
                            'value': group_name,
                            'label': f'{group_name} (group)',
                            'type': 'group'
                        })
                # Individual host line
                elif current_group and not line.startswith('['):
                    # Extract hostname (first part before space)
                    hostname = line.split()[0]
                    if hostname and not hostname.startswith('#'):
                        targets.append({
                            'value': hostname,
                            'label': f'{hostname}',
                            'type': 'host'
                        })

        # Add special targets
        if targets:
            targets.insert(0, {
                'value': 'all',
                'label': 'all (all hosts)',
                'type': 'special'
            })

    except Exception as e:
        print(f"Error parsing inventory: {e}")
        return [{'value': 'host_machine', 'label': 'host_machine (group)', 'type': 'group'}]

    return targets if targets else [{'value': 'host_machine', 'label': 'host_machine (group)', 'type': 'group'}]

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

def run_playbook_streaming(run_id, playbook_name, target, log_file):
    """Run playbook with real-time streaming to WebSocket and log file"""
    log_path = os.path.join(LOGS_DIR, log_file)

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
            'status': 'running'
        }, room='status')

        # Start the playbook process in stream mode
        cmd = ['bash', RUN_SCRIPT, '--stream', playbook_name, '-l', target]
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
            # Write header
            header = f"=== Playbook: {playbook_name} | Target: {target} | Started: {datetime.now().isoformat()} ===\n"
            log_f.write(header)
            log_f.flush()
            socketio.emit('log_line', {'line': header, 'run_id': run_id}, room=f'run:{run_id}')

            # Stream output line by line
            for line in process.stdout:
                # Write to file first (crash protection)
                log_f.write(line)
                log_f.flush()
                os.fsync(log_f.fileno())  # Force OS to write to disk

                # Then emit to WebSocket
                socketio.emit('log_line', {'line': line, 'run_id': run_id}, room=f'run:{run_id}')

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
            'status': status
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
            'status': 'failed'
        }, room='status')

@app.route('/')
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

@app.route('/run/<playbook_name>')
def run_playbook(playbook_name):
    """Trigger playbook execution with streaming"""
    if playbook_name not in get_playbooks():
        return jsonify({'error': 'Playbook not found'}), 404

    # Get target from query parameter, default to host_machine
    target = request.args.get('target', 'host_machine')

    # Check if this playbook+target combination is already running
    is_running, existing_run_id = is_playbook_target_running(playbook_name, target)
    if is_running:
        # Redirect to watch the existing run instead of error
        return redirect(url_for('live_log', run_id=existing_run_id))

    # Generate unique run ID and log filename
    run_id = str(uuid.uuid4())
    log_file = generate_log_filename(playbook_name, target, run_id)

    # Register the run
    with runs_lock:
        active_runs[run_id] = {
            'playbook': playbook_name,
            'target': target,
            'status': 'starting',
            'started': datetime.now().isoformat(),
            'log_file': log_file
        }

    # Start playbook in background thread with streaming
    thread = threading.Thread(
        target=run_playbook_streaming,
        args=(run_id, playbook_name, target, log_file)
    )
    thread.daemon = True
    thread.start()

    # Redirect to live log view
    return redirect(url_for('live_log', run_id=run_id))

@app.route('/live/<run_id>')
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
                          log_file=run_info.get('log_file', ''))

@app.route('/logs')
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
def view_log(log_file):
    """View a specific log file"""
    log_path = os.path.join(LOGS_DIR, log_file)
    if not os.path.exists(log_path):
        return "Log file not found", 404

    # Read log file
    with open(log_path, 'r') as f:
        content = f.read()

    return render_template('log_view.html', log_file=log_file, content=content)

@app.route('/api/status')
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
def api_runs():
    """Get all active runs"""
    with runs_lock:
        # Filter out process objects (not serializable)
        runs = {}
        for run_id, run_info in active_runs.items():
            runs[run_id] = {k: v for k, v in run_info.items() if k != 'process'}
    return jsonify(runs)

@app.route('/api/runs/<run_id>')
def api_run_detail(run_id):
    """Get details of a specific run"""
    with runs_lock:
        run_info = active_runs.get(run_id)
        if run_info:
            return jsonify({k: v for k, v in run_info.items() if k != 'process'})
    return jsonify({'error': 'Run not found'}), 404

@app.route('/api/runs/<run_id>/log')
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
# Theme API Endpoints
# Serves theme configuration from config/themes/*.json files
# Used by web/static/js/theme.js to load and apply themes
# =============================================================================

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
# Storage API Endpoints
# Information about the active storage backend
# =============================================================================

@app.route('/api/storage')
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
# Inventory API Endpoints
# CRUD operations for managed inventory items (hosts/servers)
# Stored via the pluggable storage backend (flatfile or MongoDB)
# =============================================================================

@app.route('/api/inventory')
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
        return jsonify(item), 201
    else:
        return jsonify({'error': 'Failed to save inventory item'}), 500


@app.route('/api/inventory/<item_id>', methods=['PUT'])
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
        return jsonify(existing)
    else:
        return jsonify({'error': 'Failed to update inventory item'}), 500


@app.route('/api/inventory/<item_id>', methods=['DELETE'])
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
        return jsonify({'success': True, 'deleted': item_id})
    else:
        return jsonify({'error': 'Inventory item not found'}), 404


@app.route('/api/inventory/search', methods=['POST'])
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
# Schedule Routes
# Playbook scheduling with APScheduler backend
# =============================================================================

@app.route('/schedules')
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
def new_schedule():
    """Form to create a new schedule"""
    playbooks = get_playbooks()
    targets = get_inventory_targets()

    # Pre-select playbook if provided in query param
    selected_playbook = request.args.get('playbook', '')

    return render_template('schedule_form.html',
                          playbooks=playbooks,
                          targets=targets,
                          selected_playbook=selected_playbook,
                          edit_mode=False,
                          schedule=None)


@app.route('/schedules/create', methods=['POST'])
def create_schedule():
    """Create a new schedule from form submission"""
    if not schedule_manager:
        return "Scheduler not initialized", 500

    playbook = request.form.get('playbook')
    target = request.form.get('target', 'host_machine')
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()

    # Validate required fields
    if not playbook or playbook not in get_playbooks():
        return "Invalid playbook", 400
    if not name:
        name = f"{playbook} - {target}"

    # Build recurrence config from form data
    recurrence_config = build_recurrence_config(request.form)

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
def edit_schedule(schedule_id):
    """Form to edit an existing schedule"""
    if not schedule_manager:
        return "Scheduler not initialized", 500

    schedule = schedule_manager.get_schedule(schedule_id)
    if not schedule:
        return "Schedule not found", 404

    playbooks = get_playbooks()
    targets = get_inventory_targets()

    return render_template('schedule_form.html',
                          playbooks=playbooks,
                          targets=targets,
                          selected_playbook=schedule['playbook'],
                          edit_mode=True,
                          schedule=schedule)


@app.route('/schedules/<schedule_id>/update', methods=['POST'])
def update_schedule(schedule_id):
    """Update an existing schedule"""
    if not schedule_manager:
        return "Scheduler not initialized", 500

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

    schedule_manager.update_schedule(schedule_id, updates)
    return redirect(url_for('schedules_page'))


@app.route('/schedules/<schedule_id>/history')
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
def api_schedules():
    """Get all schedules as JSON"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    return jsonify(schedule_manager.get_all_schedules())


@app.route('/api/schedules/<schedule_id>')
def api_schedule_detail(schedule_id):
    """Get a single schedule"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    schedule = schedule_manager.get_schedule(schedule_id)
    if not schedule:
        return jsonify({'error': 'Schedule not found'}), 404
    return jsonify(schedule)


@app.route('/api/schedules/<schedule_id>/pause', methods=['POST'])
def api_pause_schedule(schedule_id):
    """Pause a schedule"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    success = schedule_manager.pause_schedule(schedule_id)
    return jsonify({'success': success})


@app.route('/api/schedules/<schedule_id>/resume', methods=['POST'])
def api_resume_schedule(schedule_id):
    """Resume a paused schedule"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    success = schedule_manager.resume_schedule(schedule_id)
    return jsonify({'success': success})


@app.route('/api/schedules/<schedule_id>/delete', methods=['POST'])
def api_delete_schedule(schedule_id):
    """Delete a schedule"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    success = schedule_manager.delete_schedule(schedule_id)
    return jsonify({'success': success})


@app.route('/api/schedules/<schedule_id>/stop', methods=['POST'])
def api_stop_schedule(schedule_id):
    """Stop a currently running scheduled job"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    success = schedule_manager.stop_running_job(schedule_id)
    return jsonify({'success': success})


@app.route('/api/schedules/<schedule_id>/history')
def api_schedule_history(schedule_id):
    """Get execution history for a schedule"""
    if not schedule_manager:
        return jsonify({'error': 'Scheduler not initialized'}), 500

    limit = request.args.get('limit', 50, type=int)
    history = schedule_manager.get_schedule_history(schedule_id, limit=limit)
    return jsonify(history)


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


if __name__ == '__main__':
    # Initialize storage backend
    storage_backend = get_storage_backend()
    backend_type = storage_backend.get_backend_type()
    print(f"Storage backend initialized: {backend_type}")
    if storage_backend.health_check():
        print(f"Storage backend health check: OK")
    else:
        print(f"WARNING: Storage backend health check failed!")

    # Initialize the schedule manager with storage backend
    schedule_manager = ScheduleManager(
        socketio=socketio,
        run_playbook_fn=run_playbook_streaming,
        active_runs=active_runs,
        runs_lock=runs_lock,
        storage=storage_backend
    )
    schedule_manager.start()
    print("Schedule manager initialized and started")

    # Use socketio.run instead of app.run for WebSocket support
    socketio.run(app, host='0.0.0.0', port=3001, debug=True)
