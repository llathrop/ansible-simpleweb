#!/usr/bin/env python3
"""
Create Admin User Script

Creates an admin user for Ansible SimpleWeb.
Can be run from the command line or imported as a module.

Usage:
    python scripts/create_admin.py --username admin --password secret123
    python scripts/create_admin.py -u admin -p secret123 --email admin@example.com

Environment variables:
    STORAGE_BACKEND: Storage backend type (flatfile or mongodb)
    MONGODB_URI: MongoDB connection URI (if using mongodb backend)
    CONFIG_DIR: Directory for flatfile storage (default: /app/config)
"""

import argparse
import getpass
import os
import sys
import uuid
from datetime import datetime, timezone

# Add parent directories to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, os.path.join(project_root, 'web'))


def get_storage_backend():
    """Initialize and return the storage backend."""
    from storage import get_storage_backend as _get_storage_backend
    return _get_storage_backend()


def create_admin_user(storage, username, password, email='', full_name='Administrator'):
    """
    Create an admin user.

    Args:
        storage: Storage backend instance
        username: Admin username
        password: Admin password
        email: Admin email (optional)
        full_name: Admin full name (optional)

    Returns:
        User dict if created successfully, None otherwise
    """
    from auth import hash_password

    # Check if user already exists
    existing = storage.get_user(username)
    if existing:
        print(f"Error: User '{username}' already exists", file=sys.stderr)
        return None

    # Create admin user
    user = {
        'id': str(uuid.uuid4()),
        'username': username,
        'password_hash': hash_password(password),
        'email': email,
        'full_name': full_name,
        'roles': ['admin'],
        'enabled': True,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'last_login': None
    }

    if storage.save_user(username, user):
        print(f"Admin user '{username}' created successfully")
        return user
    else:
        print(f"Error: Failed to create admin user", file=sys.stderr)
        return None


def list_users(storage):
    """List all existing users."""
    users = storage.get_all_users()
    if not users:
        print("No users found")
        return

    print(f"{'Username':<20} {'Email':<30} {'Roles':<30} {'Enabled'}")
    print("-" * 90)
    for user in users:
        roles = ', '.join(user.get('roles', []))
        enabled = 'Yes' if user.get('enabled', True) else 'No'
        print(f"{user['username']:<20} {user.get('email', '-'):<30} {roles:<30} {enabled}")


def delete_user(storage, username):
    """Delete a user."""
    if storage.delete_user(username):
        print(f"User '{username}' deleted successfully")
        return True
    else:
        print(f"Error: User '{username}' not found or could not be deleted", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Create and manage admin users for Ansible SimpleWeb'
    )
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Create command
    create_parser = subparsers.add_parser('create', help='Create a new admin user')
    create_parser.add_argument('-u', '--username', required=True, help='Admin username')
    create_parser.add_argument('-p', '--password', help='Admin password (will prompt if not provided)')
    create_parser.add_argument('-e', '--email', default='', help='Admin email')
    create_parser.add_argument('-n', '--name', default='Administrator', help='Admin full name')

    # List command
    subparsers.add_parser('list', help='List all users')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a user')
    delete_parser.add_argument('-u', '--username', required=True, help='Username to delete')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize storage
    try:
        storage = get_storage_backend()
        print(f"Storage backend: {storage.get_backend_type()}")
    except Exception as e:
        print(f"Error initializing storage: {e}", file=sys.stderr)
        sys.exit(1)

    if args.command == 'create':
        password = args.password
        if not password:
            password = getpass.getpass('Enter admin password: ')
            confirm = getpass.getpass('Confirm password: ')
            if password != confirm:
                print("Error: Passwords do not match", file=sys.stderr)
                sys.exit(1)

        if len(password) < 8:
            print("Warning: Password is less than 8 characters", file=sys.stderr)

        user = create_admin_user(
            storage,
            args.username,
            password,
            email=args.email,
            full_name=args.name
        )
        sys.exit(0 if user else 1)

    elif args.command == 'list':
        list_users(storage)

    elif args.command == 'delete':
        confirm = input(f"Are you sure you want to delete user '{args.username}'? (yes/no): ")
        if confirm.lower() == 'yes':
            success = delete_user(storage, args.username)
            sys.exit(0 if success else 1)
        else:
            print("Cancelled")


if __name__ == '__main__':
    main()
