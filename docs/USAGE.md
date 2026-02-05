# Usage Guide

Complete guide to using the Ansible Simple Web Interface.

## Table of Contents

- [Web Interface Overview](#web-interface-overview)
- [Running Playbooks](#running-playbooks)
- [Viewing Logs](#viewing-logs)
- [Target Selection](#target-selection)
- [Status Indicators](#status-indicators)
- [Theming](#theming)
- [Config and deployment](#config-and-deployment)
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
     - `192.168.1.100` - Run on a specific host

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

## Theming

The interface supports multiple visual themes for accessibility and user preference.

### Changing Themes

1. Look for the **Theme** dropdown in the footer of any page
2. Select from available themes:
   - **Default** - Light theme (original appearance)
   - **Dark** - Dark backgrounds, easier on eyes in low-light
   - **Low Contrast** - Reduced contrast for visual comfort
   - **Colorblind** - Blue/orange palette for color vision deficiencies
3. Theme applies immediately across all pages
4. Your preference is saved in browser localStorage

### Theme Persistence

- Theme selection persists across browser sessions
- Works across all pages (dashboard, logs, live log viewer)
- No flash when navigating between pages

### Available Themes

**Default (Light)**
- White/light gray backgrounds
- Dark text for maximum readability
- Blue accent colors

**Dark**
- Dark gray/black backgrounds
- Light text
- Muted status colors
- Ideal for low-light environments

**Low Contrast**
- Softer gray backgrounds
- Reduced text contrast
- Gentler on eyes for extended use
- Subtle shadows

**Colorblind**
- Blue/orange color palette
- Distinguishable by users with deuteranopia and protanopia
- Maintains full functionality without relying on red/green

### Custom Themes

You can create custom themes by adding JSON files to `config/themes/`. See [CONFIGURATION.md](CONFIGURATION.md#custom-themes) for details.

## Agent Analysis

The AI agent automatically reviews playbook execution logs and provides structured analysis.

### Where It Appears

- **Log View** – When viewing a job log (cluster job or local), an "Agent Analysis" section shows below the log. Displays Summary, Status, Issues (with level badges), and Suggestions.
- **Job Status** – Same Agent Analysis section with formatted output (no raw JSON).
- **Agent Dashboard** – Navigate to **Agent** in the menu for recent reviews, proposals, and config reports.

### Agent Flow

1. When a playbook job completes, the web server triggers the agent.
2. The agent fetches the log, analyzes it with the LLM, and saves the review.
3. The UI polls or receives a push (Socket.IO `agent_review_ready`) and fetches the full review.
4. The review is rendered as Summary, Status, Issues, Suggestions (formatted HTML).

### Suggested Fix (SSH Errors)

When a playbook fails with SSH public key or connection errors, the UI shows a **Suggested fix** section with:
- Step-by-step instructions (including MikroTik `/user ssh-keys add` for RouterOS)
- The default public key and a Copy button
- A link to the Inventory page to fix credentials

No container access required; all steps are actionable from the web UI.

### Agent Configuration

- **Model**: Default is `qwen2.5-coder:3b`. Change via `LLM_MODEL` in agent-service env.
- **Ollama**: Must run in the `ollama` container only (not on the host). Pull model: `docker compose exec -T ollama ollama pull qwen2.5-coder:3b`.

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for "Agent analysis fails" and "Ollama running on host".

---

## Config and deployment

Navigate to **Config** in the menu to:

- **View and edit app config** – Storage backend (flatfile or MongoDB), agent and feature toggles (DB, agent, workers), deployment options. Changes are saved to `app_config.yaml` in CONFIG_DIR (default `/app/config`). See [CONFIGURATION.md](CONFIGURATION.md) for the full schema.
- **Backup / restore config** – Download the current config as YAML or restore from a previously backed-up file.
- **Backup / restore data** – Download a zip of schedules, inventory, and other app data (flatfile or MongoDB export), or restore from a backup zip. Separate from config backup.
- **Deployment status and “Deploy now”** – When running as a single container or after changing config, the panel shows desired vs current services (DB, agent, workers). If the config requests services that are not yet deployed, click **Deploy now** (or use `POST /api/deployment/run`) to run the deploy playbook. See [REBUILD.md](REBUILD.md) § Single-container and expansion workflow and [PHASE_SINGLE_CONTAINER_BOOTSTRAP.md](PHASE_SINGLE_CONTAINER_BOOTSTRAP.md).

Single-container (demo) mode and building the image are documented in [REBUILD.md](REBUILD.md).

---

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
