#!/usr/bin/env python3
"""
Storage Migration Script

Migrates data between storage backends (flatfile <-> MongoDB).
Can be run from inside the container or with appropriate environment variables.

Usage:
    # From inside container:
    python3 /app/web/migrate_storage.py --from flatfile --to mongodb
    python3 /app/web/migrate_storage.py --from mongodb --to flatfile

    # Via docker exec:
    docker exec ansible-simpleweb python3 /app/web/migrate_storage.py --from flatfile --to mongodb

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
    """Migrate schedules from source to target."""
    print("\n=== Migrating Schedules ===")

    source_schedules = source.get_all_schedules()
    target_schedules = target.get_all_schedules()

    print(f"Source has {len(source_schedules)} schedules")
    print(f"Target has {len(target_schedules)} schedules")

    migrated = 0
    skipped = 0

    for schedule_id, schedule in source_schedules.items():
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
    """Migrate execution history from source to target."""
    print("\n=== Migrating History ===")

    # Get all history (up to 10000 entries)
    source_history = source.get_history(limit=10000)
    target_history = target.get_history(limit=10000)

    # Build set of existing run_ids in target
    target_run_ids = {h.get('run_id') for h in target_history}

    print(f"Source has {len(source_history)} history entries")
    print(f"Target has {len(target_history)} history entries")

    migrated = 0
    skipped = 0

    # History is ordered newest-first, but we want to insert oldest-first
    # to maintain chronological order in target
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
    """Migrate inventory items from source to target."""
    print("\n=== Migrating Inventory ===")

    source_inventory = source.get_all_inventory()
    target_inventory = target.get_all_inventory()

    # Build set of existing item IDs in target
    target_ids = {item.get('id') for item in target_inventory}

    print(f"Source has {len(source_inventory)} inventory items")
    print(f"Target has {len(target_inventory)} inventory items")

    migrated = 0
    skipped = 0

    for item in source_inventory:
        item_id = item.get('id')
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

    print(f"\n=== Migration Complete ===")
    if args.dry_run:
        print(f"Would migrate {total_migrated} total items")
        print("Run without --dry-run to perform migration")
    else:
        print(f"Migrated {total_migrated} total items")


if __name__ == '__main__':
    main()
