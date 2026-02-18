# Production Security Checklist

This checklist ensures ansible-simpleweb is deployed securely. Complete all items before going to production.

## Pre-Deployment

### Authentication Setup

- [ ] **Change default admin password**
  - Run: `docker compose exec ansible-web python scripts/create_admin.py --username admin --password <SECURE_PASSWORD>`
  - Use a strong password (16+ characters, mixed case, numbers, symbols)

- [ ] **Create additional users with appropriate roles**
  - Assign minimum necessary permissions (principle of least privilege)
  - Use role-based access: `admin`, `operator`, `monitor`, `developer`

- [ ] **Configure session timeout**
  - Set `SESSION_TIMEOUT` environment variable (default: 3600 seconds)
  - For sensitive environments, consider shorter timeouts (900-1800 seconds)

### SSL/TLS Configuration

- [ ] **Generate or provide SSL certificates**
  - Auto-generated: Set `SSL_MODE=auto` for self-signed certificates
  - Production: Set `SSL_MODE=provided` and provide valid certificates
  - Certificate paths: `SSL_CERT_PATH`, `SSL_KEY_PATH`

- [ ] **Enable HTTPS**
  - Set `SSL_ENABLED=true`
  - Access via port 3443 (HTTPS)

- [ ] **Configure HSTS** (if using production certificates)
  - Automatically enabled when SSL is enabled
  - Consider adding to HSTS preload list for maximum security

### Database Security

- [ ] **Enable MongoDB authentication**
  ```yaml
  # docker-compose.yml
  mongodb:
    environment:
      - MONGO_INITDB_ROOT_USERNAME=admin
      - MONGO_INITDB_ROOT_PASSWORD=${MONGO_PASSWORD}
  ```

- [ ] **Use strong MongoDB password**
  - Set `MONGO_PASSWORD` in environment
  - Use 20+ character random password

- [ ] **Create dedicated application user**
  - Don't use root credentials for application
  - Grant only necessary permissions (readWrite on app database)

- [ ] **Bind MongoDB to internal network**
  - Remove port mapping from docker-compose if not needed externally
  - Use internal Docker network for app communication

### Worker Security

- [ ] **Regenerate worker registration tokens**
  - Generate unique tokens for each worker
  - Store securely, do not share between workers

- [ ] **Configure worker SSL verification**
  - Set `SSL_VERIFY=true` for production certificates
  - Only use `SSL_VERIFY=false` for self-signed in isolated environments

### Network Security

- [ ] **Configure firewall rules**
  - Only expose port 3443 (HTTPS) to users
  - Block direct access to MongoDB port (27017)
  - Restrict worker connectivity to necessary hosts

- [ ] **Use VPN for worker communication** (recommended)
  - Workers should connect over secure network
  - Consider WireGuard or OpenVPN

- [ ] **Disable HTTP redirect in production** (optional)
  - If not using HTTP at all, remove port 3001 mapping

## Post-Deployment

### Verification

- [ ] **Test authentication**
  - Verify login works with correct credentials
  - Verify login fails with incorrect credentials
  - Verify session timeout works

- [ ] **Test authorization**
  - Verify each role can only access permitted resources
  - Test API token authentication
  - Verify workers authenticate correctly

- [ ] **Test SSL/TLS**
  - Verify HTTPS connection works
  - Check certificate validity (browser shows secure connection)
  - Test HTTP to HTTPS redirect if enabled

- [ ] **Review audit logs**
  - Check `/audit` page for login events
  - Verify sensitive operations are logged

### Monitoring

- [ ] **Set up log monitoring**
  - Monitor authentication failures
  - Alert on account lockouts
  - Track unauthorized access attempts

- [ ] **Configure backup schedule**
  - Regular database backups
  - Certificate and key backups (store securely)
  - Configuration backups

- [ ] **Set up health monitoring**
  - Monitor `/health` endpoint
  - Alert on service unavailability

## Periodic Maintenance

### Weekly

- [ ] **Review audit logs**
  - Look for unusual patterns
  - Check for failed authentication spikes

- [ ] **Check certificate expiry**
  - Auto-generated certs expire in 365 days
  - Plan renewal before expiry

### Monthly

- [ ] **Review user accounts**
  - Disable unused accounts
  - Verify role assignments are appropriate
  - Remove unnecessary permissions

- [ ] **Update dependencies**
  - Check for security updates: `pip-audit`
  - Test updates in staging before production

- [ ] **Review security advisories**
  - Check Ansible security announcements
  - Monitor CVE databases for dependencies

### Quarterly

- [ ] **Security audit**
  - Run `scripts/security_scan.sh`
  - Review and address findings

- [ ] **Rotate secrets**
  - Rotate MongoDB passwords
  - Regenerate worker tokens
  - Consider rotating API tokens

- [ ] **Test backup restoration**
  - Verify backups are restorable
  - Document restoration procedure

## Incident Response

### Account Compromise

1. **Disable compromised account immediately**
2. **Review audit logs** for unauthorized actions
3. **Revoke all API tokens** for affected user
4. **Reset password** after investigation
5. **Review other accounts** for similar issues

### Certificate Compromise

1. **Revoke compromised certificate**
2. **Generate new certificates** immediately
3. **Update all workers** with new cert verification
4. **Review access logs** for unauthorized connections

### Data Breach

1. **Isolate affected systems**
2. **Preserve logs** for investigation
3. **Assess scope** of data exposure
4. **Notify stakeholders** as required
5. **Implement remediation** measures

## Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTH_ENABLED` | Enable authentication | `true` |
| `SSL_ENABLED` | Enable HTTPS | `false` |
| `SSL_MODE` | Certificate mode (auto/provided/disabled) | `auto` |
| `SSL_CERT_PATH` | Path to SSL certificate | `/app/config/certs/server.crt` |
| `SSL_KEY_PATH` | Path to SSL private key | `/app/config/certs/server.key` |
| `SESSION_TIMEOUT` | Session timeout in seconds | `3600` |
| `MONGO_PASSWORD` | MongoDB admin password | (required if auth enabled) |
| `INITIAL_ADMIN_USER` | Bootstrap admin username | `admin` |
| `INITIAL_ADMIN_PASSWORD` | Bootstrap admin password | (required on first run) |
| `SSL_VERIFY` | Verify SSL certificates (workers) | `true` |

## Quick Security Commands

```bash
# Run security scan
./scripts/security_scan.sh

# Check dependency vulnerabilities
pip-audit

# View recent audit logs
docker compose exec ansible-web python -c "
from web.storage.flatfile import FlatFileStorage
s = FlatFileStorage()
for entry in s.get_audit_log(limit=10):
    print(f\"{entry['timestamp']} - {entry['user']} - {entry['action']}\")
"

# List users
docker compose exec ansible-web python -c "
from web.storage.flatfile import FlatFileStorage
s = FlatFileStorage()
for user in s.get_all_users():
    print(f\"{user['username']} - roles: {user.get('roles', [])}\")
"

# Check certificate expiry
openssl x509 -enddate -noout -in config/certs/server.crt
```
