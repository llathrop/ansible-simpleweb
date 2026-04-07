
import os
import sys
import json
import sqlite3
from datetime import datetime, timezone

# Mock the FlatFileStorage enough to test the deadlock
sys.path.insert(0, '/home/llathrop/remote-pi/ansible-simpleweb/web')
from storage.flatfile import FlatFileStorage

def test_deadlock():
    db_dir = '/tmp/test_sqlite_deadlock'
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    
    storage = FlatFileStorage(config_dir=db_dir)
    
    # Setup a worker
    worker_id = 'test-worker'
    storage.save_worker({'id': worker_id, 'status': 'online', 'name': 'test'})
    
    print("Attempting update_worker_checkin...")
    try:
        # This should fail if my hypothesis is correct
        success = storage.update_worker_checkin(worker_id, {'status': 'busy'})
        print(f"Success: {success}")
    except Exception as e:
        print(f"Caught exception: {e}")

if __name__ == "__main__":
    test_deadlock()
