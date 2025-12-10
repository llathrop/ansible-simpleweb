#!/usr/bin/env python3
"""
Database Inspector CLI

Quick CLI tool to inspect storage backend data without running the web app.
Connects directly to MongoDB or reads flat files.

Usage:
    # From project directory:
    ./db-inspect.py                    # Interactive mode
    ./db-inspect.py hosts              # List all CMDB hosts
    ./db-inspect.py hosts 192.168.1.50 # Show specific host
    ./db-inspect.py inventory          # List managed inventory
    ./db-inspect.py schedules          # List schedules
    ./db-inspect.py history            # Show recent history
    ./db-inspect.py stats              # Show storage statistics

    # Specify backend explicitly:
    ./db-inspect.py --backend mongodb hosts
    ./db-inspect.py --backend flatfile inventory

Environment Variables (for MongoDB):
    MONGODB_HOST     - MongoDB host (default: localhost)
    MONGODB_PORT     - MongoDB port (default: 27017)
    MONGODB_DATABASE - Database name (default: ansible_simpleweb)
"""

import argparse
import json
import os
import sys
from datetime import datetime

# Add web directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web'))


def get_backend(backend_type=None):
    """Get storage backend instance."""
    # Lazy import to avoid requiring pymongo when using flatfile
    from storage.flatfile import FlatFileStorage

    # Auto-detect backend if not specified
    if backend_type is None:
        # Check if MongoDB is reachable
        try:
            from pymongo import MongoClient
            host = os.environ.get('MONGODB_HOST', 'localhost')
            port = int(os.environ.get('MONGODB_PORT', 27017))
            client = MongoClient(host, port, serverSelectionTimeoutMS=2000)
            client.admin.command('ping')
            backend_type = 'mongodb'
        except Exception:
            backend_type = 'flatfile'

    if backend_type == 'mongodb':
        try:
            from storage.mongodb import MongoDBStorage
        except ImportError:
            print("Error: pymongo not installed. Install with: pip install pymongo")
            print("Falling back to flatfile backend...")
            backend_type = 'flatfile'

    if backend_type == 'mongodb':
        from storage.mongodb import MongoDBStorage
        host = os.environ.get('MONGODB_HOST', 'localhost')
        port = int(os.environ.get('MONGODB_PORT', 27017))
        database = os.environ.get('MONGODB_DATABASE', 'ansible_simpleweb')
        return MongoDBStorage(host=host, port=port, database=database)
    else:
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
        return FlatFileStorage(config_dir=config_dir)


def cmd_hosts(backend, args):
    """List or show CMDB hosts."""
    if args.host:
        # Show specific host
        data = backend.get_host_facts(args.host)
        if data:
            print(json.dumps(data, indent=2, default=str))
        else:
            print(f"Host not found: {args.host}")
            return 1
    else:
        # List all hosts
        hosts = backend.get_all_hosts()
        if not hosts:
            print("No hosts in CMDB")
            return 0

        print(f"{'HOST':<30} {'GROUPS':<30} {'COLLECTIONS':<20} {'LAST UPDATED'}")
        print("-" * 100)
        for h in hosts:
            groups = ', '.join(h.get('groups', [])[:3])
            if len(h.get('groups', [])) > 3:
                groups += '...'
            colls = ', '.join(h.get('collections', []))
            updated = h.get('last_updated', 'N/A')[:19] if h.get('last_updated') else 'N/A'
            print(f"{h['host']:<30} {groups:<30} {colls:<20} {updated}")

        print(f"\nTotal: {len(hosts)} hosts")
    return 0


def cmd_inventory(backend, args):
    """List managed inventory."""
    items = backend.get_all_inventory()
    if not items:
        print("No managed inventory items")
        return 0

    print(f"{'HOSTNAME':<35} {'GROUP':<20} {'DISPLAY NAME':<25} {'VARIABLES'}")
    print("-" * 100)
    for item in items:
        vars_str = ', '.join(item.get('variables', {}).keys())[:30]
        print(f"{item.get('hostname', 'N/A'):<35} {item.get('group', 'N/A'):<20} {item.get('display_name', ''):<25} {vars_str}")

    print(f"\nTotal: {len(items)} items")
    return 0


def cmd_schedules(backend, args):
    """List schedules."""
    schedules = backend.get_all_schedules()
    if not schedules:
        print("No schedules configured")
        return 0

    print(f"{'NAME':<30} {'PLAYBOOK':<25} {'TARGET':<20} {'RECURRENCE':<15} {'ENABLED'}")
    print("-" * 100)
    for sid, s in schedules.items():
        print(f"{s.get('name', sid):<30} {s.get('playbook', 'N/A'):<25} {s.get('target', 'N/A'):<20} {s.get('recurrence', 'N/A'):<15} {s.get('enabled', False)}")

    print(f"\nTotal: {len(schedules)} schedules")
    return 0


def cmd_history(backend, args):
    """Show execution history."""
    limit = args.limit if hasattr(args, 'limit') and args.limit else 20
    history = backend.get_history(limit=limit)

    if not history:
        print("No execution history")
        return 0

    print(f"{'TIMESTAMP':<22} {'PLAYBOOK':<25} {'TARGET':<20} {'STATUS':<12} {'SCHEDULED'}")
    print("-" * 95)
    for entry in history:
        ts = entry.get('started', entry.get('timestamp', 'N/A'))[:19] if entry.get('started') or entry.get('timestamp') else 'N/A'
        status = entry.get('status', 'N/A')
        scheduled = 'Yes' if entry.get('scheduled') else 'No'
        print(f"{ts:<22} {entry.get('playbook', 'N/A'):<25} {entry.get('target', 'N/A'):<20} {status:<12} {scheduled}")

    print(f"\nShowing: {len(history)} entries (use --limit N for more)")
    return 0


def cmd_stats(backend, args):
    """Show storage statistics."""
    backend_type = backend.get_backend_type()
    healthy = backend.health_check()

    print(f"Storage Backend: {backend_type}")
    print(f"Health Check: {'OK' if healthy else 'FAILED'}")
    print()

    # Count items
    hosts = backend.get_all_hosts()
    inventory = backend.get_all_inventory()
    schedules = backend.get_all_schedules()
    history = backend.get_history(limit=10000)

    print("Data Summary:")
    print(f"  CMDB Hosts:      {len(hosts)}")
    print(f"  Inventory Items: {len(inventory)}")
    print(f"  Schedules:       {len(schedules)}")
    print(f"  History Entries: {len(history)}")

    # Collection breakdown
    if hosts:
        all_collections = set()
        all_groups = set()
        for h in hosts:
            all_collections.update(h.get('collections', []))
            all_groups.update(h.get('groups', []))
        print(f"\n  Collection Types: {', '.join(sorted(all_collections)) or 'None'}")
        print(f"  Groups: {', '.join(sorted(all_groups)) or 'None'}")

    return 0


def cmd_interactive(backend):
    """Interactive mode."""
    print(f"Connected to: {backend.get_backend_type()}")
    print("Commands: hosts, inventory, schedules, history, stats, quit")
    print()

    while True:
        try:
            cmd = input("db> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if cmd in ('quit', 'exit', 'q'):
            break
        elif cmd == 'hosts':
            cmd_hosts(backend, argparse.Namespace(host=None))
        elif cmd.startswith('hosts '):
            host = cmd.split(' ', 1)[1]
            cmd_hosts(backend, argparse.Namespace(host=host))
        elif cmd == 'inventory':
            cmd_inventory(backend, argparse.Namespace())
        elif cmd == 'schedules':
            cmd_schedules(backend, argparse.Namespace())
        elif cmd == 'history':
            cmd_history(backend, argparse.Namespace(limit=20))
        elif cmd == 'stats':
            cmd_stats(backend, argparse.Namespace())
        elif cmd == 'help':
            print("Commands: hosts [hostname], inventory, schedules, history, stats, quit")
        elif cmd:
            print(f"Unknown command: {cmd}")
            print("Commands: hosts [hostname], inventory, schedules, history, stats, quit")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Inspect storage backend data without running the web app',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--backend', '-b', choices=['flatfile', 'mongodb'],
                        help='Storage backend (auto-detected if not specified)')

    subparsers = parser.add_subparsers(dest='command')

    # hosts command
    hosts_parser = subparsers.add_parser('hosts', help='List or show CMDB hosts')
    hosts_parser.add_argument('host', nargs='?', help='Specific host to show')

    # inventory command
    subparsers.add_parser('inventory', help='List managed inventory')

    # schedules command
    subparsers.add_parser('schedules', help='List schedules')

    # history command
    history_parser = subparsers.add_parser('history', help='Show execution history')
    history_parser.add_argument('--limit', '-n', type=int, default=20, help='Number of entries')

    # stats command
    subparsers.add_parser('stats', help='Show storage statistics')

    args = parser.parse_args()

    # Get backend
    try:
        backend = get_backend(args.backend)
    except Exception as e:
        print(f"Error connecting to storage: {e}")
        return 1

    # Run command
    if args.command == 'hosts':
        return cmd_hosts(backend, args)
    elif args.command == 'inventory':
        return cmd_inventory(backend, args)
    elif args.command == 'schedules':
        return cmd_schedules(backend, args)
    elif args.command == 'history':
        return cmd_history(backend, args)
    elif args.command == 'stats':
        return cmd_stats(backend, args)
    else:
        # Interactive mode
        return cmd_interactive(backend)


if __name__ == '__main__':
    sys.exit(main())
