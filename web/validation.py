"""
Input Validation Module for Ansible SimpleWeb

Provides validation functions for API inputs to prevent injection attacks,
data corruption, and other security issues.
"""

import re
from typing import Dict, List, Optional, Tuple, Any


class ValidationError(Exception):
    """Raised when input validation fails."""

    def __init__(self, message: str, field: str = None):
        self.message = message
        self.field = field
        super().__init__(message)


# Validation patterns
PATTERNS = {
    # Username: alphanumeric with underscores, 3-50 chars
    'username': re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{2,49}$'),

    # Email: basic email format validation
    'email': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),

    # Role ID: alphanumeric with underscores, 2-50 chars
    'role_id': re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{1,49}$'),

    # Playbook name: alphanumeric with hyphens, underscores, slashes, 1-100 chars
    'playbook_name': re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-/]{0,99}(\.yml)?$'),

    # Target/hostname: alphanumeric with hyphens, underscores, dots, commas
    'target': re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-.,\s]{0,199}$'),

    # Schedule name: printable characters, 1-200 chars
    'schedule_name': re.compile(r'^[\w\s\-_.,:;()[\]@#$%&*+=<>?/\\]{1,200}$'),

    # Permission format: resource:action or resource.sub:action
    'permission': re.compile(r'^[\*a-zA-Z][a-zA-Z0-9_\.]*:[\*a-zA-Z][a-zA-Z0-9_]*$'),

    # UUID format
    'uuid': re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE),

    # Safe filename: no path traversal
    'safe_filename': re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-\.]{0,99}$'),
}


def validate_string(value: Any, field_name: str, min_len: int = 1, max_len: int = 1000,
                    pattern: str = None, required: bool = True, allow_none: bool = False) -> Optional[str]:
    """
    Validate a string value.

    Args:
        value: Value to validate
        field_name: Name of the field (for error messages)
        min_len: Minimum length
        max_len: Maximum length
        pattern: Regex pattern name from PATTERNS dict
        required: Whether the field is required
        allow_none: Whether None is allowed

    Returns:
        Validated string or None

    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        if allow_none:
            return None
        if required:
            raise ValidationError(f'{field_name} is required', field_name)
        return None

    if not isinstance(value, str):
        raise ValidationError(f'{field_name} must be a string', field_name)

    value = value.strip()

    if len(value) == 0:
        if required:
            raise ValidationError(f'{field_name} is required', field_name)
        return None

    if len(value) < min_len:
        raise ValidationError(f'{field_name} must be at least {min_len} characters', field_name)

    if len(value) > max_len:
        raise ValidationError(f'{field_name} must be at most {max_len} characters', field_name)

    if pattern and pattern in PATTERNS:
        if not PATTERNS[pattern].match(value):
            raise ValidationError(f'{field_name} has an invalid format', field_name)

    return value


def validate_email(value: Any, field_name: str = 'email', required: bool = True) -> Optional[str]:
    """Validate an email address."""
    email = validate_string(value, field_name, min_len=5, max_len=255, required=required)
    if email and not PATTERNS['email'].match(email):
        raise ValidationError(f'{field_name} is not a valid email address', field_name)
    return email


def validate_username(value: Any, field_name: str = 'username') -> str:
    """Validate a username."""
    username = validate_string(value, field_name, min_len=3, max_len=50, pattern='username')
    return username


def validate_password(value: Any, field_name: str = 'password', min_len: int = 8) -> str:
    """
    Validate a password.

    Requirements:
    - At least min_len characters
    - At most 128 characters
    """
    password = validate_string(value, field_name, min_len=min_len, max_len=128)

    if len(password) < min_len:
        raise ValidationError(f'{field_name} must be at least {min_len} characters', field_name)

    return password


def validate_role_id(value: Any, field_name: str = 'id') -> str:
    """Validate a role ID."""
    return validate_string(value, field_name, min_len=2, max_len=50, pattern='role_id')


def validate_playbook_name(value: Any, field_name: str = 'playbook') -> str:
    """Validate a playbook name."""
    playbook = validate_string(value, field_name, min_len=1, max_len=100)
    if not PATTERNS['playbook_name'].match(playbook):
        raise ValidationError(f'{field_name} contains invalid characters', field_name)
    # Check for path traversal
    if '..' in playbook:
        raise ValidationError(f'{field_name} contains invalid path components', field_name)
    return playbook


def validate_target(value: Any, field_name: str = 'target', required: bool = True) -> Optional[str]:
    """Validate a target/hostname."""
    target = validate_string(value, field_name, min_len=1, max_len=200, required=required)
    if target and not PATTERNS['target'].match(target):
        raise ValidationError(f'{field_name} contains invalid characters', field_name)
    return target


def validate_permissions(permissions: Any, field_name: str = 'permissions') -> List[str]:
    """Validate a list of permissions."""
    if permissions is None:
        return []

    if not isinstance(permissions, list):
        raise ValidationError(f'{field_name} must be a list', field_name)

    validated = []
    for i, perm in enumerate(permissions):
        if not isinstance(perm, str):
            raise ValidationError(f'{field_name}[{i}] must be a string', field_name)

        perm = perm.strip()
        if not perm:
            continue

        if not PATTERNS['permission'].match(perm):
            raise ValidationError(f'{field_name}[{i}] has invalid format: {perm}', field_name)

        validated.append(perm)

    return validated


def validate_roles(roles: Any, field_name: str = 'roles') -> List[str]:
    """Validate a list of role IDs."""
    if roles is None:
        return []

    if not isinstance(roles, list):
        raise ValidationError(f'{field_name} must be a list', field_name)

    validated = []
    for i, role in enumerate(roles):
        if not isinstance(role, str):
            raise ValidationError(f'{field_name}[{i}] must be a string', field_name)

        role = role.strip()
        if not role:
            continue

        if not PATTERNS['role_id'].match(role):
            raise ValidationError(f'{field_name}[{i}] has invalid format: {role}', field_name)

        validated.append(role)

    return validated


def validate_uuid(value: Any, field_name: str = 'id') -> str:
    """Validate a UUID."""
    uuid_str = validate_string(value, field_name, min_len=36, max_len=36)
    if not PATTERNS['uuid'].match(uuid_str):
        raise ValidationError(f'{field_name} is not a valid UUID', field_name)
    return uuid_str


def validate_int(value: Any, field_name: str, min_val: int = None, max_val: int = None,
                 default: int = None) -> Optional[int]:
    """Validate an integer value."""
    if value is None:
        return default

    try:
        int_val = int(value)
    except (ValueError, TypeError):
        raise ValidationError(f'{field_name} must be an integer', field_name)

    if min_val is not None and int_val < min_val:
        raise ValidationError(f'{field_name} must be at least {min_val}', field_name)

    if max_val is not None and int_val > max_val:
        raise ValidationError(f'{field_name} must be at most {max_val}', field_name)

    return int_val


def validate_bool(value: Any, field_name: str, default: bool = None) -> Optional[bool]:
    """Validate a boolean value."""
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        if value.lower() in ('true', '1', 'yes', 'on'):
            return True
        if value.lower() in ('false', '0', 'no', 'off'):
            return False

    raise ValidationError(f'{field_name} must be a boolean', field_name)


def validate_dict(value: Any, field_name: str, required: bool = False) -> Optional[Dict]:
    """Validate a dictionary value."""
    if value is None:
        if required:
            raise ValidationError(f'{field_name} is required', field_name)
        return None

    if not isinstance(value, dict):
        raise ValidationError(f'{field_name} must be an object', field_name)

    return value


def validate_safe_path(path: str, field_name: str = 'path', base_dir: str = None) -> str:
    """
    Validate a file path is safe (no path traversal).

    Args:
        path: Path to validate
        field_name: Name of the field
        base_dir: Base directory that path must be within

    Returns:
        Validated path

    Raises:
        ValidationError: If path is unsafe
    """
    import os

    if not path:
        raise ValidationError(f'{field_name} is required', field_name)

    # Check for null bytes
    if '\x00' in path:
        raise ValidationError(f'{field_name} contains null bytes', field_name)

    # Check for path traversal
    if '..' in path.split(os.sep):
        raise ValidationError(f'{field_name} contains path traversal', field_name)

    # Normalize the path
    normalized = os.path.normpath(path)

    # If base_dir is specified, ensure path is within it
    if base_dir:
        base_abs = os.path.abspath(base_dir)
        path_abs = os.path.abspath(os.path.join(base_dir, normalized))

        if not path_abs.startswith(base_abs + os.sep) and path_abs != base_abs:
            raise ValidationError(f'{field_name} must be within {base_dir}', field_name)

    return normalized


# Validation schemas for common API endpoints
SCHEMAS = {
    'user_create': {
        'username': {'validator': validate_username, 'required': True},
        'password': {'validator': validate_password, 'required': True},
        'email': {'validator': validate_email, 'required': False},
        'roles': {'validator': validate_roles, 'required': False},
        'enabled': {'validator': lambda v, f: validate_bool(v, f, default=True), 'required': False},
    },
    'user_update': {
        'email': {'validator': validate_email, 'required': False},
        'roles': {'validator': validate_roles, 'required': False},
        'enabled': {'validator': lambda v, f: validate_bool(v, f), 'required': False},
    },
    'role_create': {
        'id': {'validator': validate_role_id, 'required': True},
        'name': {'validator': lambda v, f: validate_string(v, f, min_len=1, max_len=100), 'required': True},
        'description': {'validator': lambda v, f: validate_string(v, f, max_len=500, required=False), 'required': False},
        'permissions': {'validator': validate_permissions, 'required': False},
        'inherits': {'validator': validate_roles, 'required': False},
    },
    'job_submit': {
        'playbook': {'validator': validate_playbook_name, 'required': True},
        'target': {'validator': validate_target, 'required': False},
        'priority': {'validator': lambda v, f: validate_int(v, f, min_val=1, max_val=100, default=50), 'required': False},
        'job_type': {'validator': lambda v, f: validate_string(v, f, pattern=None, required=False), 'required': False},
    },
}


def validate_request(data: Dict, schema_name: str) -> Dict:
    """
    Validate request data against a schema.

    Args:
        data: Request data dictionary
        schema_name: Name of schema to validate against

    Returns:
        Validated data dictionary

    Raises:
        ValidationError: If validation fails
    """
    if schema_name not in SCHEMAS:
        raise ValueError(f'Unknown schema: {schema_name}')

    schema = SCHEMAS[schema_name]
    validated = {}

    for field_name, field_spec in schema.items():
        validator = field_spec['validator']
        required = field_spec.get('required', True)

        value = data.get(field_name)

        if value is None and not required:
            continue

        try:
            validated_value = validator(value, field_name)
            if validated_value is not None:
                validated[field_name] = validated_value
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f'{field_name}: {str(e)}', field_name)

    return validated
