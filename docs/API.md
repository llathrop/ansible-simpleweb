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

## Future Enhancements

Planned API improvements:

- **POST /api/run** - JSON body for complex execution parameters
- **GET /api/logs/{name}/latest** - Get latest log as JSON
- **GET /api/inventory** - List available targets
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
