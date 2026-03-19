import pytest
import tempfile
os = __import__('os')
sys = __import__('sys')
uuid = __import__('uuid')
from datetime import datetime, timezone
from flask import Flask, g, jsonify

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from web.storage.flatfile import FlatFileStorage
from web.auth import hash_password
from web.auth_routes import (
    auth_bp,
    init_auth_middleware,
    require_permission_or_worker
)

@pytest.fixture
def app_context():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['TESTING'] = True
    
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FlatFileStorage(config_dir=tmpdir)
        
        worker_id = str(uuid.uuid4())
        worker = {
            'id': worker_id,
            'name': 'test-worker',
            'status': 'online',
            'is_local': False,
            'registered_at': datetime.now(timezone.utc).isoformat()
        }
        storage.save_worker(worker)
        
        user_id = str(uuid.uuid4())
        test_user = {
            'id': user_id,
            'username': 'testuser',
            'password_hash': hash_password('testpassword'),
            'roles': ['operator'],
            'enabled': True
        }
        storage.save_user('testuser', test_user)
        
        app.register_blueprint(auth_bp)
        
        @app.route('/api/jobs/test', methods=['GET'])
        @require_permission_or_worker('jobs:view')
        def test_route():
            return jsonify({'ok': True})
            
        init_auth_middleware(app, storage, auth_enabled=True)
        
        yield app, worker_id, test_user

def test_worker_auth_success(app_context):
    app, worker_id, _ = app_context
    client = app.test_client()
    
    response = client.get('/api/jobs/test', headers={'X-Worker-Id': worker_id})
    assert response.status_code == 200
    assert response.json['ok'] is True

def test_worker_auth_fail_invalid_id(app_context):
    app, _, _ = app_context
    client = app.test_client()
    
    response = client.get('/api/jobs/test', headers={'X-Worker-Id': 'invalid-id'})
    assert response.status_code == 401

def test_middleware_prefix_matching(app_context):
    app, worker_id, _ = app_context
    client = app.test_client()
    
    response = client.get('/api/jobs/test', headers={'X-Worker-Id': worker_id})
    assert response.status_code == 200
