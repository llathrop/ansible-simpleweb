"""
Gunicorn Configuration for Ansible SimpleWeb

This configuration supports both HTTP and HTTPS modes.
SSL is enabled when SSL_ENABLED=true environment variable is set.
"""

import os
import multiprocessing

# Server socket
bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:3001')

# Worker configuration
worker_class = 'eventlet'  # Required for SocketIO support
workers = int(os.environ.get('GUNICORN_WORKERS', 1))  # Keep at 1 for SocketIO
threads = int(os.environ.get('GUNICORN_THREADS', 1))
worker_connections = int(os.environ.get('GUNICORN_WORKER_CONNECTIONS', 1000))

# Request handling
timeout = int(os.environ.get('GUNICORN_TIMEOUT', 120))
graceful_timeout = int(os.environ.get('GUNICORN_GRACEFUL_TIMEOUT', 30))
keepalive = int(os.environ.get('GUNICORN_KEEPALIVE', 2))

# Max request handling (helps with memory leaks)
max_requests = int(os.environ.get('GUNICORN_MAX_REQUESTS', 10000))
max_requests_jitter = int(os.environ.get('GUNICORN_MAX_REQUESTS_JITTER', 1000))

# SSL Configuration
ssl_enabled = os.environ.get('SSL_ENABLED', 'false').lower() in ('true', '1', 'yes')

if ssl_enabled:
    certfile = os.environ.get('SSL_CERT_PATH', '/app/config/certs/server.crt')
    keyfile = os.environ.get('SSL_KEY_PATH', '/app/config/certs/server.key')
    ca_certs = os.environ.get('SSL_CA_PATH') or None

    # SSL settings
    ssl_version = 'TLSv1_2'
    ciphers = 'ECDHE+AESGCM:DHE+AESGCM:ECDHE+CHACHA20:DHE+CHACHA20:!aNULL:!MD5:!DSS'

# Logging
accesslog = os.environ.get('GUNICORN_ACCESS_LOG', '-')
errorlog = os.environ.get('GUNICORN_ERROR_LOG', '-')
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')

# Access log format (similar to nginx combined format)
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Security headers (added in response)
forwarded_allow_ips = os.environ.get('GUNICORN_FORWARDED_ALLOW_IPS', '*')

# Limit request sizes
limit_request_line = int(os.environ.get('GUNICORN_LIMIT_REQUEST_LINE', 4094))
limit_request_fields = int(os.environ.get('GUNICORN_LIMIT_REQUEST_FIELDS', 100))
limit_request_field_size = int(os.environ.get('GUNICORN_LIMIT_REQUEST_FIELD_SIZE', 8190))


def on_starting(server):
    """Called just before the master process is initialized."""
    if ssl_enabled:
        print(f"Starting Gunicorn with HTTPS on {bind}")
        print(f"  Certificate: {certfile}")
        print(f"  Private Key: {keyfile}")
    else:
        print(f"Starting Gunicorn with HTTP on {bind}")


def worker_int(worker):
    """Called when a worker is interrupted."""
    print(f"Worker {worker.pid} received interrupt signal")


def worker_abort(worker):
    """Called when a worker times out."""
    print(f"Worker {worker.pid} was aborted (timeout)")


def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass


def post_fork(server, worker):
    """Called just after a worker is forked."""
    pass


def when_ready(server):
    """Called when the server is ready to accept requests."""
    print("Gunicorn server is ready")
