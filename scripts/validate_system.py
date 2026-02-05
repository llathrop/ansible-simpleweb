import requests
import json
import time
import sys

# Configuration
WEB_URL = "http://localhost:3001"
AGENT_URL = "http://localhost:5001"

def print_result(name, success, details=None):
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {name}")
    if details:
        print(f"   Details: {details}")

def validate_web():
    print("\n--- Validating Ansible Web ---")
    try:
        # Check Root
        resp = requests.get(WEB_URL, timeout=5)
        print_result("Web UI Reachable", resp.status_code == 200, f"Status: {resp.status_code}")
        
        # Check Agent Overview (Backend Proxy)
        # This verifies the web -> agent connection and the agent -> web loop
        resp = requests.get(f"{WEB_URL}/api/agent/overview", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            is_online = data.get('status') == 'online'
            print_result("Web -> Agent Integration", is_online, f"Health: {data.get('status')}")
        else:
            print_result("Web -> Agent Integration", False, f"API Error: {resp.status_code} - {resp.text}")

        # Check Workers
        resp = requests.get(f"{WEB_URL}/api/workers", timeout=5)
        if resp.status_code == 200:
            workers = resp.json()
            worker_count = len(workers)
            print_result("Cluster Status", worker_count > 0, f"Connected Workers: {worker_count}")
            for w in workers:
                print(f"   - {w.get('name')} ({w.get('status')})")
        else:
            print_result("Cluster Status", False, f"API Error: {resp.status_code}")
            
    except Exception as e:
        print_result("Ansible Web Connection", False, str(e))

def validate_agent():
    print("\n--- Validating Agent Service ---")
    try:
        # Health Check
        resp = requests.get(f"{AGENT_URL}/health", timeout=5)
        if resp.status_code == 200:
            health = resp.json()
            print_result("Agent Health", True, json.dumps(health, indent=2))
        else:
            print_result("Agent Health", False, f"Status: {resp.status_code}")
            return # Stop if unhealthy

        # Playbook Generation (Simple)
        payload = {"request": "Create a playbook to install nginx on ubuntu"}
        resp = requests.post(f"{AGENT_URL}/agent/generate", json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            has_playbook = 'generated_playbook' in data
            print_result("Playbook Generation", has_playbook, "Generated Nginx Playbook")
        elif resp.status_code == 403:
             print_result("Playbook Generation", False, f"Blocked by Guardrail (Expected if request was unsafe, but this should pass): {resp.text}")
        else:
            print_result("Playbook Generation", False, f"Error: {resp.status_code} - {resp.text}")

        # Config Analysis
        config_sample = """
        /system identity set name=RouterOS
        /user add name=admin password=admin group=full
        /ip service set telnet disabled=no
        """
        payload = {"content": config_sample}
        resp = requests.post(f"{AGENT_URL}/agent/analyze-config", json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            result = data.get('result', {})
            score = result.get('security_score')
            print_result("Config Analysis", True, f"Score: {score}, Risks: {len(result.get('critical_risks', []))}")
        else:
            print_result("Config Analysis", False, f"Error: {resp.status_code} - {resp.text}")
            
        # Schedule Monitor
        resp = requests.post(f"{AGENT_URL}/agent/schedule-monitor", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print_result("Schedule Monitor", True, f"Schedules Checked: {data.get('schedules_checked')}")
        else:
             print_result("Schedule Monitor", False, f"Error: {resp.status_code} - {resp.text}")

    except Exception as e:
        print_result("Agent Service Connection", False, str(e))

if __name__ == "__main__":
    print("Starting System Validation...")
    validate_web()
    validate_agent()
    print("\nValidation Complete.")
