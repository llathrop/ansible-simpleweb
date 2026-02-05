"""
Deployment helper: desired vs current state, and delta for bootstrap/expansion.

Used to decide what to deploy when config has features.db_enabled, features.agent_enabled,
features.workers_enabled. Current state is detected (MongoDB reachable, agent health, worker count).
Bootstrap on start or config-change can run the deploy playbook for the delta.
"""

import os
from typing import Dict, Any, Optional

# Agent URL (same as app.py)
AGENT_SERVICE_URL = os.environ.get('AGENT_SERVICE_URL', 'http://agent-service:5000')
MONGODB_HOST = os.environ.get('MONGODB_HOST', 'mongodb')
MONGODB_PORT = int(os.environ.get('MONGODB_PORT', '27017'))


def get_desired_services() -> Dict[str, Any]:
    """
    Read app_config and return desired feature flags.
    Returns dict with db_enabled, agent_enabled, workers_enabled (bool), worker_count (int or 0).
    """
    try:
        from config_manager import load_config
        cfg = load_config()
        features = cfg.get('features') or {}
        return {
            'db_enabled': bool(features.get('db_enabled')),
            'agent_enabled': bool(features.get('agent_enabled')),
            'workers_enabled': bool(features.get('workers_enabled')),
            'worker_count': int(features.get('worker_count', 0)) or (1 if features.get('workers_enabled') else 0),
        }
    except Exception:
        return {'db_enabled': False, 'agent_enabled': False, 'workers_enabled': False, 'worker_count': 0}


def get_current_services(storage_backend=None, agent_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Detect what is actually deployed/reachable.
    Returns dict with db_reachable, agent_reachable (bool), worker_count (int).
    """
    import socket
    agent_url = agent_url or AGENT_SERVICE_URL
    result = {'db_reachable': False, 'agent_reachable': False, 'worker_count': 0}

    # MongoDB: try TCP connect to MONGODB_HOST:MONGODB_PORT
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((MONGODB_HOST, MONGODB_PORT))
        s.close()
        result['db_reachable'] = True
    except Exception:
        pass

    # Agent: HTTP GET to agent health
    try:
        import requests
        r = requests.get(f"{agent_url.rstrip('/')}/health", timeout=3)
        if r.status_code == 200:
            result['agent_reachable'] = True
    except Exception:
        pass

    # Workers: from storage if available
    if storage_backend and hasattr(storage_backend, 'get_all_workers'):
        try:
            workers = storage_backend.get_all_workers()
            result['worker_count'] = len(workers) if workers else 0
        except Exception:
            pass

    return result


def get_deployment_delta(
    desired: Optional[Dict[str, Any]] = None,
    current: Optional[Dict[str, Any]] = None,
    storage_backend=None,
) -> Dict[str, Any]:
    """
    Compare desired vs current and return what needs to be deployed.
    Returns dict with deploy_db, deploy_agent, deploy_workers (bool), worker_count_to_add (int).
    """
    desired = desired or get_desired_services()
    current = current or get_current_services(storage_backend=storage_backend)

    deploy_db = desired.get('db_enabled') and not current.get('db_reachable')
    deploy_agent = desired.get('agent_enabled') and not current.get('agent_reachable')
    wanted_workers = desired.get('worker_count', 0) or (1 if desired.get('workers_enabled') else 0)
    current_workers = current.get('worker_count', 0)
    deploy_workers = wanted_workers > current_workers
    worker_count_to_add = max(0, wanted_workers - current_workers)

    return {
        'deploy_db': deploy_db,
        'deploy_agent': deploy_agent,
        'deploy_workers': deploy_workers,
        'worker_count_to_add': worker_count_to_add,
        'desired': desired,
        'current': current,
    }


def run_bootstrap(delta: Dict[str, Any], playbook_dir: str = '/app/playbooks') -> tuple:
    """
    Run the deploy playbook for the given delta. Returns (success: bool, message: str).
    Requires ansible-playbook and (for docker tasks) Docker socket in container.
    """
    if not delta.get('deploy_db') and not delta.get('deploy_agent') and not delta.get('deploy_workers'):
        return True, 'Nothing to deploy'
    import subprocess
    playbook = os.path.join(playbook_dir, 'deploy', 'expand.yml')
    if not os.path.isfile(playbook):
        return False, f'Playbook not found: {playbook}'
    env = os.environ.copy()
    extra = [
        '-e', f"deploy_db={'true' if delta.get('deploy_db') else 'false'}",
        '-e', f"deploy_agent={'true' if delta.get('deploy_agent') else 'false'}",
        '-e', f"deploy_workers={'true' if delta.get('deploy_workers') else 'false'}",
        '-e', f"worker_count_to_add={delta.get('worker_count_to_add', 0)}",
    ]
    if os.environ.get('DEPLOY_DOCKER_NETWORK'):
        extra.extend(['-e', f"deploy_docker_network={os.environ.get('DEPLOY_DOCKER_NETWORK')}"])
    try:
        result = subprocess.run(
            ['ansible-playbook', playbook, '-i', 'localhost,', '-c', 'local'] + extra,
            cwd='/app',
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        if result.returncode == 0:
            return True, 'Deployment started (check container logs)'
        return False, result.stderr or result.stdout or f'Exit code {result.returncode}'
    except subprocess.TimeoutExpired:
        return False, 'Deployment playbook timed out'
    except FileNotFoundError:
        return False, 'ansible-playbook not found'
    except Exception as e:
        return False, str(e)
