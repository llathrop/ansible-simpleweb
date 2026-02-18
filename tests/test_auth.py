"""
Tests for web/auth.py - Authentication module

Tests:
- Password hashing and verification
- Session management
- API token generation and validation
- Login attempt tracking and account lockout
"""

import pytest
import time
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from web.auth import (
    hash_password,
    verify_password,
    SessionManager,
    APITokenManager,
    LoginAttemptTracker,
    AuthenticationError,
    AccountLockedError
)


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password_returns_string(self):
        """hash_password should return a bcrypt hash string."""
        password = "test_password_123"
        hashed = hash_password(password)
        assert isinstance(hashed, str)
        assert hashed.startswith('$2b$')  # bcrypt prefix

    def test_hash_password_unique_hashes(self):
        """Same password should produce different hashes (due to salt)."""
        password = "same_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """verify_password should return True for correct password."""
        password = "correct_password"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """verify_password should return False for incorrect password."""
        password = "correct_password"
        hashed = hash_password(password)
        assert verify_password("wrong_password", hashed) is False

    def test_verify_password_empty(self):
        """verify_password should handle empty strings."""
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("non-empty", hashed) is False

    def test_verify_password_invalid_hash(self):
        """verify_password should return False for invalid hash."""
        assert verify_password("password", "invalid_hash") is False
        assert verify_password("password", "") is False

    def test_hash_password_special_characters(self):
        """Password with special characters should hash correctly."""
        password = "p@$$w0rd!@#$%^&*()"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True


class TestSessionManager:
    """Tests for SessionManager class."""

    def test_create_session(self):
        """create_session should return a session ID."""
        manager = SessionManager()
        user = {'id': 'user123', 'username': 'testuser', 'roles': ['admin']}
        session_id = manager.create_session(user)
        assert isinstance(session_id, str)
        assert len(session_id) == 36  # UUID format

    def test_validate_session_valid(self):
        """validate_session should return session data for valid session."""
        manager = SessionManager()
        user = {'id': 'user123', 'username': 'testuser', 'roles': ['admin']}
        session_id = manager.create_session(user)

        session = manager.validate_session(session_id)
        assert session is not None
        assert session['user_id'] == 'user123'
        assert session['username'] == 'testuser'

    def test_validate_session_invalid(self):
        """validate_session should return None for invalid session."""
        manager = SessionManager()
        assert manager.validate_session('invalid-session-id') is None
        assert manager.validate_session(None) is None
        assert manager.validate_session('') is None

    def test_validate_session_expired(self):
        """validate_session should return None for expired session."""
        manager = SessionManager(timeout_seconds=1)
        user = {'id': 'user123', 'username': 'testuser'}
        session_id = manager.create_session(user)

        # Wait for expiry
        time.sleep(1.5)

        assert manager.validate_session(session_id) is None

    def test_destroy_session(self):
        """destroy_session should invalidate the session."""
        manager = SessionManager()
        user = {'id': 'user123', 'username': 'testuser'}
        session_id = manager.create_session(user)

        assert manager.validate_session(session_id) is not None
        result = manager.destroy_session(session_id)
        assert result is True
        assert manager.validate_session(session_id) is None

    def test_destroy_session_invalid(self):
        """destroy_session should return False for invalid session."""
        manager = SessionManager()
        assert manager.destroy_session('invalid-id') is False

    def test_cleanup_expired_sessions(self):
        """cleanup_expired_sessions should remove expired sessions."""
        manager = SessionManager(timeout_seconds=1)
        user = {'id': 'user123', 'username': 'testuser'}

        # Create sessions
        session1 = manager.create_session(user)
        time.sleep(1.5)
        session2 = manager.create_session(user)  # Still valid

        manager.cleanup_expired_sessions()

        assert manager.validate_session(session1) is None
        assert manager.validate_session(session2) is not None


class TestAPITokenManager:
    """Tests for APITokenManager class."""

    def test_generate_token(self):
        """generate_token should return a random hex string."""
        token1 = APITokenManager.generate_token()
        token2 = APITokenManager.generate_token()

        assert isinstance(token1, str)
        assert len(token1) == 64  # 32 bytes = 64 hex chars
        assert token1 != token2

    def test_hash_token(self):
        """hash_token should return a SHA-256 hash."""
        token = "test_token_123"
        hashed = APITokenManager.hash_token(token)

        assert isinstance(hashed, str)
        assert len(hashed) == 64  # SHA-256 = 64 hex chars
        # Same input should produce same hash
        assert APITokenManager.hash_token(token) == hashed

    def test_create_token_entry(self):
        """create_token_entry should return token and entry dict."""
        raw_token, entry = APITokenManager.create_token_entry(
            user_id='user123',
            name='Test Token',
            expiry_days=30
        )

        assert isinstance(raw_token, str)
        assert len(raw_token) == 64

        assert entry['user_id'] == 'user123'
        assert entry['name'] == 'Test Token'
        assert 'id' in entry
        assert 'token_hash' in entry
        assert 'created_at' in entry
        assert 'expires_at' in entry
        assert entry['last_used'] is None

    def test_create_token_entry_no_expiry(self):
        """create_token_entry with expiry_days=None should have no expiry."""
        _, entry = APITokenManager.create_token_entry(
            user_id='user123',
            name='No Expiry Token',
            expiry_days=None
        )

        assert entry['expires_at'] is None


class TestLoginAttemptTracker:
    """Tests for LoginAttemptTracker class."""

    def test_record_failure_tracking(self):
        """record_failure should track failed attempts."""
        tracker = LoginAttemptTracker(max_attempts=5, lockout_minutes=1)

        tracker.record_failure('testuser')
        assert tracker.get_remaining_attempts('testuser') == 4

        tracker.record_failure('testuser')
        assert tracker.get_remaining_attempts('testuser') == 3

    def test_lockout_after_max_attempts(self):
        """Account should lock after max failed attempts."""
        tracker = LoginAttemptTracker(max_attempts=3, lockout_minutes=1)

        for _ in range(3):
            tracker.record_failure('testuser')

        assert tracker.is_locked('testuser') is True
        assert tracker.get_remaining_attempts('testuser') == 0

    def test_lockout_remaining_time(self):
        """get_lockout_remaining should return remaining seconds."""
        tracker = LoginAttemptTracker(max_attempts=3, lockout_minutes=1)

        for _ in range(3):
            tracker.record_failure('testuser')

        remaining = tracker.get_lockout_remaining('testuser')
        assert remaining is not None
        assert 0 < remaining <= 60

    def test_record_success_clears_attempts(self):
        """record_success should clear failed attempts."""
        tracker = LoginAttemptTracker(max_attempts=5, lockout_minutes=1)

        tracker.record_failure('testuser')
        tracker.record_failure('testuser')
        assert tracker.get_remaining_attempts('testuser') == 3

        tracker.record_success('testuser')
        assert tracker.get_remaining_attempts('testuser') == 5

    def test_record_success_clears_lockout(self):
        """record_success should clear lockout."""
        tracker = LoginAttemptTracker(max_attempts=3, lockout_minutes=1)

        for _ in range(3):
            tracker.record_failure('testuser')
        assert tracker.is_locked('testuser') is True

        tracker.record_success('testuser')
        assert tracker.is_locked('testuser') is False

    def test_separate_users(self):
        """Different users should have separate tracking."""
        tracker = LoginAttemptTracker(max_attempts=3, lockout_minutes=1)

        tracker.record_failure('user1')
        tracker.record_failure('user1')
        tracker.record_failure('user1')

        assert tracker.is_locked('user1') is True
        assert tracker.is_locked('user2') is False
        assert tracker.get_remaining_attempts('user2') == 3

    def test_not_locked_initially(self):
        """New user should not be locked."""
        tracker = LoginAttemptTracker()
        assert tracker.is_locked('newuser') is False
        assert tracker.get_lockout_remaining('newuser') is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
