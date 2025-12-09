from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for
import os
import glob
import subprocess
import threading
import time
from datetime import datetime

app = Flask(__name__)

# Paths
PLAYBOOKS_DIR = '/app/playbooks'
LOGS_DIR = '/app/logs'
RUN_SCRIPT = '/app/run-playbook.sh'
INVENTORY_FILE = '/app/inventory/hosts'

# Track running playbooks
running_playbooks = {}

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

def run_playbook_background(playbook_name, target='host_machine'):
    """Run playbook in background thread"""
    try:
        running_playbooks[playbook_name] = {
            'status': 'running',
            'started': datetime.now().isoformat()
        }

        # Run the playbook
        cmd = ['bash', RUN_SCRIPT, playbook_name, '-l', target]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd='/app')

        running_playbooks[playbook_name] = {
            'status': 'completed' if result.returncode == 0 else 'failed',
            'finished': datetime.now().isoformat(),
            'exit_code': result.returncode
        }

        # Remove from running after 5 seconds
        time.sleep(5)
        if playbook_name in running_playbooks:
            del running_playbooks[playbook_name]

    except Exception as e:
        running_playbooks[playbook_name] = {
            'status': 'error',
            'error': str(e)
        }

@app.route('/')
def index():
    """Main page - list all playbooks"""
    playbooks = get_playbooks()
    targets = get_inventory_targets()
    playbook_data = []

    for playbook in playbooks:
        latest_log = get_latest_log(playbook)
        status = running_playbooks.get(playbook, {}).get('status', 'ready')

        playbook_data.append({
            'name': playbook,
            'display_name': playbook.replace('-', ' ').title(),
            'latest_log': latest_log,
            'last_run': get_log_timestamp(latest_log),
            'status': status
        })

    return render_template('index.html', playbooks=playbook_data, targets=targets)

@app.route('/run/<playbook_name>')
def run_playbook(playbook_name):
    """Trigger playbook execution"""
    if playbook_name not in get_playbooks():
        return jsonify({'error': 'Playbook not found'}), 404

    if playbook_name in running_playbooks:
        return jsonify({'error': 'Playbook already running'}), 400

    # Get target from query parameter, default to host_machine
    target = request.args.get('target', 'host_machine')

    # Start playbook in background thread
    thread = threading.Thread(target=run_playbook_background, args=(playbook_name, target))
    thread.daemon = True
    thread.start()

    return redirect(url_for('index'))

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
        status_data[playbook] = running_playbooks.get(playbook, {}).get('status', 'ready')

    return jsonify(status_data)

@app.route('/api/playbooks')
def api_playbooks():
    """API endpoint to get playbook information"""
    playbooks = get_playbooks()
    result = []

    for playbook in playbooks:
        latest_log = get_latest_log(playbook)
        result.append({
            'name': playbook,
            'latest_log': latest_log,
            'last_run': get_log_timestamp(latest_log),
            'status': running_playbooks.get(playbook, {}).get('status', 'ready')
        })

    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3001, debug=True)
