"""
Application configuration manager.

Loads and saves app_config.yaml from CONFIG_DIR (default /app/config).
Config file is text (YAML) for editing and review. When present, config values
take precedence over environment variables for app behavior. Supports backup
and restore of the config file.
"""
import os
import copy
from typing import Dict, Any, Tuple, Optional

# Try YAML; if not available, config save/load will fail with clear error
try:
    import yaml
except ImportError:
    yaml = None

CONFIG_DIR = os.environ.get('CONFIG_DIR', '/app/config')
CONFIG_FILENAME = 'app_config.yaml'
CONFIG_PATH = os.path.join(CONFIG_DIR, CONFIG_FILENAME)

# Default configuration (matches plan in docs/PHASE_SINGLE_CONTAINER_BOOTSTRAP.md)
# Organization: storage, agent, cluster, features, deployment, ui
DEFAULT_CONFIG = {
    'storage': {
        'backend': 'flatfile',
        'mongodb': {
            'host': 'mongodb',
            'port': 27017,
            'database': 'ansible_simpleweb',
        },
    },
    'agent': {
        'enabled': False,
        'trigger_enabled': True,
        'model': 'qwen2.5-coder:3b',
        'url': 'http://agent-service:5000',
    },
    'cluster': {
        'mode': 'standalone',
        'registration_token': '',
        'checkin_interval': 60,
        'sync_interval': 300,
        'local_worker_tags': ['local'],
    },
    'features': {
        'db_enabled': False,
        'agent_enabled': False,
        'workers_enabled': False,
        'worker_count': 0,
    },
    'deployment': {
        'agent_host': 'local',
        'db_host': 'local',
        'worker_hosts': [],
    },
    'ui': {
        'default_theme': 'default',
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override into base. Lists are replaced, not merged."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config() -> Dict[str, Any]:
    """
    Load configuration from file. If file does not exist, return default config.
    Environment variables are not merged here; callers may use get_effective_* helpers.
    """
    if yaml is None:
        return copy.deepcopy(DEFAULT_CONFIG)
    if not os.path.isfile(CONFIG_PATH):
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, 'r') as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return copy.deepcopy(DEFAULT_CONFIG)
        return _deep_merge(copy.deepcopy(DEFAULT_CONFIG), data)
    except Exception:
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate config, then save to app_config.yaml.
    Returns (success, error_message). Error message is empty on success.
    """
    if yaml is None:
        return False, 'PyYAML is not installed'
    validated, err = validate_config(config)
    if not validated:
        return False, err or 'Invalid config'
    try:
        os.makedirs(CONFIG_DIR, mode=0o755, exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            yaml.dump(validated, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return True, ''
    except Exception as e:
        return False, str(e)


def validate_config(config: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Validate config structure and values. Returns (validated_dict, error_message).
    If valid, returns (validated merged with defaults, ''). Otherwise (None, error_message).
    """
    if not isinstance(config, dict):
        return None, 'Config must be a dict'
    merged = _deep_merge(copy.deepcopy(DEFAULT_CONFIG), config)

    # storage
    s = merged.get('storage', {})
    if not isinstance(s, dict):
        return None, 'storage must be a dict'
    backend = (s.get('backend') or 'flatfile').lower()
    if backend not in ('flatfile', 'mongodb'):
        return None, 'storage.backend must be flatfile or mongodb'
    if backend == 'mongodb':
        m = s.get('mongodb') or {}
        if not isinstance(m, dict):
            return None, 'storage.mongodb must be a dict'
        if not isinstance(m.get('port'), (int, type(None))):
            return None, 'storage.mongodb.port must be an integer'

    # agent
    a = merged.get('agent', {})
    if not isinstance(a, dict):
        return None, 'agent must be a dict'
    if not isinstance(a.get('enabled'), (bool, type(None))):
        return None, 'agent.enabled must be a boolean'
    if not isinstance(a.get('trigger_enabled'), (bool, type(None))):
        return None, 'agent.trigger_enabled must be a boolean'

    # cluster
    c = merged.get('cluster', {})
    if not isinstance(c, dict):
        return None, 'cluster must be a dict'
    mode = (c.get('mode') or 'standalone').lower()
    if mode not in ('standalone', 'primary', 'worker'):
        return None, 'cluster.mode must be standalone, primary, or worker'
    if not isinstance(c.get('local_worker_tags'), (list, type(None))):
        return None, 'cluster.local_worker_tags must be a list'

    # features
    f = merged.get('features', {})
    if not isinstance(f, dict):
        return None, 'features must be a dict'
    wc = f.get('worker_count')
    if wc is not None and not isinstance(wc, (int, type(None))):
        return None, 'features.worker_count must be an integer'
    if isinstance(wc, (int, float)) and (wc < 0 or wc > 100):
        return None, 'features.worker_count must be 0-100'

    # cluster.sync_interval
    si = merged.get('cluster', {}).get('sync_interval')
    if si is not None and not isinstance(si, (int, type(None))):
        return None, 'cluster.sync_interval must be an integer'

    # deployment
    d = merged.get('deployment', {})
    if not isinstance(d, dict):
        return None, 'deployment must be a dict'
    if not isinstance(d.get('worker_hosts'), (list, type(None))):
        return None, 'deployment.worker_hosts must be a list'

    return merged, ''


def get_effective_storage_backend() -> str:
    """Backend name for storage: from config file if present, else env."""
    cfg = load_config()
    return (cfg.get('storage') or {}).get('backend') or os.environ.get('STORAGE_BACKEND', 'flatfile')


def get_effective_mongodb_settings() -> dict:
    """MongoDB host, port, database. From config if storage is mongodb, else env."""
    cfg = load_config()
    backend = (cfg.get('storage') or {}).get('backend') or os.environ.get('STORAGE_BACKEND', 'flatfile')
    if backend != 'mongodb':
        return {}
    m = (cfg.get('storage') or {}).get('mongodb') or {}
    return {
        'host': m.get('host') or os.environ.get('MONGODB_HOST', 'mongodb'),
        'port': int(m.get('port') or os.environ.get('MONGODB_PORT', 27017)),
        'database': m.get('database') or os.environ.get('MONGODB_DATABASE', 'ansible_simpleweb'),
    }


def get_effective_agent_url() -> str:
    """Agent service URL. Config takes precedence over env."""
    cfg = load_config()
    return (cfg.get('agent') or {}).get('url') or os.environ.get('AGENT_SERVICE_URL', 'http://agent-service:5000')


def get_effective_agent_trigger_enabled() -> bool:
    """Whether to trigger agent on job completion. Config over env."""
    cfg = load_config()
    val = (cfg.get('agent') or {}).get('trigger_enabled')
    if val is not None:
        return bool(val)
    return os.environ.get('AGENT_TRIGGER_ENABLED', 'true').lower() in ('1', 'true', 'yes')


def get_effective_worker_count() -> int:
    """Desired worker count from features. Used by deployment."""
    cfg = load_config()
    f = cfg.get('features') or {}
    return int(f.get('worker_count', 0) or 0)


def config_file_exists() -> bool:
    """Return True if app_config.yaml exists."""
    return os.path.isfile(CONFIG_PATH)


def get_config_path() -> str:
    """Return absolute path to config file."""
    return CONFIG_PATH
