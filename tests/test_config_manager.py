"""
Unit tests for application config manager (web/config_manager.py).

Verifies load/save/validate, default config, and effective storage/mongodb helpers.
"""
import os
import sys
import importlib
import pytest

# Project root on path for web.* imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set CONFIG_DIR to a temp dir so we don't touch real config
@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('CONFIG_DIR', str(tmp_path))
    # Reload so CONFIG_PATH is recalculated
    import web.config_manager as cm
    importlib.reload(cm)
    yield str(tmp_path)


def test_load_config_returns_defaults_when_no_file(config_dir):
    """When app_config.yaml does not exist, load_config returns default config."""
    import web.config_manager as config_manager
    cfg = config_manager.load_config()
    assert cfg['storage']['backend'] == 'flatfile'
    assert cfg['agent']['enabled'] is False
    assert cfg['features']['db_enabled'] is False
    assert cfg['deployment']['worker_hosts'] == []


def test_load_config_returns_merged_when_file_exists(config_dir):
    """When app_config.yaml exists, load_config merges with defaults."""
    import web.config_manager as config_manager
    path = os.path.join(config_dir, 'app_config.yaml')
    with open(path, 'w') as f:
        f.write("storage:\n  backend: mongodb\n")
    cfg = config_manager.load_config()
    assert cfg['storage']['backend'] == 'mongodb'
    assert cfg['agent']['model'] == 'qwen2.5-coder:3b'  # from defaults


def test_validate_config_accepts_valid(config_dir):
    """validate_config accepts valid partial config."""
    import web.config_manager as config_manager
    validated, err = config_manager.validate_config({'storage': {'backend': 'flatfile'}})
    assert err == ''
    assert validated is not None
    assert validated['storage']['backend'] == 'flatfile'


def test_validate_config_rejects_invalid_backend(config_dir):
    """validate_config rejects invalid storage.backend."""
    import web.config_manager as config_manager
    validated, err = config_manager.validate_config({'storage': {'backend': 'invalid'}})
    assert validated is None
    assert 'flatfile or mongodb' in err


def test_validate_config_rejects_invalid_cluster_mode(config_dir):
    """validate_config rejects invalid cluster.mode."""
    import web.config_manager as config_manager
    validated, err = config_manager.validate_config({'cluster': {'mode': 'invalid'}})
    assert validated is None
    assert 'standalone' in err or 'primary' in err


def test_save_config_writes_file(config_dir):
    """save_config writes valid YAML to app_config.yaml."""
    import web.config_manager as config_manager
    cfg = config_manager.load_config()
    cfg['storage']['backend'] = 'flatfile'
    success, err = config_manager.save_config(cfg)
    assert success is True, err
    assert err == ''
    path = os.path.join(config_dir, 'app_config.yaml')
    assert os.path.isfile(path)
    with open(path) as f:
        content = f.read()
    assert 'flatfile' in content


def test_save_config_rejects_invalid(config_dir):
    """save_config returns error for invalid config."""
    import web.config_manager as config_manager
    success, err = config_manager.save_config({'storage': {'backend': 'invalid'}})
    assert success is False
    assert len(err) > 0


def test_get_effective_storage_backend_uses_config_when_file_exists(config_dir):
    """When config file exists, get_effective_storage_backend uses it."""
    import web.config_manager as config_manager
    path = os.path.join(config_dir, 'app_config.yaml')
    with open(path, 'w') as f:
        f.write("storage:\n  backend: mongodb\n")
    importlib.reload(config_manager)
    assert config_manager.get_effective_storage_backend() == 'mongodb'


def test_get_effective_mongodb_settings_when_flatfile(config_dir):
    """get_effective_mongodb_settings returns empty when backend is flatfile."""
    import web.config_manager as config_manager
    # No file -> defaults -> flatfile
    m = config_manager.get_effective_mongodb_settings()
    assert m == {}
    # With file flatfile
    path = os.path.join(config_dir, 'app_config.yaml')
    with open(path, 'w') as f:
        f.write("storage:\n  backend: flatfile\n")
    importlib.reload(config_manager)
    m = config_manager.get_effective_mongodb_settings()
    assert m == {}


def test_config_file_exists(config_dir):
    """config_file_exists reflects presence of app_config.yaml."""
    import web.config_manager as config_manager
    assert config_manager.config_file_exists() is False
    path = os.path.join(config_dir, 'app_config.yaml')
    with open(path, 'w') as f:
        f.write("storage:\n  backend: flatfile\n")
    importlib.reload(config_manager)
    assert config_manager.config_file_exists() is True


def test_get_config_path(config_dir):
    """get_config_path returns absolute path ending with app_config.yaml."""
    import web.config_manager as config_manager
    p = config_manager.get_config_path()
    assert p == os.path.join(config_dir, 'app_config.yaml')
    assert os.path.basename(p) == 'app_config.yaml'


def test_validate_config_rejects_non_dict(config_dir):
    """validate_config rejects non-dict input."""
    import web.config_manager as config_manager
    for invalid in ([], None, 'x', 1):
        validated, err = config_manager.validate_config(invalid)
        assert validated is None
        assert 'dict' in err.lower() or len(err) > 0


def test_validate_config_rejects_mongodb_port_not_int(config_dir):
    """validate_config rejects storage.mongodb.port when not int."""
    import web.config_manager as config_manager
    validated, err = config_manager.validate_config({
        'storage': {'backend': 'mongodb', 'mongodb': {'port': '27017'}},
    })
    assert validated is None
    assert 'integer' in err.lower() or 'port' in err.lower()


def test_load_config_malformed_yaml_returns_defaults(config_dir):
    """When config file has invalid YAML, load_config returns default config."""
    import web.config_manager as config_manager
    path = os.path.join(config_dir, 'app_config.yaml')
    with open(path, 'w') as f:
        f.write("storage:\n  backend: [ broken\n")
    cfg = config_manager.load_config()
    assert cfg['storage']['backend'] == 'flatfile'
    assert cfg['agent']['enabled'] is False


def test_save_config_then_load_round_trip(config_dir):
    """Outcome: save_config then load_config returns the same effective values."""
    import web.config_manager as config_manager
    cfg = config_manager.load_config()
    cfg['storage']['backend'] = 'flatfile'
    cfg['features']['db_enabled'] = True
    success, err = config_manager.save_config(cfg)
    assert success is True, err
    loaded = config_manager.load_config()
    assert loaded['storage']['backend'] == 'flatfile'
    assert loaded['features']['db_enabled'] is True


def test_validate_config_accepts_worker_count(config_dir):
    """validate_config accepts features.worker_count."""
    import web.config_manager as config_manager
    validated, err = config_manager.validate_config({
        'features': {'worker_count': 2},
    })
    assert err == ''
    assert validated is not None
    assert validated['features']['worker_count'] == 2


def test_get_effective_agent_url_uses_config(config_dir):
    """get_effective_agent_url uses config when present."""
    import web.config_manager as config_manager
    path = os.path.join(config_dir, 'app_config.yaml')
    with open(path, 'w') as f:
        f.write("agent:\n  url: http://custom-agent:5001\n")
    importlib.reload(config_manager)
    assert config_manager.get_effective_agent_url() == 'http://custom-agent:5001'
