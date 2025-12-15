"""
Worker Configuration

Handles configuration loading from environment variables and config files.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class WorkerConfig:
    """Worker service configuration."""

    # Required settings
    worker_name: str
    server_url: str
    registration_token: str

    # Worker capabilities
    tags: List[str] = field(default_factory=list)

    # Timing settings (in seconds)
    checkin_interval: int = 600  # 10 minutes
    sync_interval: int = 300  # 5 minutes
    poll_interval: int = 5  # Job polling

    # Execution settings
    max_concurrent_jobs: int = 2

    # Paths
    content_dir: str = '/app'
    logs_dir: str = '/app/logs'

    # Runtime state (not from config)
    worker_id: Optional[str] = None

    @classmethod
    def from_env(cls) -> 'WorkerConfig':
        """
        Load configuration from environment variables.

        Environment variables:
            WORKER_NAME: Unique name for this worker (required)
            SERVER_URL: Primary server URL (required)
            REGISTRATION_TOKEN: Token for registration (required)
            WORKER_TAGS: Comma-separated list of tags
            CHECKIN_INTERVAL: Seconds between check-ins (default 600)
            SYNC_INTERVAL: Seconds between sync checks (default 300)
            POLL_INTERVAL: Seconds between job polls (default 5)
            MAX_CONCURRENT_JOBS: Max parallel jobs (default 2)
            CONTENT_DIR: Base directory for Ansible content
            LOGS_DIR: Directory for job logs
        """
        worker_name = os.environ.get('WORKER_NAME', '')
        server_url = os.environ.get('SERVER_URL', '')
        registration_token = os.environ.get('REGISTRATION_TOKEN', '')

        if not worker_name:
            raise ValueError("WORKER_NAME environment variable is required")
        if not server_url:
            raise ValueError("SERVER_URL environment variable is required")
        if not registration_token:
            raise ValueError("REGISTRATION_TOKEN environment variable is required")

        # Parse tags
        tags_str = os.environ.get('WORKER_TAGS', '')
        tags = [t.strip() for t in tags_str.split(',') if t.strip()]

        return cls(
            worker_name=worker_name,
            server_url=server_url.rstrip('/'),
            registration_token=registration_token,
            tags=tags,
            checkin_interval=int(os.environ.get('CHECKIN_INTERVAL', '600')),
            sync_interval=int(os.environ.get('SYNC_INTERVAL', '300')),
            poll_interval=int(os.environ.get('POLL_INTERVAL', '5')),
            max_concurrent_jobs=int(os.environ.get('MAX_CONCURRENT_JOBS', '2')),
            content_dir=os.environ.get('CONTENT_DIR', '/app'),
            logs_dir=os.environ.get('LOGS_DIR', '/app/logs'),
        )

    def validate(self) -> List[str]:
        """
        Validate configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.worker_name:
            errors.append("worker_name is required")

        if not self.server_url:
            errors.append("server_url is required")

        if not self.registration_token:
            errors.append("registration_token is required")

        if self.checkin_interval < 10:
            errors.append("checkin_interval must be at least 10 seconds")

        if self.max_concurrent_jobs < 1:
            errors.append("max_concurrent_jobs must be at least 1")

        return errors

    def to_dict(self) -> dict:
        """Convert to dictionary (excluding sensitive data)."""
        return {
            'worker_name': self.worker_name,
            'server_url': self.server_url,
            'tags': self.tags,
            'checkin_interval': self.checkin_interval,
            'sync_interval': self.sync_interval,
            'poll_interval': self.poll_interval,
            'max_concurrent_jobs': self.max_concurrent_jobs,
            'content_dir': self.content_dir,
            'logs_dir': self.logs_dir,
            'worker_id': self.worker_id,
        }
