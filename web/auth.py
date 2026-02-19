"""
Authentication Module for Ansible SimpleWeb

Provides user authentication functionality including:
- Password hashing and verification (bcrypt)
- Session management
- API token generation and validation
- Account lockout after failed attempts
"""

import bcrypt
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple
import hashlib


class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass


class AccountLockedError(AuthenticationError):
    """Raised when account is locked due to failed attempts"""
    pass


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt with cost factor 12.

    Args:
        password: Plain text password to hash

    Returns:
        Bcrypt hash string
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against its bcrypt hash.

    Args:
        password: Plain text password to verify
        password_hash: Bcrypt hash to check against

    Returns:
        True if password matches hash, False otherwise
    """
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False


class SessionManager:
    """
    Manages user sessions with in-memory storage.

    For production, consider using Redis for persistence and scalability.
    """

    def __init__(self, timeout_seconds: int = 3600):
        """
        Initialize session manager.

        Args:
            timeout_seconds: Session timeout in seconds (default: 1 hour)
        """
        self.sessions = {}  # session_id -> {user_id, username, created, last_active}
        self.timeout_seconds = timeout_seconds

    def create_session(self, user: Dict) -> str:
        """
        Create a new session for a user.

        Args:
            user: User dict with 'id', 'username', etc.

        Returns:
            Session ID (UUID)
        """
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        self.sessions[session_id] = {
            'user_id': user['id'],
            'username': user['username'],
            'email': user.get('email', ''),
            'roles': user.get('roles', []),
            'created': now,
            'last_active': now
        }

        return session_id

    def validate_session(self, session_id: str) -> Optional[Dict]:
        """
        Validate a session and return user info if valid.

        Args:
            session_id: Session ID to validate

        Returns:
            User session dict if valid, None if invalid/expired
        """
        if not session_id or session_id not in self.sessions:
            return None

        session = self.sessions[session_id]
        now = datetime.now(timezone.utc)

        # Check if session has expired
        elapsed = (now - session['last_active']).total_seconds()
        if elapsed > self.timeout_seconds:
            # Session expired, remove it
            del self.sessions[session_id]
            return None

        # Update last active time
        session['last_active'] = now

        return session

    def destroy_session(self, session_id: str) -> bool:
        """
        Destroy a session (logout).

        Args:
            session_id: Session ID to destroy

        Returns:
            True if session was destroyed, False if not found
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False

    def cleanup_expired_sessions(self):
        """Remove all expired sessions."""
        now = datetime.now(timezone.utc)
        expired = [
            sid for sid, session in self.sessions.items()
            if (now - session['last_active']).total_seconds() > self.timeout_seconds
        ]
        for sid in expired:
            del self.sessions[sid]


class APITokenManager:
    """
    Manages API tokens for programmatic access.

    Tokens are stored in the storage backend for persistence.
    """

    @staticmethod
    def generate_token() -> str:
        """
        Generate a secure random API token.

        Returns:
            Token string (hex)
        """
        return secrets.token_hex(32)  # 64 characters hex

    @staticmethod
    def hash_token(token: str) -> str:
        """
        Hash a token for secure storage.

        Args:
            token: Raw token string

        Returns:
            SHA-256 hash of token
        """
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    @staticmethod
    def create_token_entry(user_id: str, name: str, expiry_days: Optional[int] = 365) -> Tuple[str, Dict]:
        """
        Create a new API token entry.

        Args:
            user_id: User ID the token belongs to
            name: Descriptive name for the token
            expiry_days: Days until token expires (None for no expiry)

        Returns:
            Tuple of (raw_token, token_entry_dict)

        Note:
            Raw token must be shown to user immediately; it cannot be recovered later.
        """
        token = APITokenManager.generate_token()
        token_hash = APITokenManager.hash_token(token)

        now = datetime.now(timezone.utc)
        expiry = now + timedelta(days=expiry_days) if expiry_days else None

        token_entry = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'name': name,
            'token_hash': token_hash,
            'created_at': now.isoformat(),
            'expires_at': expiry.isoformat() if expiry else None,
            'last_used': None
        }

        return token, token_entry


class LoginAttemptTracker:
    """
    Tracks failed login attempts and implements account lockout.

    In production, this should use a persistent store like Redis.
    """

    def __init__(self, max_attempts: int = 5, lockout_minutes: int = 15):
        """
        Initialize login attempt tracker.

        Args:
            max_attempts: Maximum failed attempts before lockout
            lockout_minutes: Duration of lockout in minutes
        """
        self.attempts = {}  # username -> [timestamp, timestamp, ...]
        self.lockouts = {}  # username -> lockout_until_timestamp
        self.max_attempts = max_attempts
        self.lockout_duration = timedelta(minutes=lockout_minutes)

    def is_locked(self, username: str) -> bool:
        """
        Check if an account is currently locked.

        Args:
            username: Username to check

        Returns:
            True if account is locked, False otherwise
        """
        if username not in self.lockouts:
            return False

        lockout_until = self.lockouts[username]
        now = datetime.now(timezone.utc)

        if now < lockout_until:
            return True

        # Lockout expired, clean up
        del self.lockouts[username]
        if username in self.attempts:
            del self.attempts[username]

        return False

    def record_failure(self, username: str):
        """
        Record a failed login attempt.

        Args:
            username: Username that failed login
        """
        now = datetime.now(timezone.utc)

        if username not in self.attempts:
            self.attempts[username] = []

        # Add current attempt
        self.attempts[username].append(now)

        # Remove attempts older than lockout duration
        cutoff = now - self.lockout_duration
        self.attempts[username] = [
            attempt for attempt in self.attempts[username]
            if attempt > cutoff
        ]

        # Check if we should lock the account
        if len(self.attempts[username]) >= self.max_attempts:
            self.lockouts[username] = now + self.lockout_duration

    def record_success(self, username: str):
        """
        Record a successful login (clears failure count).

        Args:
            username: Username that successfully logged in
        """
        if username in self.attempts:
            del self.attempts[username]
        if username in self.lockouts:
            del self.lockouts[username]

    def get_remaining_attempts(self, username: str) -> int:
        """
        Get number of remaining login attempts before lockout.

        Args:
            username: Username to check

        Returns:
            Number of attempts remaining (0 if locked)
        """
        if self.is_locked(username):
            return 0

        if username not in self.attempts:
            return self.max_attempts

        # Clean old attempts first
        now = datetime.now(timezone.utc)
        cutoff = now - self.lockout_duration
        self.attempts[username] = [
            attempt for attempt in self.attempts[username]
            if attempt > cutoff
        ]

        return max(0, self.max_attempts - len(self.attempts[username]))

    def get_lockout_remaining(self, username: str) -> Optional[int]:
        """
        Get remaining lockout time in seconds.

        Args:
            username: Username to check

        Returns:
            Seconds remaining in lockout, or None if not locked
        """
        if username not in self.lockouts:
            return None

        lockout_until = self.lockouts[username]
        now = datetime.now(timezone.utc)

        if now >= lockout_until:
            return None

        return int((lockout_until - now).total_seconds())


# Global instances (can be replaced with dependency injection or app context)
session_manager = SessionManager()
login_tracker = LoginAttemptTracker()


def authenticate_user(storage_backend, username: str, password: str) -> Dict:
    """
    Authenticate a user with username and password.

    Args:
        storage_backend: Storage backend instance
        username: Username to authenticate
        password: Password to verify

    Returns:
        User dict if authentication successful

    Raises:
        AccountLockedError: If account is locked
        AuthenticationError: If authentication fails
    """
    # Check if account is locked
    if login_tracker.is_locked(username):
        lockout_remaining = login_tracker.get_lockout_remaining(username)
        raise AccountLockedError(
            f"Account locked. Try again in {lockout_remaining} seconds."
        )

    # Get user from storage
    user = storage_backend.get_user(username)
    if not user:
        login_tracker.record_failure(username)
        raise AuthenticationError("Invalid username or password")

    # Check if user is enabled
    if not user.get('enabled', True):
        raise AuthenticationError("Account is disabled")

    # Verify password
    if not verify_password(password, user['password_hash']):
        login_tracker.record_failure(username)
        remaining = login_tracker.get_remaining_attempts(username)
        if remaining > 0:
            raise AuthenticationError(
                f"Invalid username or password ({remaining} attempts remaining)"
            )
        else:
            raise AccountLockedError("Account locked due to too many failed attempts")

    # Authentication successful
    login_tracker.record_success(username)

    # Update last login time
    user['last_login'] = datetime.now(timezone.utc).isoformat()
    storage_backend.save_user(user['username'], user)

    return user


def authenticate_api_token(storage_backend, token: str) -> Optional[Dict]:
    """
    Authenticate using an API token.

    Args:
        storage_backend: Storage backend instance
        token: API token to validate

    Returns:
        User dict if token is valid, None otherwise
    """
    token_hash = APITokenManager.hash_token(token)

    # Get token entry from storage
    token_entry = storage_backend.get_api_token_by_hash(token_hash)
    if not token_entry:
        return None

    # Check if token has expired
    if token_entry.get('expires_at'):
        expiry = datetime.fromisoformat(token_entry['expires_at'])
        if datetime.now(timezone.utc) > expiry:
            return None

    # Get user
    user = storage_backend.get_user_by_id(token_entry['user_id'])
    if not user or not user.get('enabled', True):
        return None

    # Update last used time
    token_entry['last_used'] = datetime.now(timezone.utc).isoformat()
    storage_backend.update_api_token(token_entry['id'], token_entry)

    return user
