#!/usr/bin/env python3
"""
Storage Migration Script

Migrates data between storage backends (flatfile <-> MongoDB).
Can be run from inside the container or with appropriate environment variables.

Migrates the following data:
    - Schedules: Playbook scheduling configurations
    - History: Playbook execution history
    - Inventory: Managed inventory items (hosts/groups)
    - Host Facts: CMDB data including collected facts and history

Usage:
    # From inside container:
    python3 /app/web/migrate_storage.py --from flatfile --to mongodb
    python3 /app/web/migrate_storage.py --from mongodb --to flatfile

    # Via docker exec:
    docker exec ansible-simpleweb python3 /app/web/migrate_storage.py --from flatfile --to mongodb

    # Preview migration without making changes:
    docker exec ansible-simpleweb python3 /app/web/migrate_storage.py --from flatfile --to mongodb --dry-run

    # Force overwrite existing data:
    docker exec ansible-simpleweb python3 /app/web/migrate_storage.py --from flatfile --to mongodb --force

Options:
    --from      Source backend ('flatfile' or 'mongodb')
    --to        Target backend ('flatfile' or 'mongodb')
    --dry-run   Show what would be migrated without making changes
    --force     Overwrite existing data in target (default: skip existing)
"""

import argparse
import os
import sys

# Add web directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.flatfile import FlatFileStorage
from storage.mongodb import MongoDBStorage


def get_storage(backend_type: str):
    """Get storage instance by type."""
    if backend_type == 'flatfile':
        config_dir = os.environ.get('CONFIG_DIR', '/app/config')
        return FlatFileStorage(config_dir=config_dir)
    elif backend_type == 'mongodb':
        host = os.environ.get('MONGODB_HOST', 'mongodb')
        port = int(os.environ.get('MONGODB_PORT', 27017))
        database = os.environ.get('MONGODB_DATABASE', 'ansible_simpleweb')
        return MongoDBStorage(host=host, port=port, database=database)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")


def migrate_schedules(source, target, dry_run=False, force=False):
    """
    Migrate playbook schedules from source to target.

    Schedules define when playbooks should run automatically (one-time,
    hourly, daily, weekly, monthly). Each schedule includes:
    - Playbook name and target host/group
    - Recurrence configuration
    - Last run status and timestamps

    Args:
        source: Source storage backend instance
        target: Target storage backend instance
        dry_run: If True, only show what would be migrated
        force: If True, overwrite existing schedules in target

    Returns:
        Number of schedules migrated
    """
    print("\n=== Migrating Schedules ===")

    # Get all schedules as dict {schedule_id: schedule_data}
    source_schedules = source.get_all_schedules()
    target_schedules = target.get_all_schedules()

    print(f"Source has {len(source_schedules)} schedules")
    print(f"Target has {len(target_schedules)} schedules")

    migrated = 0
    skipped = 0

    for schedule_id, schedule in source_schedules.items():
        # Skip if schedule exists in target and force is not enabled
        if schedule_id in target_schedules and not force:
            print(f"  SKIP: {schedule.get('name', schedule_id)} (already exists)")
            skipped += 1
            continue

        action = "WOULD MIGRATE" if dry_run else "MIGRATING"
        print(f"  {action}: {schedule.get('name', schedule_id)}")

        if not dry_run:
            target.save_schedule(schedule_id, schedule)
        migrated += 1

    print(f"Schedules: {migrated} migrated, {skipped} skipped")
    return migrated


def migrate_history(source, target, dry_run=False, force=False):
    """
    Migrate playbook execution history from source to target.

    History entries record each playbook run including:
    - Run ID, playbook name, target, status
    - Start/finish timestamps
    - Whether it was a scheduled run
    - Log file reference

    Args:
        source: Source storage backend instance
        target: Target storage backend instance
        dry_run: If True, only show what would be migrated
        force: If True, overwrite existing entries in target

    Returns:
        Number of history entries migrated
    """
    print("\n=== Migrating History ===")

    # Get all history entries (up to 10000 to handle large histories)
    source_history = source.get_history(limit=10000)
    target_history = target.get_history(limit=10000)

    # Build set of existing run_ids in target for quick lookup
    target_run_ids = {h.get('run_id') for h in target_history}

    print(f"Source has {len(source_history)} history entries")
    print(f"Target has {len(target_history)} history entries")

    migrated = 0
    skipped = 0

    # History is ordered newest-first from get_history(), but we want
    # to insert oldest-first to maintain chronological order in target
    for entry in reversed(source_history):
        run_id = entry.get('run_id')
        if run_id in target_run_ids and not force:
            skipped += 1
            continue

        if not dry_run:
            target.add_history_entry(entry)
        migrated += 1

    if migrated > 0 or skipped > 0:
        print(f"History: {migrated} migrated, {skipped} skipped")
    else:
        print("History: nothing to migrate")

    return migrated


def migrate_inventory(source, target, dry_run=False, force=False):
    """
    Migrate managed inventory items from source to target.

    Managed inventory items are hosts added via the web interface,
    separate from the Ansible INI inventory file. Each item includes:
    - Hostname and display name
    - Group assignment
    - Host variables (ansible_user, ansible_ssh_private_key_file, etc.)
    - Created/updated timestamps

    Args:
        source: Source storage backend instance
        target: Target storage backend instance
        dry_run: If True, only show what would be migrated
        force: If True, overwrite existing items in target

    Returns:
        Number of inventory items migrated
    """
    print("\n=== Migrating Inventory ===")

    # Get all managed inventory items as list of dicts
    source_inventory = source.get_all_inventory()
    target_inventory = target.get_all_inventory()

    # Build set of existing item IDs in target for quick lookup
    target_ids = {item.get('id') for item in target_inventory}

    print(f"Source has {len(source_inventory)} inventory items")
    print(f"Target has {len(target_inventory)} inventory items")

    migrated = 0
    skipped = 0

    for item in source_inventory:
        item_id = item.get('id')
        # Skip if item exists in target and force is not enabled
        if item_id in target_ids and not force:
            print(f"  SKIP: {item.get('hostname', item_id)} (already exists)")
            skipped += 1
            continue

        action = "WOULD MIGRATE" if dry_run else "MIGRATING"
        print(f"  {action}: {item.get('hostname', item_id)}")

        if not dry_run:
            target.save_inventory_item(item_id, item)
        migrated += 1

    print(f"Inventory: {migrated} migrated, {skipped} skipped")
    return migrated


def migrate_host_facts(source, target, dry_run=False, force=False):
    """
    Migrate host facts (CMDB data) from source to target.

    This includes all collected facts, history, and metadata for each host.
    Uses import_host_facts() to preserve complete data including history.

    The import_host_facts() method bypasses the normal save_host_facts()
    diff-based history tracking, allowing raw import of the complete
    document including any existing history from the source.

    Args:
        source: Source storage backend instance
        target: Target storage backend instance
        dry_run: If True, only show what would be migrated
        force: If True, overwrite existing hosts in target

    Returns:
        Number of hosts migrated
    """
    print("\n=== Migrating Host Facts (CMDB) ===")

    # Get list of all hosts from both backends
    # Each host summary includes: host, groups, collections list, timestamps
    source_hosts = source.get_all_hosts()
    target_hosts = target.get_all_hosts()

    # Build set of existing hosts in target for quick lookup
    target_host_names = {h.get('host') for h in target_hosts}

    print(f"Source has {len(source_hosts)} hosts with collected facts")
    print(f"Target has {len(target_hosts)} hosts with collected facts")

    migrated = 0
    skipped = 0

    for host_summary in source_hosts:
        hostname = host_summary.get('host')
        collections = host_summary.get('collections', [])

        # Skip if host exists in target and force is not enabled
        if hostname in target_host_names and not force:
            print(f"  SKIP: {hostname} ({len(collections)} collections) (already exists)")
            skipped += 1
            continue

        action = "WOULD MIGRATE" if dry_run else "MIGRATING"
        print(f"  {action}: {hostname} ({len(collections)} collections)")

        if not dry_run:
            # Retrieve the complete host document including:
            # - All collections (hardware, software, etc.)
            # - Full history with diffs for each collection
            # - Groups, timestamps, and other metadata
            host_data = source.get_host_facts(hostname)
            if host_data:
                # Use import_host_facts to write the raw document
                # This preserves all data exactly as it exists in source
                target.import_host_facts(host_data)
                migrated += 1
            else:
                print(f"    WARNING: Could not retrieve data for {hostname}")
        else:
            migrated += 1

    print(f"Host Facts: {migrated} migrated, {skipped} skipped")
    return migrated


def main():
    parser = argparse.ArgumentParser(
        description='Migrate data between storage backends',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--from', dest='source', required=True,
                        choices=['flatfile', 'mongodb'],
                        help='Source backend')
    parser.add_argument('--to', dest='target', required=True,
                        choices=['flatfile', 'mongodb'],
                        help='Target backend')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be migrated without making changes')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing data in target')

    args = parser.parse_args()

    if args.source == args.target:
        print("Error: Source and target must be different")
        sys.exit(1)

    print(f"Migration: {args.source} -> {args.target}")
    if args.dry_run:
        print("(DRY RUN - no changes will be made)")
    if args.force:
        print("(FORCE - will overwrite existing data)")

    # Initialize storage backends
    try:
        source = get_storage(args.source)
        target = get_storage(args.target)
    except Exception as e:
        print(f"Error initializing storage: {e}")
        sys.exit(1)

    # Check health
    if not source.health_check():
        print(f"Error: Source backend ({args.source}) is not healthy")
        sys.exit(1)

    if not target.health_check():
        print(f"Error: Target backend ({args.target}) is not healthy")
        sys.exit(1)

    print(f"Source ({args.source}): OK")
    print(f"Target ({args.target}): OK")

    # Perform migration
    total_migrated = 0
    total_migrated += migrate_schedules(source, target, args.dry_run, args.force)
    total_migrated += migrate_history(source, target, args.dry_run, args.force)
    total_migrated += migrate_inventory(source, target, args.dry_run, args.force)
    total_migrated += migrate_host_facts(source, target, args.dry_run, args.force)

    print(f"\n=== Migration Complete ===")
    if args.dry_run:
        print(f"Would migrate {total_migrated} total items")
        print("Run without --dry-run to perform migration")
    else:
        print(f"Migrated {total_migrated} total items")


if __name__ == '__main__':
    main()
