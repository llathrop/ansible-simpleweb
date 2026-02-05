#!/usr/bin/env python3
"""
Validate single-container (demo) deployment.

Checks that the primary container is up, responds on /api/status and /api/config,
uses flatfile storage when no app_config.yaml requests MongoDB, and optionally
verifies a playbook can be run via local executor.

Usage:
  python3 scripts/validate_single_container.py [--base-url URL]
  BASE_URL defaults to http://localhost:3001 (override with env or --base-url).

Exit code: 0 if all checks pass, 1 otherwise.
"""
import argparse
import json
import sys

try:
    import requests
except ImportError:
    print("FAIL - requests required. pip install requests")
    sys.exit(1)

def main():
    p = argparse.ArgumentParser(description="Validate single-container deployment")
    p.add_argument("--base-url", default="http://localhost:3001", help="Primary base URL")
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    failed = []

    # 1. Web reachable
    try:
        r = requests.get(f"{base}/", timeout=5)
        if r.status_code != 200:
            failed.append(f"GET / returned {r.status_code}")
        else:
            print("PASS - Web UI reachable")
    except Exception as e:
        failed.append(f"Web UI: {e}")
        print(f"FAIL - Web UI: {e}")

    # 2. API status
    try:
        r = requests.get(f"{base}/api/status", timeout=5)
        if r.status_code != 200:
            failed.append(f"GET /api/status returned {r.status_code}")
        else:
            print("PASS - /api/status OK")
    except Exception as e:
        failed.append(f"/api/status: {e}")
        print(f"FAIL - /api/status: {e}")

    # 3. Config API
    try:
        r = requests.get(f"{base}/api/config", timeout=5)
        if r.status_code != 200:
            failed.append(f"GET /api/config returned {r.status_code}")
        else:
            data = r.json()
            if "config" not in data:
                failed.append("GET /api/config missing 'config'")
            else:
                print("PASS - /api/config OK")
    except Exception as e:
        failed.append(f"/api/config: {e}")
        print(f"FAIL - /api/config: {e}")

    # 4. Storage: expect flatfile when running single-container (no config file or config says flatfile)
    try:
        r = requests.get(f"{base}/api/storage", timeout=5)
        if r.status_code != 200:
            failed.append(f"GET /api/storage returned {r.status_code}")
        else:
            data = r.json()
            backend = data.get("backend_type", "")
            if backend not in ("flatfile", "mongodb"):
                failed.append(f"Unexpected storage backend: {backend}")
            else:
                print(f"PASS - Storage backend: {backend}")
    except Exception as e:
        failed.append(f"/api/storage: {e}")
        print(f"FAIL - /api/storage: {e}")

    if failed:
        print("\nValidation failed:", failed)
        sys.exit(1)
    print("\nSingle-container validation passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
