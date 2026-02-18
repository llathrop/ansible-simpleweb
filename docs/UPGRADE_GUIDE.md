# Upgrade Guide: Security Implementation

This guide covers upgrading from a non-authenticated ansible-simpleweb installation to the new security-enabled version.

## Overview

The security update adds:
- User authentication with bcrypt password hashing
- Role-based access control (RBAC) with hierarchical permissions
- SSL/TLS support with auto-generated or user-provided certificates
- Comprehensive audit logging
- Security headers and input validation
- API token authentication

## Breaking Changes

### Authentication Required

All API endpoints now require authentication. You have two options:

1. **Session-based authentication** (web UI)
   - Login at `/login` with username/password
   - Session cookies maintain authentication

2. **API Token authentication** (programmatic access)
   - Generate tokens via web UI at `/tokens`
   - Include `X-API-Token: <token>` header in requests

### URL Changes

| Before | After |
|--------|-------|
| http://localhost:3001 | https://localhost:3443 |
| Worker `SERVER_URL` | Update to HTTPS URL |
| Agent `SERVER_URL` | Update to HTTPS URL |

### Worker Authentication

Workers must update their configuration:

```yaml
# docker-compose.yml - worker configuration
environment:
  - SERVER_URL=https://ansible-web:3443
  - REGISTRATION_TOKEN=<new-worker-token>
  - SSL_VERIFY=false  # For self-signed certs, or true for valid certs
```

### New Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AUTH_ENABLED` | No | `true` | Enable authentication |
| `INITIAL_ADMIN_USER` | First run | `admin` | Bootstrap admin username |
| `INITIAL_ADMIN_PASSWORD` | First run | - | Bootstrap admin password |
| `SSL_ENABLED` | No | `false` | Enable HTTPS |
| `SSL_MODE` | No | `auto` | Certificate mode |
| `MONGO_PASSWORD` | If MongoDB auth | - | MongoDB admin password |
| `SESSION_TIMEOUT` | No | `3600` | Session timeout (seconds) |

## Prerequisites

Before upgrading:

1. **Create backup**
   ```bash
   ./scripts/backup_environment.sh
   ```

2. **Verify backup** - Test restore in separate directory

3. **Plan maintenance window** - Users will be logged out

4. **Prepare credentials**
   - Choose admin password (12+ characters)
   - Choose MongoDB password (if using MongoDB)

## Upgrade Steps

### Step 1: Create Backup

```bash
./scripts/backup_environment.sh
```

Verify backup directory created in `backups/`.

### Step 2: Stop Services

```bash
docker compose down
```

### Step 3: Pull Latest Code

```bash
git checkout main
git pull origin main
```

Or if using the security branch:
```bash
git checkout feat/security
```

### Step 4: Set Environment Variables

Create or update `.env` file:

```bash
# Required for first run
INITIAL_ADMIN_USER=admin
INITIAL_ADMIN_PASSWORD=YourSecurePassword123!

# SSL configuration
SSL_ENABLED=true
SSL_MODE=auto  # or 'provided' if you have certificates

# MongoDB (if using authentication)
MONGO_PASSWORD=YourMongoPassword123!

# Optional
SESSION_TIMEOUT=3600
```

### Step 5: Update Docker Compose (if needed)

Ensure your `docker-compose.yml` includes HTTPS port:

```yaml
ansible-web:
  ports:
    - "3001:3001"   # HTTP (redirects to HTTPS)
    - "3443:3443"   # HTTPS
  volumes:
    - ./config/certs:/app/config/certs  # For SSL certificates
```

### Step 6: Build and Start

```bash
docker compose build
docker compose up -d
```

### Step 7: Verify Installation

1. Access https://localhost:3443 (accept self-signed cert warning)
2. Login with admin credentials
3. Verify existing data is intact:
   - Schedules
   - Inventory
   - Job history

### Step 8: Update Workers

For each worker:

1. Stop the worker
2. Update environment:
   ```yaml
   SERVER_URL: https://<primary-host>:3443
   SSL_VERIFY: false  # For self-signed, or true for valid certs
   ```
3. Restart the worker
4. Verify connection in web UI

### Step 9: Generate API Tokens (if needed)

For automation scripts that previously accessed the API:

1. Login to web UI
2. Navigate to `/tokens`
3. Create token with appropriate permissions
4. Update scripts to include `X-API-Token` header

## Rollback Procedure

If issues occur:

```bash
# Stop failed migration
docker compose down

# Restore from backup
./scripts/restore_environment.sh backups/pre-security-<timestamp>

# Checkout previous version
git checkout <previous-commit>

# Restart
docker compose up -d
```

## Gradual Migration (Optional)

For gradual migration, you can temporarily disable authentication:

```bash
# .env
AUTH_ENABLED=false
```

This allows you to:
1. Deploy the new version
2. Test functionality
3. Create users and tokens
4. Enable authentication when ready

**Warning**: This should only be used temporarily. Do not run without authentication in production.

## Post-Upgrade Tasks

After successful upgrade:

1. **Create additional users**
   - Admin users for team members
   - Service accounts for automation

2. **Review default roles**
   - Assign appropriate roles to users
   - Create custom roles if needed

3. **Generate worker tokens**
   - Create unique tokens for each worker
   - Retire shared registration token

4. **Configure monitoring**
   - Set up alerts for authentication failures
   - Monitor audit logs

5. **Update documentation**
   - Update internal docs with new URLs
   - Document API token usage

## Troubleshooting

### Cannot Login

**Symptoms**: Login page shows error, credentials rejected

**Solutions**:
1. Check `INITIAL_ADMIN_PASSWORD` was set correctly
2. Check logs: `docker compose logs ansible-web`
3. Reset admin password via CLI:
   ```bash
   docker compose exec ansible-web python scripts/create_admin.py --reset
   ```

### SSL Certificate Errors

**Symptoms**: Browser shows certificate warning, workers cannot connect

**Solutions**:
1. For self-signed certs, accept browser warning
2. For workers, set `SSL_VERIFY=false` (self-signed) or provide CA cert
3. To regenerate certificate:
   ```bash
   rm -rf config/certs/*
   docker compose restart ansible-web
   ```

### Workers Cannot Connect

**Symptoms**: Workers show as offline, connection refused

**Solutions**:
1. Update `SERVER_URL` to use HTTPS
2. Set `SSL_VERIFY=false` for self-signed certificates
3. Check firewall allows port 3443
4. Verify worker token is valid

### Existing Data Missing

**Symptoms**: Schedules, inventory, or jobs not visible

**Solutions**:
1. Check storage backend configuration
2. For flatfile: verify `config/` directory permissions
3. For MongoDB: check connection credentials
4. Restore from backup if needed

### API Requests Failing

**Symptoms**: Scripts that used API now get 401 errors

**Solutions**:
1. Generate API token via web UI
2. Add `X-API-Token` header to requests
3. Verify token has required permissions

## Support

For issues not covered here:

1. Check logs: `docker compose logs`
2. Run security scan: `./scripts/security_scan.sh`
3. Review audit logs in web UI
4. File issue at project repository
