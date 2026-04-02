# UniFi AP Management Playbooks

This suite of playbooks allows for direct management and monitoring of UniFi Access Points via SSH.

## Prerequisites
* SSH must be enabled on the APs (configured in the UniFi Controller).
* An inventory group named `unifi_aps` must be defined.

## Playbooks
1. **get_config.yml**: Fetches `/tmp/system.cfg` from the AP and saves it to the `logs/` directory.
2. **get_logs.yml**: Retrieves the last 100 lines of system logs and 50 lines of kernel logs.
3. **get_stats.yml**: Executes `mca-dump` to gather detailed JSON statistics about clients, traffic, and hardware status.

## Usage
Run via the web interface or CLI:
```bash
./run-playbook.sh playbooks/network/unifi/get_stats.yml unifi_aps
```
