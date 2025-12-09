# Troubleshooting Guide

Common issues and their solutions.

## Table of Contents

- [Container Issues](#container-issues)
- [Web Interface Issues](#web-interface-issues)
- [Playbook Execution Issues](#playbook-execution-issues)
- [SSH Connection Issues](#ssh-connection-issues)
- [Inventory Issues](#inventory-issues)
- [Log Issues](#log-issues)
- [Performance Issues](#performance-issues)

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

**Symptom:** SSH authentication fails

**Solutions:**

```bash
# Check SSH key exists in container
docker-compose exec ansible-web ls -la /app/.ssh/

# Check key permissions
docker-compose exec ansible-web ls -la /app/.ssh/svc-ansible-key
# Should be 600

# Fix permissions if needed
docker-compose exec ansible-web chmod 600 /app/.ssh/svc-ansible-key

# Verify key is added to target's authorized_keys
ssh user@target-host cat ~/.ssh/authorized_keys

# Test SSH connection manually
docker-compose exec ansible-web ssh -i /app/.ssh/svc-ansible-key user@target-host

# Check SSH verbose output
docker-compose exec ansible-web ssh -vvv -i /app/.ssh/svc-ansible-key user@target-host
```

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
