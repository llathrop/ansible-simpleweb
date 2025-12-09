# Usage Guide

Complete guide to using the Ansible Simple Web Interface.

## Table of Contents

- [Web Interface Overview](#web-interface-overview)
- [Running Playbooks](#running-playbooks)
- [Viewing Logs](#viewing-logs)
- [Target Selection](#target-selection)
- [Status Indicators](#status-indicators)
- [API Usage](#api-usage)

## Web Interface Overview

Access the interface at: **http://localhost:3001**

### Main Dashboard

The dashboard displays all available playbooks in a grid layout. Each playbook card shows:

- **Playbook Name** - Auto-generated from filename
- **Status Badge** - Current execution status
- **Last Run** - Timestamp of most recent execution
- **Latest Log** - Name of the most recent log file
- **Target Dropdown** - Select which host/group to run on
- **Run Button** - Execute the playbook
- **View Log Button** - Open the latest log file

### Auto-Refresh

The page automatically checks for status updates every 3 seconds. When a playbook completes, the page refreshes to show the updated status and log file.

## Running Playbooks

### Basic Execution

1. **Select Target**
   - Click the dropdown under "Target Host/Group"
   - Choose from:
     - `all` - Run on all configured hosts
     - `groupname (group)` - Run on all hosts in a group
     - `192.168.1.50` - Run on a specific host

2. **Click "Run Playbook"**
   - Button changes to "Running..." with animated badge
   - Playbook executes in background
   - Page automatically refreshes when complete

3. **View Results**
   - Status badge updates (Completed/Failed)
   - "View Log" button becomes available
   - Click to see full execution output

### Status Flow

```
Ready → Running → Completed/Failed → Ready (after 5 seconds)
```

### Preventing Duplicate Runs

- Only one instance of each playbook can run at a time
- "Run Playbook" button is disabled while running
- Dropdown is disabled during execution

## Viewing Logs

### Latest Log (Quick Access)

Click **"View Log"** on any playbook card to see the most recent execution log.

### All Logs (Browse History)

1. Click **"All Logs"** in the navigation menu
2. See complete list of all execution logs
3. Sorted by date (newest first)
4. Shows file size and modification time
5. Click any log to view contents

### Log Format

Logs are named: `<playbook-name>-YYYYMMDD-HHMMSS.log`

Example: `hardware-inventory-20251209-004455.log`

### Log Contents

Each log contains:
- Ansible playbook output
- Task execution results
- JSON-formatted data (from playbooks)
- Error messages (if any)
- Execution summary

## Target Selection

### Available Targets

The dropdown automatically discovers all targets from `inventory/hosts`:

**Special Targets:**
- `all (all hosts)` - Executes on every configured host

**Groups:**
- `host_machine (group)` - All hosts in [host_machine] group
- `production (group)` - All hosts in [production] group
- etc.

**Individual Hosts:**
- `192.168.1.50` - Single specific host
- `server1.example.com` - Single specific host

### Target Discovery

Targets are discovered automatically:
- On every page load
- No caching
- No restart required
- Add hosts to inventory → refresh page → they appear

### Multi-Host Execution

When targeting a group or `all`:
- Playbook runs sequentially on each host
- Log shows results from all hosts
- Execution continues even if one host fails
- Final status reflects overall success/failure

## Status Indicators

### Status Badges

**Ready** (Green)
- Playbook is idle and ready to run
- No recent execution

**Running** (Orange, Animated)
- Playbook is currently executing
- Pulsing animation indicates activity
- Typically lasts 10-60 seconds depending on playbook

**Completed** (Blue)
- Playbook finished successfully
- Exit code 0
- Check log for full results
- Resets to "Ready" after 5 seconds

**Failed** (Red)
- Playbook encountered an error
- Non-zero exit code
- Check log for error details
- Resets to "Ready" after 5 seconds

### Real-Time Updates

Status checks occur automatically:
- Every 3 seconds via background API call
- Non-intrusive (no page flicker)
- Full refresh only when status changes
- Prevents stale information

## API Usage

For external integrations or automation, use the REST API endpoints.

### Get All Playbooks

```bash
curl http://localhost:3001/api/playbooks
```

Returns JSON array with playbook details.

### Get Status

```bash
curl http://localhost:3001/api/status
```

Returns current status of all playbooks.

### Run Playbook (via URL)

```bash
# Run on default target (host_machine)
curl http://localhost:3001/run/hardware-inventory

# Run on specific target
curl "http://localhost:3001/run/hardware-inventory?target=all"
```

See [API.md](API.md) for complete API documentation.

## Best Practices

### Playbook Execution

1. **Always select the correct target** before running
2. **Wait for completion** before running again
3. **Check logs** after each run for errors
4. **Monitor status badges** for real-time feedback

### Log Management

1. Logs are automatically created and timestamped
2. All logs are preserved (no automatic cleanup)
3. Review logs regularly for issues
4. Old logs can be manually deleted from `logs/` directory

### Performance

- Playbooks run in background threads (non-blocking)
- Multiple different playbooks can run simultaneously
- Same playbook cannot run twice at once
- Page updates don't interfere with execution

## Keyboard Shortcuts

Currently none implemented. All actions require mouse clicks.

## Mobile Usage

The interface is mobile-friendly:
- Responsive grid layout
- Touch-friendly buttons
- Works on tablets and phones
- Same functionality as desktop

## Common Workflows

### Daily System Check

1. Open interface
2. Select "all" from dropdown
3. Run: system-health
4. Run: service-status
5. View logs to verify all systems normal

### Hardware Inventory

1. Select specific host from dropdown
2. Run: hardware-inventory
3. View log for CPU, RAM, disk details
4. Export log for documentation

### Software Audit

1. Select host group (e.g., "production")
2. Run: software-inventory
3. View log for package versions
4. Compare across hosts for consistency

## Troubleshooting

For common issues and solutions, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Advanced Features

### Custom Playbooks

See [ADDING_PLAYBOOKS.md](ADDING_PLAYBOOKS.md) for details on creating your own playbooks.

### Multi-Host Configuration

See [CONFIGURATION.md](CONFIGURATION.md) for inventory setup and SSH configuration.
