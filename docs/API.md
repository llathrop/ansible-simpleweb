# API Reference

REST API documentation for the Ansible Simple Web Interface.

## Table of Contents

- [Overview](#overview)
- [Base URL](#base-url)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
- [Response Formats](#response-formats)
- [Examples](#examples)
- [Error Handling](#error-handling)

## Overview

The web interface provides a REST API for programmatic access to playbook information and execution.

### API Capabilities

- List all available playbooks
- Get playbook status
- Trigger playbook execution
- Retrieve execution history
- Monitor real-time status

## Base URL

```
http://localhost:3001
```

## Authentication

Currently: **None required**

The service is localhost-only by default. Before exposing externally, implement authentication (JWT, API keys, OAuth, etc.).

## Endpoints

### GET /api/playbooks

Get list of all playbooks with their latest execution information.

**Request:**
```http
GET /api/playbooks HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
[
  {
    "name": "hardware-inventory",
    "latest_log": "hardware-inventory-20251209-004455.log",
    "last_run": "2025-12-09 00:44:58",
    "status": "ready"
  },
  {
    "name": "system-health",
    "latest_log": "system-health-20251209-004511.log",
    "last_run": "2025-12-09 00:45:20",
    "status": "running"
  }
]
```

**Fields:**
- `name` (string): Playbook filename without `.yml`
- `latest_log` (string|null): Most recent log filename
- `last_run` (string): Timestamp of last execution
- `status` (string): Current status (ready|running|completed|failed)

---

### GET /api/status

Get current execution status of all playbooks.

**Request:**
```http
GET /api/status HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
{
  "hardware-inventory": "ready",
  "network-config": "ready",
  "service-status": "running",
  "software-inventory": "ready",
  "system-health": "completed"
}
```

**Status Values:**
- `ready`: Idle, ready to run
- `running`: Currently executing
- `completed`: Just finished successfully
- `failed`: Just finished with error

**Note:** `completed` and `failed` status automatically revert to `ready` after 5 seconds.

---

### GET /run/{playbook_name}

Trigger playbook execution.

**Request:**
```http
GET /run/hardware-inventory?target=host_machine HTTP/1.1
Host: localhost:3001
```

**Parameters:**
- `playbook_name` (path, required): Name of playbook to run
- `target` (query, optional): Target host/group (default: `host_machine`)

**Response:**
```http
HTTP/1.1 302 Found
Location: /
```

Redirects to main page after triggering execution.

**Error Responses:**

```json
// 404 - Playbook not found
{
  "error": "Playbook not found"
}

// 400 - Already running
{
  "error": "Playbook already running"
}
```

---

### GET /logs

Get list of all log files.

**Request:**
```http
GET /logs HTTP/1.1
Host: localhost:3001
```

**Response:**
HTML page with table of all log files.

*Note: This endpoint returns HTML, not JSON. For programmatic access, use file system or create custom endpoint.*

---

### GET /logs/{log_file}

View specific log file contents.

**Request:**
```http
GET /logs/hardware-inventory-20251209-004455.log HTTP/1.1
Host: localhost:3001
```

**Response:**
HTML page displaying log contents.

*Note: Returns HTML. For programmatic access, read from `logs/` directory directly.*

## Response Formats

### Success Response

```json
{
  "status": "success",
  "data": { ... }
}
```

### Error Response

```json
{
  "error": "Error message here"
}
```

### HTTP Status Codes

- `200 OK` - Successful request
- `302 Found` - Redirect after playbook trigger
- `400 Bad Request` - Invalid request
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

## Examples

### cURL Examples

#### List All Playbooks

```bash
curl http://localhost:3001/api/playbooks
```

#### Get Status

```bash
curl http://localhost:3001/api/status
```

#### Run Playbook (Default Target)

```bash
curl "http://localhost:3001/run/hardware-inventory"
```

#### Run Playbook (Specific Target)

```bash
curl "http://localhost:3001/run/system-health?target=all"
```

#### Run Playbook (Single Host)

```bash
curl "http://localhost:3001/run/software-inventory?target=192.168.1.50"
```

### Python Examples

#### Using requests library

```python
import requests
import json

BASE_URL = "http://localhost:3001"

# Get all playbooks
response = requests.get(f"{BASE_URL}/api/playbooks")
playbooks = response.json()
print(json.dumps(playbooks, indent=2))

# Get status
response = requests.get(f"{BASE_URL}/api/status")
status = response.json()
print(json.dumps(status, indent=2))

# Run playbook
response = requests.get(
    f"{BASE_URL}/run/hardware-inventory",
    params={"target": "host_machine"}
)
print(f"Status Code: {response.status_code}")
```

#### Monitor Playbook Execution

```python
import requests
import time

BASE_URL = "http://localhost:3001"
PLAYBOOK = "hardware-inventory"

# Trigger playbook
requests.get(f"{BASE_URL}/run/{PLAYBOOK}?target=all")
print(f"Started {PLAYBOOK}")

# Poll status
while True:
    response = requests.get(f"{BASE_URL}/api/status")
    status = response.json()

    if status[PLAYBOOK] == "ready":
        print(f"{PLAYBOOK} completed!")
        break
    elif status[PLAYBOOK] == "running":
        print(f"{PLAYBOOK} still running...")
    elif status[PLAYBOOK] == "failed":
        print(f"{PLAYBOOK} failed!")
        break

    time.sleep(2)

# Get results
response = requests.get(f"{BASE_URL}/api/playbooks")
playbooks = response.json()
for p in playbooks:
    if p['name'] == PLAYBOOK:
        print(f"Log file: {p['latest_log']}")
        print(f"Last run: {p['last_run']}")
```

### JavaScript Examples

#### Using Fetch API

```javascript
const BASE_URL = 'http://localhost:3001';

// Get all playbooks
fetch(`${BASE_URL}/api/playbooks`)
  .then(response => response.json())
  .then(playbooks => console.log(playbooks));

// Get status
fetch(`${BASE_URL}/api/status`)
  .then(response => response.json())
  .then(status => console.log(status));

// Run playbook
fetch(`${BASE_URL}/run/hardware-inventory?target=all`)
  .then(response => console.log('Playbook triggered'));

// Monitor execution
async function monitorPlaybook(playbookName) {
  while (true) {
    const response = await fetch(`${BASE_URL}/api/status`);
    const status = await response.json();

    if (status[playbookName] === 'ready') {
      console.log(`${playbookName} completed`);
      break;
    }

    console.log(`${playbookName} status: ${status[playbookName]}`);
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
}

// Usage
fetch(`${BASE_URL}/run/system-health`)
  .then(() => monitorPlaybook('system-health'));
```

### Bash Examples

#### Simple Status Check

```bash
#!/bin/bash

STATUS=$(curl -s http://localhost:3001/api/status)
echo "$STATUS" | jq '.'
```

#### Run All Playbooks

```bash
#!/bin/bash

PLAYBOOKS=$(curl -s http://localhost:3001/api/playbooks | jq -r '.[].name')

for playbook in $PLAYBOOKS; do
    echo "Running $playbook..."
    curl -s "http://localhost:3001/run/$playbook?target=host_machine"
    sleep 5
done
```

#### Monitor Until Complete

```bash
#!/bin/bash

PLAYBOOK="hardware-inventory"

# Trigger playbook
curl -s "http://localhost:3001/run/$PLAYBOOK" > /dev/null

# Monitor status
while true; do
    STATUS=$(curl -s http://localhost:3001/api/status | jq -r ".\"$PLAYBOOK\"")
    echo "Status: $STATUS"

    if [ "$STATUS" == "ready" ]; then
        echo "Completed!"
        break
    fi

    sleep 2
done
```

## Error Handling

### Common Errors

**404 Not Found**
```json
{
  "error": "Playbook not found"
}
```

**Solution:** Check playbook name, verify file exists in `playbooks/` directory.

**400 Bad Request**
```json
{
  "error": "Playbook already running"
}
```

**Solution:** Wait for current execution to complete before triggering again.

### Best Practices

1. **Check status before running**
   ```python
   status = requests.get(f"{BASE_URL}/api/status").json()
   if status[playbook] == "ready":
       requests.get(f"{BASE_URL}/run/{playbook}")
   ```

2. **Handle redirects**
   ```python
   response = requests.get(url, allow_redirects=True)
   ```

3. **Implement retries**
   ```python
   from requests.adapters import HTTPAdapter
   from requests.packages.urllib3.util.retry import Retry

   session = requests.Session()
   retry = Retry(total=3, backoff_factor=0.5)
   adapter = HTTPAdapter(max_retries=retry)
   session.mount('http://', adapter)
   ```

4. **Set timeouts**
   ```python
   response = requests.get(url, timeout=10)
   ```

## Rate Limiting

Currently: **No rate limiting**

For production use, implement rate limiting:
- Playbook execution: 1 per playbook per minute
- Status checks: 100 per minute
- Playbook listing: 100 per minute

---

### GET /api/storage

Get information about the active storage backend.

**Request:**
```http
GET /api/storage HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
{
  "backend_type": "flatfile",
  "healthy": true,
  "config": {
    "STORAGE_BACKEND": "flatfile",
    "MONGODB_HOST": null,
    "MONGODB_DATABASE": null
  }
}
```

---

## Inventory API

CRUD operations for managed inventory items (hosts/servers).

### GET /api/inventory

Get all inventory items.

**Request:**
```http
GET /api/inventory HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
[
  {
    "id": "b459dfe1-65a5-4666-be7e-8d0dba7deff5",
    "hostname": "web-server-01.example.com",
    "display_name": "Web Server 1",
    "group": "webservers",
    "description": "Primary web server",
    "variables": {"ansible_user": "deploy"},
    "created": "2025-12-10T03:07:51.395020",
    "updated": "2025-12-10T03:08:10.833655"
  }
]
```

---

### GET /api/inventory/{item_id}

Get a single inventory item by ID.

**Request:**
```http
GET /api/inventory/b459dfe1-65a5-4666-be7e-8d0dba7deff5 HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
{
  "id": "b459dfe1-65a5-4666-be7e-8d0dba7deff5",
  "hostname": "web-server-01.example.com",
  "display_name": "Web Server 1",
  "group": "webservers",
  "description": "Primary web server",
  "variables": {"ansible_user": "deploy"},
  "created": "2025-12-10T03:07:51.395020",
  "updated": "2025-12-10T03:08:10.833655"
}
```

---

### POST /api/inventory

Create a new inventory item.

**Request:**
```http
POST /api/inventory HTTP/1.1
Host: localhost:3001
Content-Type: application/json

{
  "hostname": "server.example.com",
  "display_name": "Web Server 1",
  "group": "webservers",
  "description": "Primary web server",
  "variables": {"ansible_user": "deploy", "ansible_port": 22}
}
```

**Required fields:** `hostname`

**Response (201 Created):**
```json
{
  "id": "generated-uuid",
  "hostname": "server.example.com",
  "display_name": "Web Server 1",
  "group": "webservers",
  "description": "Primary web server",
  "variables": {"ansible_user": "deploy", "ansible_port": 22},
  "created": "2025-12-10T03:07:51.395020",
  "updated": "2025-12-10T03:07:51.395020"
}
```

---

### PUT /api/inventory/{item_id}

Update an existing inventory item.

**Request:**
```http
PUT /api/inventory/b459dfe1-65a5-4666-be7e-8d0dba7deff5 HTTP/1.1
Host: localhost:3001
Content-Type: application/json

{
  "description": "Updated description",
  "variables": {"ansible_user": "admin"}
}
```

**Response:**
```json
{
  "id": "b459dfe1-65a5-4666-be7e-8d0dba7deff5",
  "hostname": "web-server-01.example.com",
  "display_name": "Web Server 1",
  "group": "webservers",
  "description": "Updated description",
  "variables": {"ansible_user": "admin"},
  "created": "2025-12-10T03:07:51.395020",
  "updated": "2025-12-10T03:15:00.000000"
}
```

---

### DELETE /api/inventory/{item_id}

Delete an inventory item.

**Request:**
```http
DELETE /api/inventory/b459dfe1-65a5-4666-be7e-8d0dba7deff5 HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
{
  "success": true,
  "deleted": "b459dfe1-65a5-4666-be7e-8d0dba7deff5"
}
```

---

### POST /api/inventory/search

Search inventory items by criteria. Supports wildcard matching.

**Request:**
```http
POST /api/inventory/search HTTP/1.1
Host: localhost:3001
Content-Type: application/json

{
  "hostname": "web*",
  "group": "webservers"
}
```

**Response:**
```json
[
  {
    "id": "b459dfe1-65a5-4666-be7e-8d0dba7deff5",
    "hostname": "web-server-01.example.com",
    "display_name": "Web Server 1",
    "group": "webservers",
    ...
  }
]
```

---

## CMDB / Host Facts API

The CMDB (Configuration Management Database) stores collected facts from playbook runs,
such as hardware specifications, installed software, and system configuration per host.

### GET /api/hosts

Get summary of all hosts with collected facts.

**Request:**
```http
GET /api/hosts HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
[
  {
    "host": "192.168.1.50",
    "groups": ["local_servers"],
    "collections": ["hardware", "software"],
    "first_seen": "2025-12-10T04:48:43.000000",
    "last_updated": "2025-12-10T04:55:52.983452"
  },
  {
    "host": "web-server-01.example.com",
    "groups": ["webservers", "production"],
    "collections": ["hardware"],
    "first_seen": "2025-12-10T04:15:57.087085",
    "last_updated": "2025-12-10T04:15:57.087085"
  }
]
```

---

### GET /api/hosts/{hostname}

Get all collected facts for a specific host.

**Request:**
```http
GET /api/hosts/192.168.1.50 HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
{
  "host": "192.168.1.50",
  "groups": ["local_servers"],
  "collections": {
    "hardware": {
      "current": {
        "cpu": {
          "model": "Intel Core i7-6700HQ",
          "cores": 4,
          "vcpus": 8
        },
        "memory": {
          "total_mb": 31909
        },
        "disks": {
          "total_size_gb": 925.73
        }
      },
      "last_updated": "2025-12-10T04:48:43.000000",
      "source": "callback_plugin",
      "history": []
    }
  },
  "first_seen": "2025-12-10T04:48:43.000000",
  "last_updated": "2025-12-10T04:55:52.983452"
}
```

---

### GET /api/hosts/{hostname}/{collection}

Get a specific collection (e.g., hardware, software) for a host.

**Request:**
```http
GET /api/hosts/192.168.1.50/hardware HTTP/1.1
Host: localhost:3001
```

**Query Parameters:**
- `include_history=true` - Include historical changes (diffs)

**Response:**
```json
{
  "current": {
    "cpu": {...},
    "memory": {...},
    "disks": {...}
  },
  "last_updated": "2025-12-10T04:48:43.000000",
  "source": "callback_plugin",
  "history": [
    {
      "timestamp": "2025-12-10T04:30:00.000000",
      "diff": {
        "changed": {"memory.free_mb": {"old": 4096, "new": 2048}},
        "added": {},
        "removed": {}
      }
    }
  ]
}
```

---

### POST /api/hosts/{hostname}/facts

Manually save facts for a host (useful for external integrations).

**Request:**
```http
POST /api/hosts/new-server.local/facts HTTP/1.1
Host: localhost:3001
Content-Type: application/json

{
  "collection": "hardware",
  "data": {
    "cpu": "Intel Xeon E5",
    "memory_gb": 64,
    "disks": [{"device": "/dev/sda", "size_gb": 1000}]
  },
  "groups": ["production", "databases"],
  "source": "api"
}
```

**Response:**
```json
{
  "status": "created",
  "host": "new-server.local",
  "collection": "hardware"
}
```

Status values: `created`, `updated`, `unchanged`

---

### GET /api/hosts/{hostname}/history/{collection}

Get change history for a specific collection.

**Request:**
```http
GET /api/hosts/192.168.1.50/history/hardware?limit=10 HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
[
  {
    "timestamp": "2025-12-10T04:48:43.000000",
    "diff": {
      "changed": {"memory.free_mb": {"old": 4096, "new": 2048}},
      "added": {},
      "removed": {}
    },
    "source": "callback_plugin"
  }
]
```

---

### DELETE /api/hosts/{hostname}

Delete all facts for a host.

**Request:**
```http
DELETE /api/hosts/old-server.local HTTP/1.1
Host: localhost:3001
```

**Query Parameters:**
- `collection=hardware` - Delete only specific collection (optional)

**Response:**
```json
{
  "deleted": true,
  "host": "old-server.local"
}
```

---

### GET /api/hosts/group/{group_name}

Get all hosts belonging to a specific group.

**Request:**
```http
GET /api/hosts/group/webservers HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
[
  {
    "host": "web-server-01.example.com",
    "groups": ["webservers", "production"],
    "collections": ["hardware"],
    "last_updated": "2025-12-10T04:15:57.087085"
  }
]
```

---

## Batch Job API

API for managing batch job execution - run multiple playbooks against multiple targets sequentially.

### GET /api/batch

Get all batch jobs.

**Request:**
```http
GET /api/batch HTTP/1.1
Host: localhost:3001
```

**Response:**
```json
{
  "batch_jobs": [
    {
      "id": "abc123-def456",
      "name": "Server Maintenance",
      "playbooks": ["system-health", "service-status"],
      "targets": ["192.168.1.50", "webservers"],
      "status": "completed",
      "total": 2,
      "completed": 2,
      "failed": 0,
      "created": "2025-12-10T12:00:00.000000",
      "finished": "2025-12-10T12:05:00.000000"
    }
  ],
  "count": 1
}
```

---

### GET /api/batch/active

Get currently running batch jobs.

**Response:**
```json
{
  "abc123-def456": {
    "name": "Server Maintenance",
    "status": "running",
    "current_playbook": "system-health",
    "completed": 0,
    "total": 2
  }
}
```

---

### POST /api/batch

Create and start a new batch job.

**Request:**
```http
POST /api/batch HTTP/1.1
Host: localhost:3001
Content-Type: application/json

{
  "playbooks": ["system-health", "service-status"],
  "targets": ["192.168.1.50", "webservers"],
  "name": "Server Maintenance"
}
```

**Response (201 Created):**
```json
{
  "batch_id": "abc123-def456",
  "message": "Batch job created and started",
  "status": "pending"
}
```

---

### GET /api/batch/{batch_id}

Get details of a specific batch job.

**Response:**
```json
{
  "id": "abc123-def456",
  "name": "Server Maintenance",
  "playbooks": ["system-health", "service-status"],
  "targets": ["192.168.1.50"],
  "status": "running",
  "current_playbook": "system-health",
  "current_run_id": "run-xyz",
  "total": 2,
  "completed": 0,
  "failed": 0,
  "results": [],
  "hosts_included": ["192.168.1.50"],
  "created": "2025-12-10T12:00:00.000000",
  "started": "2025-12-10T12:00:01.000000",
  "finished": null
}
```

---

### GET /api/batch/{batch_id}/logs

Get log files for all playbooks in a batch job.

**Response:**
```json
{
  "batch_id": "abc123-def456",
  "logs": [
    {
      "playbook": "system-health",
      "log_file": "system-health-20251210-120001.log",
      "status": "completed",
      "exists": true
    },
    {
      "playbook": "service-status",
      "log_file": "service-status-20251210-120130.log",
      "status": "running",
      "exists": true
    }
  ]
}
```

---

### GET /api/batch/{batch_id}/export

Export batch job configuration for reuse.

**Response:**
```json
{
  "name": "Server Maintenance",
  "playbooks": ["system-health", "service-status"],
  "targets": ["192.168.1.50"],
  "exported_from": "abc123-def456",
  "exported_at": "2025-12-10T12:10:00.000000"
}
```

---

### DELETE /api/batch/{batch_id}

Delete a batch job record (only if not running).

**Response:**
```json
{
  "success": true,
  "deleted": "abc123-def456"
}
```

---

## SSH Key Management API

Manage SSH private keys for host authentication.

### GET /api/ssh-keys

List available SSH keys.

**Response:**
```json
{
  "keys": [
    {
      "name": "svc-ansible-key",
      "path": "/app/.ssh/svc-ansible-key",
      "source": "system"
    },
    {
      "name": "my-server-key",
      "path": "/app/ssh-keys/my-server-key",
      "source": "uploaded"
    }
  ]
}
```

---

### POST /api/ssh-keys

Upload a new SSH private key.

**Request:**
```http
POST /api/ssh-keys HTTP/1.1
Host: localhost:3001
Content-Type: application/json

{
  "name": "my-server-key",
  "content": "-----BEGIN RSA PRIVATE KEY-----\n..."
}
```

**Response:**
```json
{
  "success": true,
  "name": "my-server-key",
  "path": "/app/ssh-keys/my-server-key"
}
```

**Notes:**
- Key name can only contain letters, numbers, dashes, and underscores
- Keys are stored with 0600 permissions
- Keys are stored in `/app/ssh-keys/` (mounted volume)

---

### POST /api/inventory/test-connection

Test SSH connection to a host before saving.

**Request:**
```http
POST /api/inventory/test-connection HTTP/1.1
Host: localhost:3001
Content-Type: application/json

{
  "hostname": "192.168.1.50",
  "variables": {
    "ansible_user": "deploy",
    "ansible_ssh_private_key_file": "/app/ssh-keys/my-key"
  }
}
```

**Response (Success):**
```json
{
  "success": true,
  "message": "Connection successful"
}
```

**Response (Failure):**
```json
{
  "success": false,
  "error": "Permission denied - check credentials"
}
```

---

## Schedule API

Manage scheduled playbook and batch job execution.

### GET /api/schedules

Get all schedules.

**Response:**
```json
{
  "schedules": [
    {
      "id": "schedule-123",
      "name": "Daily Health Check",
      "is_batch": false,
      "playbook": "system-health",
      "target": "all",
      "recurrence_display": "Daily at 02:00",
      "next_run_display": "2025-12-11 02:00",
      "enabled": true,
      "run_count": 10,
      "success_count": 8,
      "failed_count": 2,
      "success_rate": 80,
      "success_display": "8/10"
    },
    {
      "id": "schedule-456",
      "name": "Weekly Maintenance",
      "is_batch": true,
      "playbooks": ["system-health", "service-status"],
      "targets": ["192.168.1.50", "webservers"],
      "recurrence_display": "Weekly on Sunday at 03:00",
      "enabled": true
    }
  ]
}
```

---

### POST /api/schedules

Create a new schedule.

**Single Playbook Schedule:**
```json
{
  "name": "Daily Health Check",
  "playbook": "system-health",
  "target": "all",
  "recurrence": {
    "type": "daily",
    "hour": 2,
    "minute": 0
  }
}
```

**Batch Schedule:**
```json
{
  "name": "Weekly Maintenance",
  "is_batch": true,
  "playbooks": ["system-health", "service-status"],
  "targets": ["192.168.1.50", "webservers"],
  "recurrence": {
    "type": "weekly",
    "day_of_week": 6,
    "hour": 3,
    "minute": 0
  }
}
```

---

## Future Enhancements

Planned API improvements:

- **POST /api/run** - JSON body for complex execution parameters
- **GET /api/logs/{name}/latest** - Get latest log as JSON
- **WebSocket /api/stream** - Real-time execution updates
- **Authentication** - API key or JWT tokens
- **Rate limiting** - Prevent abuse
- **Pagination** - For large log lists

## Integration Examples

### Monitoring Dashboard

```python
# Flask app to display status dashboard
from flask import Flask, jsonify
import requests

app = Flask(__name__)
ANSIBLE_API = "http://localhost:3001"

@app.route('/dashboard')
def dashboard():
    playbooks = requests.get(f"{ANSIBLE_API}/api/playbooks").json()
    status = requests.get(f"{ANSIBLE_API}/api/status").json()

    for p in playbooks:
        p['current_status'] = status.get(p['name'], 'unknown')

    return jsonify(playbooks)

if __name__ == '__main__':
    app.run(port=5000)
```

### Scheduled Execution

```python
# APScheduler to run playbooks on schedule
from apscheduler.schedulers.blocking import BlockingScheduler
import requests

BASE_URL = "http://localhost:3001"

def run_health_check():
    requests.get(f"{BASE_URL}/run/system-health?target=all")
    print("Health check triggered")

scheduler = BlockingScheduler()

# Run every day at 2 AM
scheduler.add_job(run_health_check, 'cron', hour=2)

scheduler.start()
```

### Slack Integration

```python
# Send playbook results to Slack
import requests
import time

ANSIBLE_URL = "http://localhost:3001"
SLACK_WEBHOOK = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

def run_and_notify(playbook, target="all"):
    # Trigger playbook
    requests.get(f"{ANSIBLE_URL}/run/{playbook}?target={target}")

    # Wait for completion
    while True:
        status = requests.get(f"{ANSIBLE_URL}/api/status").json()
        if status[playbook] == "ready":
            break
        time.sleep(2)

    # Get results
    playbooks = requests.get(f"{ANSIBLE_URL}/api/playbooks").json()
    result = next(p for p in playbooks if p['name'] == playbook)

    # Send to Slack
    requests.post(SLACK_WEBHOOK, json={
        "text": f"Playbook `{playbook}` completed",
        "attachments": [{
            "fields": [
                {"title": "Target", "value": target, "short": True},
                {"title": "Log", "value": result['latest_log'], "short": True}
            ]
        }]
    })

# Usage
run_and_notify("hardware-inventory", "production")
```

## See Also

- [USAGE.md](USAGE.md) - Web interface usage
- [ADDING_PLAYBOOKS.md](ADDING_PLAYBOOKS.md) - Creating playbooks
- [CONFIGURATION.md](CONFIGURATION.md) - Setup and configuration
