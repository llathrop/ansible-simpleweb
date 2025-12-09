# Adding Playbooks

Complete guide to creating and adding custom Ansible playbooks to the web interface.

## Table of Contents

- [Quick Start](#quick-start)
- [File Naming](#file-naming)
- [Automatic Discovery](#automatic-discovery)
- [Playbook Structure](#playbook-structure)
- [Best Practices](#best-practices)
- [Examples](#examples)
- [Testing](#testing)

## Quick Start

### The Process

Adding a playbook is as simple as:

1. Create a `.yml` file in `playbooks/` directory
2. Refresh the web interface
3. Done! It appears automatically

**No restart required. No configuration needed.**

### Example

```bash
# Create new playbook
cat > playbooks/check-disk-space.yml << 'EOF'
---
- name: Check Disk Space
  hosts: all
  gather_facts: yes
  tasks:
    - name: Get disk usage
      shell: df -h /
      register: disk_info
      changed_when: false

    - name: Display results
      debug:
        msg: "{{ disk_info.stdout }}"
EOF

# Refresh browser at http://localhost:3001
# New playbook "Check Disk Space" appears!
```

## File Naming

### Naming Convention

Use lowercase with hyphens:
- `hardware-inventory.yml` ✅
- `system-health.yml` ✅
- `backup-database.yml` ✅

Avoid:
- `HardwareInventory.yml` ❌ (uppercase)
- `hardware_inventory.yml` ❌ (underscores)
- `hardware inventory.yml` ❌ (spaces)

### Display Names

The web interface automatically converts filenames to readable names:

| Filename | Display Name |
|----------|--------------|
| `hardware-inventory.yml` | Hardware Inventory |
| `check-ssl-certs.yml` | Check Ssl Certs |
| `system-health.yml` | System Health |

## Automatic Discovery

### How It Works

The Flask application:
1. Scans `playbooks/` directory on every page load
2. Finds all `.yml` files
3. Extracts playbook name from filename
4. Displays in web interface automatically

### No Configuration Needed

- No playbook registration
- No database updates
- No restart required
- No caching (always current)

### Immediate Availability

```bash
# Create playbook
echo "..." > playbooks/new-playbook.yml

# Refresh browser
# Playbook appears immediately in the interface
```

## Playbook Structure

### Minimum Required Structure

```yaml
---
- name: Your Playbook Name
  hosts: all
  gather_facts: yes
  tasks:
    - name: Your task
      debug:
        msg: "Hello World"
```

### Recommended Structure for JSON Output

```yaml
---
- name: Your Playbook Name
  hosts: all
  gather_facts: yes
  tasks:
    # Collect data
    - name: Gather information
      shell: your-command-here
      register: data
      changed_when: false

    # Format as JSON
    - name: Compile results
      set_fact:
        results:
          hostname: "{{ ansible_hostname }}"
          timestamp: "{{ ansible_date_time.iso8601 }}"
          data: "{{ data.stdout_lines }}"

    # Display JSON output
    - name: Display results
      debug:
        msg: "{{ results | to_nice_json }}"
```

### Key Components

**1. Name:**
```yaml
- name: Descriptive Playbook Name
```
Shows up in Ansible output, helps with debugging.

**2. Hosts:**
```yaml
hosts: all
```
Use `all` to allow target selection from web interface.

**3. Gather Facts:**
```yaml
gather_facts: yes
```
Enables access to `ansible_*` variables (hostname, IP, OS, etc.).

**4. Tasks:**
```yaml
tasks:
  - name: Task description
    module: parameters
```
Individual steps the playbook executes.

## Best Practices

### 1. Always Output JSON

For consistency and parseability:

```yaml
- name: Display as JSON
  debug:
    msg: "{{ your_data | to_nice_json }}"
```

### 2. Include Metadata

Always include hostname and timestamp:

```yaml
- name: Compile results
  set_fact:
    results:
      hostname: "{{ ansible_hostname }}"
      fqdn: "{{ ansible_fqdn }}"
      timestamp: "{{ ansible_date_time.iso8601 }}"
      # ... your data here
```

### 3. Use `changed_when: false` for Read-Only Tasks

Prevents unnecessary "changed" status:

```yaml
- name: Get system info
  shell: uname -a
  register: sysinfo
  changed_when: false  # This is a read-only command
```

### 4. Handle Errors Gracefully

```yaml
- name: Try to get data
  shell: potentially-failing-command
  register: result
  ignore_errors: yes  # Continue even if this fails

- name: Check if it worked
  set_fact:
    status: "{{ 'success' if result.rc == 0 else 'failed' }}"
```

### 5. Use Descriptive Task Names

```yaml
# Good
- name: Check if PostgreSQL is running
  systemd:
    name: postgresql
    state: started

# Bad
- name: Check service
  systemd:
    name: postgresql
    state: started
```

### 6. Target All Hosts

```yaml
hosts: all  # Allows web interface dropdown to work
```

Don't hardcode specific hosts in the playbook. Let the interface control targeting.

## Examples

### Example 1: Certificate Expiry Checker

```yaml
---
- name: SSL Certificate Expiry Check
  hosts: all
  gather_facts: yes
  tasks:
    - name: Find certificate files
      find:
        paths: /etc/ssl/certs
        patterns: "*.pem"
      register: cert_files

    - name: Check expiration dates
      shell: openssl x509 -in "{{ item.path }}" -noout -enddate 2>/dev/null
      register: expiry_dates
      loop: "{{ cert_files.files[:10] }}"
      changed_when: false
      ignore_errors: yes

    - name: Compile report
      set_fact:
        cert_report:
          hostname: "{{ ansible_hostname }}"
          timestamp: "{{ ansible_date_time.iso8601 }}"
          certificates_checked: "{{ expiry_dates.results | length }}"
          results: "{{ expiry_dates.results }}"

    - name: Display report
      debug:
        msg: "{{ cert_report | to_nice_json }}"
```

### Example 2: Memory Usage Alert

```yaml
---
- name: Memory Usage Check
  hosts: all
  gather_facts: yes
  tasks:
    - name: Calculate memory percentage
      set_fact:
        memory_percent: "{{ ((ansible_memtotal_mb - ansible_memfree_mb) / ansible_memtotal_mb * 100) | round(1) }}"

    - name: Set alert level
      set_fact:
        alert_level: >-
          {% if memory_percent | float > 90 %}critical
          {% elif memory_percent | float > 75 %}warning
          {% else %}normal
          {% endif %}

    - name: Compile memory report
      set_fact:
        memory_report:
          hostname: "{{ ansible_hostname }}"
          timestamp: "{{ ansible_date_time.iso8601 }}"
          memory_total_mb: "{{ ansible_memtotal_mb }}"
          memory_free_mb: "{{ ansible_memfree_mb }}"
          memory_percent_used: "{{ memory_percent }}"
          alert_level: "{{ alert_level }}"

    - name: Display report
      debug:
        msg: "{{ memory_report | to_nice_json }}"
```

### Example 3: Database Backup Status

```yaml
---
- name: Database Backup Status
  hosts: all
  gather_facts: yes
  tasks:
    - name: Find latest backup file
      find:
        paths: /var/backups/postgresql
        patterns: "*.sql.gz"
      register: backups

    - name: Get latest backup info
      set_fact:
        latest_backup: "{{ backups.files | sort(attribute='mtime', reverse=true) | first if backups.files else {} }}"

    - name: Calculate backup age
      set_fact:
        backup_age_hours: "{{ ((ansible_date_time.epoch | int) - (latest_backup.mtime | default(0))) / 3600 | round(1) }}"
      when: latest_backup

    - name: Compile backup status
      set_fact:
        backup_status:
          hostname: "{{ ansible_hostname }}"
          timestamp: "{{ ansible_date_time.iso8601 }}"
          latest_backup: "{{ latest_backup.path | default('No backups found') }}"
          backup_age_hours: "{{ backup_age_hours | default('N/A') }}"
          backup_size_mb: "{{ (latest_backup.size / 1024 / 1024) | round(2) if latest_backup else 'N/A' }}"
          status: "{{ 'current' if (backup_age_hours | float) < 24 else 'stale' }}"

    - name: Display status
      debug:
        msg: "{{ backup_status | to_nice_json }}"
```

## Testing

### Test Manually First

Before relying on the web interface, test your playbook manually:

```bash
# Copy playbook to container
docker cp playbooks/your-playbook.yml ansible-simpleweb:/app/playbooks/

# Test run
docker-compose exec -T ansible-web ansible-playbook playbooks/your-playbook.yml -l host_machine

# Check for errors
docker-compose exec -T ansible-web ansible-playbook playbooks/your-playbook.yml -l host_machine --syntax-check
```

### Verify in Web Interface

1. Refresh http://localhost:3001
2. Find your playbook in the list
3. Select a test target
4. Click "Run Playbook"
5. Check log for expected output

### Common Issues

**Playbook doesn't appear:**
- Check filename ends with `.yml`
- Verify file is in `playbooks/` directory
- Refresh browser (hard refresh: Ctrl+F5)

**Playbook fails to run:**
- Check syntax: `ansible-playbook --syntax-check`
- Review logs for error messages
- Verify target host is accessible

**Wrong output format:**
- Ensure using `| to_nice_json` filter
- Check task names are descriptive
- Verify `changed_when: false` on read-only tasks

## Playbook Templates

### Basic Template

```yaml
---
- name: PLAYBOOK_NAME
  hosts: all
  gather_facts: yes
  tasks:
    - name: Collect data
      shell: your-command
      register: data
      changed_when: false

    - name: Format results
      set_fact:
        results:
          hostname: "{{ ansible_hostname }}"
          timestamp: "{{ ansible_date_time.iso8601 }}"
          data: "{{ data.stdout }}"

    - name: Display results
      debug:
        msg: "{{ results | to_nice_json }}"
```

### Multi-Step Template

```yaml
---
- name: PLAYBOOK_NAME
  hosts: all
  gather_facts: yes
  tasks:
    - name: Step 1 - Collect data
      shell: command1
      register: step1
      changed_when: false

    - name: Step 2 - Process data
      shell: command2
      register: step2
      changed_when: false

    - name: Step 3 - Analyze results
      set_fact:
        analysis: "{{ step1.stdout }} + {{ step2.stdout }}"

    - name: Compile final report
      set_fact:
        final_report:
          hostname: "{{ ansible_hostname }}"
          timestamp: "{{ ansible_date_time.iso8601 }}"
          step1_result: "{{ step1.stdout }}"
          step2_result: "{{ step2.stdout }}"
          analysis: "{{ analysis }}"

    - name: Display report
      debug:
        msg: "{{ final_report | to_nice_json }}"
```

## Removing Playbooks

Just as easy as adding:

```bash
# Delete the file
rm playbooks/unwanted-playbook.yml

# Refresh browser
# Playbook disappears from interface
```

## Advanced Topics

### Using Variables

```yaml
vars:
  my_variable: "value"
  another_var: 123
```

### Including Other Files

```yaml
- name: Include common tasks
  include_tasks: common/setup.yml
```

### Using Ansible Vault

```bash
# Encrypt sensitive data
ansible-vault encrypt playbooks/secrets.yml

# Run playbook (will prompt for password)
docker-compose exec -T ansible-web ansible-playbook playbooks/your-playbook.yml --ask-vault-pass
```

Note: Web interface doesn't currently support vault passwords. Use for manual execution only.

## Next Steps

- See [USAGE.md](USAGE.md) for running playbooks via web interface
- See [CONFIGURATION.md](CONFIGURATION.md) for inventory and SSH setup
- See [API.md](API.md) for programmatic access
