# Troubleshooting Guide

Common issues and their solutions.

## Table of Contents

- [Container Issues](#container-issues)
- [Web Interface Issues](#web-interface-issues)
- [Playbook Execution Issues](#playbook-execution-issues)
- [SSH Connection Issues](#ssh-connection-issues)
- [Inventory Issues](#inventory-issues)
- [Log Issues](#log-issues)
- [Agent analysis fails / debugging](#agent-analysis-fails--debugging)
- [Performance Issues](#performance-issues)
- [Config, deployment, and single-container](#config-deployment-and-single-container)

## Container Issues

### Container Won't Start

**Symptom:** `docker-compose up` fails

**Solutions:**

```bash
# Check if port 3001 is already in use
sudo netstat -tulpn | grep 3001
# or
sudo lsof -i :3001

# Kill process using the port
sudo kill -9 <PID>

# Check Docker is running
sudo systemctl status docker

# Check Docker Compose file syntax
docker-compose config

# View detailed error logs
docker-compose up
```

### Container Starts But Crashes

**Symptom:** Container starts then stops immediately

**Solutions:**

```bash
# Check logs for errors
docker-compose logs

# Check if Flask has syntax errors
docker-compose exec ansible-web python3 -c "import web.app"

# Restart with verbose logging
docker-compose up

# Check file permissions
ls -la web/app.py
```

### Can't Access Web Interface

**Symptom:** http://localhost:3001 doesn't load

**Solutions:**

```bash
# Verify container is running
docker-compose ps

# Check Flask is listening
docker-compose exec ansible-web netstat -tulpn | grep 3001

# Test from inside container
docker-compose exec ansible-web curl http://localhost:3001

# Check firewall
sudo ufw status
sudo ufw allow 3001

# Try 127.0.0.1 instead of localhost
# Open: http://127.0.0.1:3001
```

### Container Has No Network Access

**Symptom:** Can't reach external hosts from container

**Solutions:**

```bash
# Test DNS from container
docker-compose exec ansible-web ping -c 3 8.8.8.8
docker-compose exec ansible-web nslookup google.com

# Check Docker network
docker network ls
docker network inspect ansible-simpleweb_default

# Restart Docker networking
sudo systemctl restart docker
docker-compose down
docker-compose up -d
```

## Web Interface Issues

### Playbooks Don't Appear

**Symptom:** Web interface shows "No playbooks found"

**Solutions:**

```bash
# Check playbooks directory exists
ls -la playbooks/

# Check .yml files exist
ls playbooks/*.yml

# Check file permissions
chmod 644 playbooks/*.yml

# Check directory is mounted correctly
docker-compose exec ansible-web ls -la /app/playbooks/

# Verify volume mount in docker-compose.yml
grep playbooks docker-compose.yml

# Hard refresh browser
# Ctrl+F5 (Windows/Linux) or Cmd+Shift+R (Mac)
```

### Dropdown Shows No Targets

**Symptom:** Target dropdown is empty or shows error

**Solutions:**

```bash
# Check inventory file exists
ls -la inventory/hosts

# Verify inventory file is readable
cat inventory/hosts

# Check for syntax errors in inventory
docker-compose exec ansible-web ansible-inventory --list

# Check volume mount
docker-compose exec ansible-web cat /app/inventory/hosts

# Verify inventory has at least one group
grep '^\[' inventory/hosts
```

### Status Not Updating

**Symptom:** Status stuck on "Running" or doesn't change

**Solutions:**

```bash
# Check Flask logs
docker-compose logs -f

# Check if playbook actually running
docker-compose exec ansible-web ps aux | grep ansible-playbook

# Check JavaScript console in browser
# F12 → Console tab → Look for errors

# Clear browser cache
# Hard refresh: Ctrl+F5

# Check /api/status endpoint
curl http://localhost:3001/api/status
```

### Page Keeps Refreshing

**Symptom:** Page refreshes constantly

**Solutions:**

```bash
# Check API endpoint is responding correctly
curl http://localhost:3001/api/status

# Check browser console for errors
# F12 → Console tab

# Disable auto-refresh temporarily
# Edit web/templates/index.html
# Comment out the setInterval() function
```

## Playbook Execution Issues

### Playbook Fails to Run

**Symptom:** Click "Run" but nothing happens or immediate failure

**Solutions:**

```bash
# Test playbook syntax
docker-compose exec -T ansible-web ansible-playbook playbooks/your-playbook.yml --syntax-check

# Test manually
docker-compose exec -T ansible-web ansible-playbook playbooks/your-playbook.yml -l localhost --check

# Check playbook file permissions
ls -la playbooks/your-playbook.yml

# View detailed errors
docker-compose logs -f

# Check Ansible log
cat logs/ansible.log
```

### Playbook Runs But Shows No Output

**Symptom:** Playbook completes but log is empty or incomplete

**Solutions:**

```bash
# Check log directory permissions
ls -la logs/
docker-compose exec ansible-web ls -la /app/logs/

# Check disk space
df -h
docker-compose exec ansible-web df -h

# Verify run-playbook.sh works
docker-compose exec -T ansible-web bash /app/run-playbook.sh hardware-inventory -l localhost

# Check if log files are being created
ls -ltr logs/ | tail
```

### DEFAULT_GATHER_TIMEOUT deprecation warning

**Symptom:** Ansible prints a deprecation warning about `DEFAULT_GATHER_TIMEOUT`, recommending `module_defaults` instead.

**What we did:** The `[gathering] gather_timeout` setting in `ansible.cfg` triggers this deprecation and has been removed. Playbooks that use `gather_facts: yes` set a 30s timeout via `module_defaults` (e.g. `module_defaults: ansible.builtin.setup: { gather_timeout: 30 }`). If the warning still appears, ensure `ansible.cfg` has no `[gathering]` section and that the primary/workers use the mounted `./ansible.cfg` (see `docker-compose.yml`).

### Playbook Times Out

**Symptom:** Playbook runs for long time then fails with timeout

**Solutions:**

Edit `ansible.cfg`:

```ini
[defaults]
timeout = 120              # Increase SSH timeout
gather_timeout = 120       # Increase fact gathering timeout

[ssh_connection]
timeout = 120
```

Or set in playbook:

```yaml
---
- name: Long Running Playbook
  hosts: all
  gather_facts: yes
  vars:
    ansible_timeout: 120
```

### Task Hangs Indefinitely

**Symptom:** Playbook gets stuck on one task

**Solutions:**

```bash
# Check if task is waiting for input
docker-compose exec ansible-web ps aux | grep ansible

# Kill stuck process
docker-compose exec ansible-web pkill -f ansible-playbook

# Add timeout to task
- name: Potentially slow task
  shell: your-command
  async: 300              # Run for max 5 minutes
  poll: 10                # Check every 10 seconds
```

## SSH Connection Issues

### Connection Refused

**Symptom:** `Connection refused` error in logs

**Solutions:**

```bash
# Check SSH is running on target
ssh user@target-host

# Check SSH port
sudo netstat -tulpn | grep ssh

# Check firewall on target
sudo ufw status
sudo ufw allow 22

# Test from container
docker-compose exec ansible-web ssh user@target-host

# Check target is reachable
docker-compose exec ansible-web ping -c 3 target-host
```

### Permission Denied (publickey)

**Symptom:** SSH authentication fails with:

```
ssh connection failed: Failed to authenticate public key: Access denied for 'publickey'.
Authentication that can continue: publickey,password
```

This means the target host rejected public key authentication. Common causes: wrong user, wrong key path, or the public key is not in the target's `authorized_keys`.

**Solutions:**

```bash
# 1. Verify inventory configuration
# Ensure ansible_user and ansible_ssh_private_key_file match your setup:
# [routers]
# router1 ansible_host=192.168.1.1 ansible_user=admin ansible_ssh_private_key_file=/app/ssh-keys/your-key

# Check SSH key exists in container (and at the path used in inventory)
docker-compose exec ansible-web ls -la /app/.ssh/
docker-compose exec ansible-web ls -la /app/ssh-keys/

# Key permissions must be 600 (owner read/write only)
docker-compose exec ansible-web ls -la /app/.ssh/svc-ansible-key
# Should be 600
docker-compose exec ansible-web chmod 600 /app/.ssh/svc-ansible-key

# 2. Verify the public key is on the target
# The public key (.pub) must be in ~/.ssh/authorized_keys on the target host
# for the ansible_user you use.
ssh user@target-host cat ~/.ssh/authorized_keys

# 3. Test SSH connection manually (use same user and key path as inventory)
docker-compose exec ansible-web ssh -i /app/.ssh/svc-ansible-key user@target-host

# 4. Debug with verbose output
docker-compose exec ansible-web ssh -vvv -i /app/.ssh/svc-ansible-key user@target-host
```

**Inventory checklist:**
- `ansible_user` must match a user on the target who has your public key in `~/.ssh/authorized_keys`
- `ansible_ssh_private_key_file` must point to the private key file inside the container (e.g. `/app/ssh-keys/mykey` or `/app/.ssh/svc-ansible-key`)
- In cluster mode, workers run Ansible; ensure the key exists at the same path on the worker. Workers must mount `./.ssh:/app/.ssh:ro` and `./ssh-keys:/app/ssh-keys:ro` (same as primary) in docker-compose

**How to fix SSH publickey (step-by-step):**

1. **Choose the SSH user and key**  
   Decide which user on the target host will run Ansible (e.g. `admin`) and which private key you will use (e.g. `/app/ssh-keys/mykey` or `/app/.ssh/svc-ansible-key`).

2. **Put the key where the app/worker runs**  
   Copy the private key into the container (or mount it). Example:
   ```bash
   # If using docker-compose, add a volume or COPY in Dockerfile, e.g.:
   # volumes: - ./ssh-keys:/app/ssh-keys:ro
   docker compose exec ansible-web ls -la /app/ssh-keys/
   # Permissions must be 600
   docker compose exec ansible-web chmod 600 /app/ssh-keys/your-key
   ```

3. **Add the public key to the target host**  
   On the **target** machine, for the user you chose (e.g. `admin`):
   ```bash
   # On your laptop or wherever you have the key:
   cat /path/to/your-key.pub
   # On the target (as that user or as root):
   mkdir -p ~/.ssh
   echo "paste-the-public-key-line" >> ~/.ssh/authorized_keys
   chmod 700 ~/.ssh
   chmod 600 ~/.ssh/authorized_keys
   ```

4. **Set inventory for that host**  
   In `inventory/hosts` (or your inventory file), set `ansible_user` and the key path:
   ```ini
   [routers]
   router1 ansible_host=192.168.1.1 ansible_user=admin ansible_ssh_private_key_file=/app/ssh-keys/your-key
   ```
   Use the **exact** path as seen inside the container (e.g. `/app/ssh-keys/your-key`).

5. **Test SSH from the container**  
   From the host:
   ```bash
   docker compose exec ansible-web ssh -i /app/ssh-keys/your-key -o StrictHostKeyChecking=no admin@192.168.1.1
   ```
   If this works, Ansible should work. If it fails, use `-vvv` to see why (wrong user, key not in authorized_keys, permissions, etc.).

6. **Cluster mode**  
   If you use workers, the same key path must exist on each worker (e.g. same volume or sync). Run the same `ssh -i ...` test from a worker container if needed.

### Worker: "no such identity: /app/.ssh/svc-ansible-key"

**Symptom:** Job runs on a worker and fails with:

```
no such identity: /app/.ssh/svc-ansible-key: No such file or directory
svc-ansible@192.168.1.55: Permission denied (publickey,password).
```

This means the worker container does not have the SSH key at that path. Workers must mount `./.ssh:/app/.ssh:ro` (same as the primary).

**Solutions:**

1. **Docker Compose:** Force recreate workers so they pick up the mount:
   ```bash
   docker compose up -d --force-recreate worker-1 worker-2 worker-3
   ```

2. **Verify the key exists on the host:**
   ```bash
   ls -la .ssh/svc-ansible-key
   ```
   If missing, create `.ssh` and add the key there.

3. **Verify the worker sees the key:**
   ```bash
   docker compose exec worker-1 ls -la /app/.ssh/svc-ansible-key
   ```
   If this fails, the mount is wrong or the host `.ssh` is empty.

4. **Deploy playbook (ansible-worker-*):** If workers were created before the SSH mount was added, remove and redeploy:
   ```bash
   docker rm -f ansible-worker-1 ansible-worker-2 ansible-worker-3
   ansible-playbook playbooks/deploy/expand.yml -e deploy_workers=1 -e worker_count_to_add=3
   ```

5. **Remote worker host:** If workers run on a different machine, `.ssh` is gitignored and will not exist after clone. Create it and copy the key:
   ```bash
   mkdir -p /path/to/project/.ssh
   scp primary-host:/path/to/project/.ssh/svc-ansible-key /path/to/project/.ssh/
   chmod 600 /path/to/project/.ssh/svc-ansible-key
   ```
   Then recreate the worker containers on that host.

**For MikroTik RouterOS (key auth):** Add the key via RouterOS CLI. Connect via Winbox or SSH, then run:
```
/user ssh-keys add user=YOUR_USER public-key="ssh-rsa AAAA..."
```
Replace `YOUR_USER` with your `ansible_user` (e.g. `llathrop`). Paste your full public key (from `cat ~/.ssh/id_rsa.pub` or the **Copy public key** button in the Suggested fix card when SSH fails).

**No container access?** When a playbook fails with SSH publickey, the log view and job status pages show a **Suggested fix** card with steps, your public key (if available), and a **Copy public key** button. Use that to add the key to your target.

### MikroTik RouterOS: password auth (no keys)

**Symptom:** You want to use password auth for MikroTik (e.g. for testing) instead of SSH keys.

**Setup:** This project uses `inventory/group_vars/routers.yml` to force password auth and read the password from `ROUTER_PASSWORD`:

1. Ensure **no SSH keys** are configured for your user on the MikroTik (RouterOS disables password login if keys exist). Remove keys: `/user ssh-keys remove [find where user=llathrop]`.

2. Create a `.env` file in the project root (or export in shell):
   ```
   ROUTER_PASSWORD=your_mikrotik_password
   ```
   Docker Compose picks up `.env` automatically; workers get `ROUTER_PASSWORD`.

3. Restart workers so they pick up the env: `docker compose up -d worker-1 worker-2 worker-3`.

4. Run the playbook. The inventory uses `ansible_ssh_common_args` to force password auth and skip publickey.

### Host Key Verification Failed

**Symptom:** `Host key verification failed` error

**Solutions:**

```bash
# Option 1: Disable in ansible.cfg (already done)
grep host_key_checking ansible.cfg

# Option 2: Add to known_hosts
docker-compose exec ansible-web ssh-keyscan target-host >> /root/.ssh/known_hosts

# Option 3: Remove old key
docker-compose exec ansible-web ssh-keygen -R target-host
```

### Sudo Password Required

**Symptom:** Tasks fail with "Missing sudo password"

**Solutions:**

```bash
# Configure passwordless sudo on target
ssh target-host
sudo visudo
# Add: username ALL=(ALL) NOPASSWD:ALL

# Or add password to inventory
[servers]
server ansible_become_pass=password

# Or pass at runtime
docker-compose exec -T ansible-web ansible-playbook playbooks/your-playbook.yml --ask-become-pass
```

## Inventory Issues

### No Hosts Matched

**Symptom:** `skipping: no hosts matched`

**Solutions:**

```bash
# Check inventory syntax
docker-compose exec -T ansible-web ansible-inventory --list

# Verify host/group exists
docker-compose exec -T ansible-web ansible-inventory --graph

# Check inventory file path
docker-compose exec -T ansible-web cat /app/ansible.cfg | grep inventory

# Test specific host
docker-compose exec -T ansible-web ansible target-host --list-hosts
```

### Invalid Inventory Syntax

**Symptom:** Errors parsing inventory file

**Solutions:**

```bash
# Validate inventory
docker-compose exec -T ansible-web ansible-inventory --list

# Check for common issues:
# - Missing closing bracket ]
# - Invalid characters in group names
# - Duplicate group definitions

# Example valid syntax:
[groupname]
hostname ansible_user=user

# Example invalid:
[group name]     # No spaces in names
hostname user=test  # Wrong syntax
```

## Log Issues

### Logs Not Appearing

**Symptom:** No log files created after playbook runs

**Solutions:**

```bash
# Check logs directory exists and is writable
ls -la logs/
docker-compose exec ansible-web ls -la /app/logs/

# Check disk space
df -h logs/

# Run playbook manually to test
docker-compose exec -T ansible-web bash /app/run-playbook.sh test-playbook

# Check if script has execute permissions
ls -la run-playbook.sh
chmod +x run-playbook.sh
```

### Can't View Log Files

**Symptom:** "Log file not found" when clicking View Log

**Solutions:**

```bash
# Check log file exists
ls -la logs/

# Check Flask can access logs
docker-compose exec ansible-web ls -la /app/logs/

# Check file permissions
chmod 644 logs/*.log

# Verify log path in Flask app
docker-compose exec ansible-web grep LOGS_DIR /app/web/app.py
```

### Logs Too Large

**Symptom:** Browser hangs when viewing large logs

**Solutions:**

```bash
# Check log file size
ls -lh logs/*.log

# View large log in terminal instead
docker-compose exec -T ansible-web tail -n 100 /app/logs/large-log.log

# Or use less
docker-compose exec -T ansible-web less /app/logs/large-log.log

# Limit playbook output
- name: Task with lots of output
  shell: command
  register: result
  no_log: true        # Don't log output
```

## Agent analysis fails / debugging

**Symptom:** "Agent Analysis" in the log view or job status shows an error, "LLM Server Unreachable", or never completes (stuck on Pending/Running).

**Where to find logs:** The agent does not write a log file. All interaction (trigger received, LLM calls, review saved, errors) is logged to **stderr** and appears only in the **agent container logs**. Full steps are in [ARCHITECTURE.md §6 Logs and debugging](ARCHITECTURE.md#6-logs-and-debugging).

**Quick checks:**

1. **Trigger from web** (did the primary tell the agent to run?):
   ```bash
   docker compose logs ansible-web 2>&1 | grep -i agent
   ```
   Look for "Agent review triggered for job …" after a job completes. If you see "Failed to trigger agent review …", the web cannot reach the agent (check `AGENT_SERVICE_URL`, network, or that `agent-service` is running).

2. **Agent behavior** (what did the agent do?):
   ```bash
   docker compose logs agent-service
   # or follow live:
   docker compose logs -f agent-service
   ```
   After a job completes, look for: `Received trigger for job …`, `Starting review for job …`, then either success (`Review saved …`, `Notified web …`) or errors (e.g. "Failed to fetch job details", "Log file not found", "LLM Server Unreachable", or a Python traceback).

3. **LLM model:** The default is a **lightweight** model (`qwen2.5-coder:1.5b`). To use a larger model, set `LLM_MODEL` in the agent-service environment (e.g. in `docker-compose.yml`: `LLM_MODEL=qwen2.5-coder:7b`), then restart the agent container. Pull the model in the ollama container: `docker compose exec ollama ollama run <model-name>`.

4. **LLM reachable:** Ollama runs **in the `ollama` container only**. The agent uses `LLM_API_URL=http://ollama:11434/v1`. Ensure the `ollama` container is up: `docker compose ps ollama`. **Verify**: run `./scripts/verify-ollama.sh`. **Logs**: `docker compose logs ollama`. If you see Ollama running on the host, see **"Ollama running on the host"** below.

5. **Review API:** From the host, `curl -s http://localhost:3001/api/agent/review-status/<job_id>` returns `pending` | `running` | `completed` | `error`. If the agent logs show "Review saved" but the UI does not update, check that the UI is receiving the push event or polling this endpoint and then fetching the full review.

### Verify agent is up and responding

If the UI shows "Pending" forever or "Error checking analysis", confirm the agent service is running and reachable:

1. **Agent health (from host):**
   ```bash
   # Agent container publishes 5001:5000; from host:
   curl -s http://localhost:5001/health
   # Should return JSON with "status": "online", "service": "agent-service"

   # From inside the web container (same network as agent):
   docker compose exec ansible-web curl -s http://agent-service:5000/health
   ```

2. **Web → agent URL:** The web app uses `AGENT_SERVICE_URL` (e.g. in `.env` or `docker-compose.yml`). It must be the URL the **web container** uses to reach the agent (e.g. `http://agent-service:5000`). Check:
   ```bash
   docker compose exec ansible-web env | grep AGENT
   ```

3. **Trigger after job completion:** When a job finishes, the web should POST to the agent. In web logs:
   ```bash
   docker compose logs ansible-web 2>&1 | grep -i agent
   ```
   Look for "Agent review triggered for job …" (success) or "Failed to trigger agent review …" (web cannot reach agent or agent error).

4. **Agent processing:** After a trigger, the agent writes a status file and then a review file. Check agent logs:
   ```bash
   docker compose logs agent-service
   ```
   Look for "Received trigger for job …", "Starting review for job …", then either "Review saved …" / "Notified web …" or an error/traceback.

If the agent is not running or the web cannot reach it, the UI will stay on "Pending" and the elapsed counter will still run (from when the page started waiting); fix the agent/URL and run another job to test.

### Ollama running on the host (stop it)

**Symptom:** You see an Ollama process running on your host (not in Docker). You should **never** see this—this project does **not** start Ollama on the host.

**Cause:** This project uses only the `ollama` container and does **not** publish port 11434 to the host (to avoid tools connecting and triggering host Ollama). Host Ollama is started by something else:
- **Cursor IDE**: If Cursor is configured to use a local LLM at localhost:11434, it may start Ollama when you use the AI panel. Go to Cursor Settings → Models and disable local Ollama or point it elsewhere.
- **Ollama Desktop app**: Quit it or disable "Start Ollama when computer starts".
- A previous manual install, systemd service, or other tool.

**Fix:** Stop host Ollama and use only the container:

```bash
# Stop any host Ollama process
pkill ollama

# If you use systemd (user service):
systemctl --user stop ollama
systemctl --user disable ollama   # Prevent auto-start

# Then ensure the container is used:
docker compose up -d ollama
docker compose ps ollama   # Should show "Up"
```

**Never** run `ollama run ...` or `ollama serve` directly on the host. Always use the container: `docker compose exec ollama ollama run <model>`.

**Test:** If host Ollama still starts when you run playbooks, set `AGENT_TRIGGER_ENABLED=false` in the ansible-web environment (docker-compose) and restart. This disables the agent trigger on job completion. If host Ollama stops appearing, the trigger→agent→LLM chain was involved; if it still appears, the cause is elsewhere (e.g. Cursor).

## Performance Issues

### Slow Playbook Execution

**Symptom:** Playbooks take very long to run

**Solutions:**

```bash
# Enable pipelining (already in ansible.cfg)
grep pipelining ansible.cfg

# Increase parallel execution
# Edit ansible.cfg
[defaults]
forks = 10            # Run on 10 hosts at once

# Disable fact gathering if not needed
- name: Fast Playbook
  hosts: all
  gather_facts: no    # Skip fact gathering
```

### High Memory Usage

**Symptom:** Container using lots of RAM

**Solutions:**

```bash
# Check container stats
docker stats ansible-simpleweb

# Limit container memory
# Edit docker-compose.yml
services:
  ansible-web:
    mem_limit: 512m

# Restart with limit
docker-compose down
docker-compose up -d
```

### Slow Web Interface

**Symptom:** Web pages load slowly

**Solutions:**

```bash
# Check container CPU usage
docker stats ansible-simpleweb

# Check for large log files
du -sh logs/

# Reduce auto-refresh frequency
# Edit web/templates/index.html
# Change: setInterval(function() { ... }, 5000); // 5 seconds instead of 3

# Clear old logs
rm logs/*-2024*.log  # Remove old logs
```

## Config, deployment, and single-container

### Config changes not applied

**Symptom:** After editing config on the Config page, storage or features do not change.

**Solutions:**

- Config is written to `app_config.yaml` in CONFIG_DIR (default `/app/config`). Ensure the container has that directory writable (e.g. volume mount). Restart the web container so it reloads config on startup; storage is initialized at startup from config.
- For storage backend (flatfile vs MongoDB), switching to MongoDB requires MongoDB to be reachable; otherwise health check may fail. See [CONFIGURATION.md](CONFIGURATION.md).

### Deployment / "Deploy now" fails

**Symptom:** Clicking "Deploy now" or `POST /api/deployment/run` returns an error or playbook not found.

**Solutions:**

- The deploy playbook is `playbooks/deploy/expand.yml`. It must exist and be readable from the primary container. From repo root: `docker compose exec ansible-web ls -la /app/playbooks/deploy/expand.yml`.
- Deployment uses `ansible-playbook` inside the container. For Docker-based deployment (adding DB/agent/worker containers), the Docker socket must be available to the primary (e.g. mount `/var/run/docker.sock`). See [REBUILD.md](REBUILD.md) § Single-container and expansion workflow.
- Check primary logs: `docker compose logs ansible-web 2>&1 | grep -i bootstrap` or `grep -i deploy`.

### Single-container validation fails

**Symptom:** `python3 scripts/validate_single_container.py` fails (e.g. Web UI or /api/status not reachable).

**Solutions:**

- Ensure the primary is running: `docker compose -f docker-compose.single.yml ps` (or your compose file). Access the UI at the URL you pass to the script (default http://localhost:3001).
- If you use a different port or host, run: `python3 scripts/validate_single_container.py --base-url http://your-host:PORT`.
- Install requests if missing: `pip install requests`.

## General Debugging

### Enable Verbose Logging

```bash
# Run with verbose output
docker-compose exec -T ansible-web ansible-playbook playbooks/your-playbook.yml -vvv

# Check all logs
docker-compose logs --tail=100

# Follow logs in real-time
docker-compose logs -f
```

### Reset Everything

```bash
# Nuclear option - reset everything
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Or just restart
docker-compose restart
```

### Get Support Information

```bash
# Gather debugging info
echo "=== Docker Version ==="
docker --version

echo "=== Container Status ==="
docker-compose ps

echo "=== Container Logs ==="
docker-compose logs --tail=50

echo "=== Ansible Version ==="
docker-compose exec -T ansible-web ansible --version

echo "=== Inventory ==="
docker-compose exec -T ansible-web ansible-inventory --list

echo "=== Disk Space ==="
df -h
docker-compose exec -T ansible-web df -h
```

## Still Having Issues?

1. Check application logs: `docker-compose logs -f`
2. Check Ansible logs: `cat logs/ansible.log`
3. Test manually: `docker-compose exec -T ansible-web ansible-playbook ...`
4. Review documentation: [USAGE.md](USAGE.md), [CONFIGURATION.md](CONFIGURATION.md)
5. Check git history for recent changes: `git log`

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `Connection refused` | SSH not running | Start sshd on target |
| `Permission denied` | SSH key issue | Check keys and permissions |
| `No hosts matched` | Inventory issue | Verify inventory syntax |
| `Timeout` | Network/firewall | Check connectivity |
| `Module not found` | Python issue | Install required module |
| `Syntax error` | Playbook YAML | Check YAML syntax |
| `Sudo password` | Missing sudo config | Configure NOPASSWD sudo |

## Prevention

### Best Practices to Avoid Issues

1. **Test playbooks manually** before using web interface
2. **Check logs regularly** for warnings
3. **Keep backups** of working configurations
4. **Document changes** in git commits
5. **Monitor resource usage** (disk, memory)
6. **Update regularly** (Docker, Ansible)
7. **Use version control** for playbooks
8. **Test in staging** before production

---

**If you find a solution to an issue not listed here, please document it!**
