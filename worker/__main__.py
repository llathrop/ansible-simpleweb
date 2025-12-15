#!/usr/bin/env python3
"""
Worker Service Entry Point

Starts the worker service using configuration from environment variables.
"""

import sys
import traceback

from .config import WorkerConfig
from .service import WorkerService


def main():
    """Main entry point for worker service."""
    print("=" * 60)
    print("Ansible Cluster Worker Service")
    print("=" * 60)

    try:
        # Load configuration from environment
        print("\nLoading configuration from environment...")
        config = WorkerConfig.from_env()

        # Validate configuration
        errors = config.validate()
        if errors:
            print("\nConfiguration errors:")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)

        print(f"\nWorker Name: {config.worker_name}")
        print(f"Server URL: {config.server_url}")
        print(f"Tags: {', '.join(config.tags) if config.tags else '(none)'}")
        print(f"Max Concurrent Jobs: {config.max_concurrent_jobs}")
        print(f"Check-in Interval: {config.checkin_interval}s")
        print(f"Sync Interval: {config.sync_interval}s")

        # Create and start service
        print("\nStarting worker service...")
        service = WorkerService(config)
        service.start()

    except KeyboardInterrupt:
        print("\nShutdown requested by user")
        sys.exit(0)
    except ValueError as e:
        print(f"\nConfiguration error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nFatal error: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
