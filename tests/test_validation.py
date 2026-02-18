"""Tests for input validation module."""
import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.validation import (
    ValidationError,
    validate_string,
    validate_email,
    validate_username,
    validate_password,
    validate_role_id,
    validate_playbook_name,
    validate_target,
    validate_permissions,
    validate_roles,
    validate_uuid,
    validate_int,
    validate_bool,
    validate_safe_path,
    validate_request,
)


class TestValidateString:
    """Tests for validate_string function."""

    def test_valid_string(self):
        """Valid string passes validation."""
        result = validate_string('hello', 'test')
        assert result == 'hello'

    def test_strips_whitespace(self):
        """Whitespace is stripped."""
        result = validate_string('  hello  ', 'test')
        assert result == 'hello'

    def test_none_when_not_required(self):
        """None returns None when not required."""
        result = validate_string(None, 'test', required=False)
        assert result is None

    def test_none_raises_when_required(self):
        """None raises error when required."""
        with pytest.raises(ValidationError) as excinfo:
            validate_string(None, 'test', required=True)
        assert 'required' in excinfo.value.message.lower()

    def test_min_length_enforced(self):
        """Minimum length is enforced."""
        with pytest.raises(ValidationError) as excinfo:
            validate_string('ab', 'test', min_len=5)
        assert 'at least 5' in excinfo.value.message

    def test_max_length_enforced(self):
        """Maximum length is enforced."""
        with pytest.raises(ValidationError) as excinfo:
            validate_string('a' * 20, 'test', max_len=10)
        assert 'at most 10' in excinfo.value.message

    def test_non_string_raises(self):
        """Non-string value raises error."""
        with pytest.raises(ValidationError) as excinfo:
            validate_string(123, 'test')
        assert 'must be a string' in excinfo.value.message


class TestValidateEmail:
    """Tests for validate_email function."""

    def test_valid_email(self):
        """Valid email passes validation."""
        result = validate_email('user@example.com')
        assert result == 'user@example.com'

    def test_invalid_email(self):
        """Invalid email raises error."""
        with pytest.raises(ValidationError):
            validate_email('not-an-email')

    def test_email_without_tld(self):
        """Email without TLD raises error."""
        with pytest.raises(ValidationError):
            validate_email('user@example')


class TestValidateUsername:
    """Tests for validate_username function."""

    def test_valid_username(self):
        """Valid username passes validation."""
        result = validate_username('admin')
        assert result == 'admin'

    def test_username_with_underscore(self):
        """Username with underscore is valid."""
        result = validate_username('admin_user')
        assert result == 'admin_user'

    def test_username_with_numbers(self):
        """Username with numbers is valid."""
        result = validate_username('user123')
        assert result == 'user123'

    def test_username_too_short(self):
        """Username too short raises error."""
        with pytest.raises(ValidationError):
            validate_username('ab')

    def test_username_starts_with_number(self):
        """Username starting with number raises error."""
        with pytest.raises(ValidationError):
            validate_username('123user')

    def test_username_with_special_chars(self):
        """Username with special characters raises error."""
        with pytest.raises(ValidationError):
            validate_username('user@name')


class TestValidatePassword:
    """Tests for validate_password function."""

    def test_valid_password(self):
        """Valid password passes validation."""
        result = validate_password('securepassword123')
        assert result == 'securepassword123'

    def test_password_too_short(self):
        """Password too short raises error."""
        with pytest.raises(ValidationError) as excinfo:
            validate_password('short')
        assert 'at least 8' in excinfo.value.message

    def test_custom_min_length(self):
        """Custom minimum length is enforced."""
        with pytest.raises(ValidationError):
            validate_password('1234567890', min_len=12)


class TestValidatePlaybookName:
    """Tests for validate_playbook_name function."""

    def test_valid_playbook(self):
        """Valid playbook name passes validation."""
        result = validate_playbook_name('setup.yml')
        assert result == 'setup.yml'

    def test_playbook_with_path(self):
        """Playbook with subdirectory is valid."""
        result = validate_playbook_name('servers/setup')
        assert result == 'servers/setup'

    def test_playbook_path_traversal(self):
        """Path traversal in playbook name raises error."""
        with pytest.raises(ValidationError):
            validate_playbook_name('../../../etc/passwd')

    def test_playbook_with_dotdot(self):
        """Playbook with .. component raises error."""
        with pytest.raises(ValidationError):
            validate_playbook_name('servers/../etc/passwd')


class TestValidatePermissions:
    """Tests for validate_permissions function."""

    def test_valid_permissions(self):
        """Valid permissions pass validation."""
        result = validate_permissions(['playbooks:view', 'logs:view'])
        assert result == ['playbooks:view', 'logs:view']

    def test_wildcard_permissions(self):
        """Wildcard permissions are valid."""
        result = validate_permissions(['*:*', 'playbooks:*'])
        assert '*:*' in result
        assert 'playbooks:*' in result

    def test_hierarchical_permission(self):
        """Hierarchical permissions are valid."""
        result = validate_permissions(['playbooks.servers:run'])
        assert result == ['playbooks.servers:run']

    def test_invalid_permission_format(self):
        """Invalid permission format raises error."""
        with pytest.raises(ValidationError):
            validate_permissions(['not-a-permission'])

    def test_empty_permission_skipped(self):
        """Empty permissions are skipped."""
        result = validate_permissions(['playbooks:view', '', 'logs:view'])
        assert result == ['playbooks:view', 'logs:view']


class TestValidateUuid:
    """Tests for validate_uuid function."""

    def test_valid_uuid(self):
        """Valid UUID passes validation."""
        result = validate_uuid('a1b2c3d4-e5f6-7890-abcd-ef1234567890')
        assert result == 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'

    def test_invalid_uuid(self):
        """Invalid UUID raises error."""
        with pytest.raises(ValidationError):
            validate_uuid('not-a-uuid')

    def test_uuid_wrong_length(self):
        """UUID with wrong length raises error."""
        with pytest.raises(ValidationError):
            validate_uuid('a1b2c3d4')


class TestValidateInt:
    """Tests for validate_int function."""

    def test_valid_int(self):
        """Valid integer passes validation."""
        result = validate_int(42, 'test')
        assert result == 42

    def test_string_int(self):
        """String integer is converted."""
        result = validate_int('42', 'test')
        assert result == 42

    def test_min_value_enforced(self):
        """Minimum value is enforced."""
        with pytest.raises(ValidationError):
            validate_int(5, 'test', min_val=10)

    def test_max_value_enforced(self):
        """Maximum value is enforced."""
        with pytest.raises(ValidationError):
            validate_int(100, 'test', max_val=50)

    def test_default_value(self):
        """Default value is returned for None."""
        result = validate_int(None, 'test', default=10)
        assert result == 10


class TestValidateBool:
    """Tests for validate_bool function."""

    def test_true_bool(self):
        """True boolean passes validation."""
        result = validate_bool(True, 'test')
        assert result is True

    def test_false_bool(self):
        """False boolean passes validation."""
        result = validate_bool(False, 'test')
        assert result is False

    def test_true_string(self):
        """'true' string is converted."""
        result = validate_bool('true', 'test')
        assert result is True

    def test_false_string(self):
        """'false' string is converted."""
        result = validate_bool('false', 'test')
        assert result is False

    def test_yes_string(self):
        """'yes' string is converted."""
        result = validate_bool('yes', 'test')
        assert result is True

    def test_no_string(self):
        """'no' string is converted."""
        result = validate_bool('no', 'test')
        assert result is False


class TestValidateSafePath:
    """Tests for validate_safe_path function."""

    def test_valid_path(self):
        """Valid path passes validation."""
        result = validate_safe_path('playbooks/test.yml', 'path')
        assert result == 'playbooks/test.yml'

    def test_path_traversal(self):
        """Path traversal raises error."""
        with pytest.raises(ValidationError):
            validate_safe_path('../../../etc/passwd', 'path')

    def test_null_byte(self):
        """Null byte in path raises error."""
        with pytest.raises(ValidationError):
            validate_safe_path('test\x00.yml', 'path')

    def test_path_with_base_dir(self):
        """Path within base_dir passes validation."""
        result = validate_safe_path('test.yml', 'path', base_dir='/app/playbooks')
        assert result == 'test.yml'


class TestValidateRequest:
    """Tests for validate_request function."""

    def test_user_create_schema(self):
        """User create schema validates correctly."""
        data = {
            'username': 'newuser',
            'password': 'securepassword123',
            'email': 'user@example.com',
            'roles': ['operator']
        }
        result = validate_request(data, 'user_create')
        assert result['username'] == 'newuser'
        assert result['password'] == 'securepassword123'

    def test_user_create_missing_required(self):
        """User create with missing required field raises error."""
        data = {'email': 'user@example.com'}
        with pytest.raises(ValidationError) as excinfo:
            validate_request(data, 'user_create')
        assert 'username' in excinfo.value.message or 'required' in excinfo.value.message.lower()

    def test_role_create_schema(self):
        """Role create schema validates correctly."""
        data = {
            'id': 'custom_role',
            'name': 'Custom Role',
            'description': 'A custom role',
            'permissions': ['playbooks:view']
        }
        result = validate_request(data, 'role_create')
        assert result['id'] == 'custom_role'
        assert result['name'] == 'Custom Role'

    def test_unknown_schema(self):
        """Unknown schema raises ValueError."""
        with pytest.raises(ValueError):
            validate_request({}, 'unknown_schema')
