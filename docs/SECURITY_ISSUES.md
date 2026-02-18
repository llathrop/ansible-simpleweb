# Security Issues Inventory

**Last Updated:** 2026-02-18
**Security Review Phase:** 4 Complete

## Overview

This document tracks all security issues identified during the security review phases, prioritized by criticality and ease of fix.

## Priority Matrix

| Priority | Criticality | Ease of Fix |
|----------|-------------|-------------|
| P1 | Critical | Easy |
| P2 | Critical | Medium |
| P3 | High | Easy |
| P4 | Critical | Hard |
| P5 | High | Medium |
| P6 | Medium | Easy |

---

## Fixed Issues

### [CRITICAL] Tarfile Path Traversal (CVE-22) - FIXED

**Priority:** P1 - Critical/Easy
**Status:** ✅ Fixed in Phase 4.1
**Affected Component:** `worker/sync.py`
**Impact:** Remote code execution via malicious tarball extraction

**Remediation:**
- Added `_safe_extract_filter()` function to validate tarfile members
- Rejects absolute paths, path traversal (../), and out-of-directory extraction
- All tarfile extraction now uses member filtering

---

## Remaining Issues

### [MEDIUM] Dependency Vulnerabilities

**Priority:** P6 - Medium/Easy
**Status:** ⚠️ Requires Attention
**Affected Components:** Package dependencies

**Vulnerable Packages (from pip-audit):**
| Package | Current | CVE | Fixed Version |
|---------|---------|-----|---------------|
| ansible | 8.7.0 | CVE-2025-14010 | 12.2.0 |
| ansible-core | 2.15.13 | CVE-2024-8775, CVE-2024-11079 | 2.17.7+ |
| cryptography | 46.0.4 | CVE-2026-26007 | 46.0.5 |
| eventlet | 0.34.2 | CVE-2023-29483, CVE-2025-58068 | 0.40.3 |
| pymongo | 4.6.1 | CVE-2024-5629 | 4.6.3 |
| requests | 2.31.0 | CVE-2024-35195, CVE-2024-47081 | 2.32.4 |

**Remediation:**
Update requirements.txt with fixed versions. Note: Ansible upgrades may require testing for compatibility.

---

### [LOW] Subprocess Usage (Expected)

**Priority:** P6 - Low/Expected
**Status:** ℹ️ Acknowledged - Expected Behavior
**Affected Components:** `web/app.py`, `worker/executor.py`, `web/deployment.py`

**Description:**
Bandit flagged subprocess usage as potential security risk. However, this is expected behavior for an Ansible execution tool:
- `subprocess.Popen` is used to execute ansible-playbook commands
- All playbook names are validated against allowed playbooks list
- Target validation is performed before execution

**Mitigations in Place:**
- Playbook names validated against filesystem
- No shell=True in subprocess calls
- Working directory constrained to /app
- Input sanitization via validation module

---

### [LOW] Hardcoded /tmp Directory

**Priority:** P6 - Low/Easy
**Status:** ⚠️ Minor Risk
**Affected Components:** `web/app.py`, `web/content_repo.py`

**Description:**
Some temporary file operations use hardcoded `/tmp` directory.

**Files Affected:**
- `web/app.py:286` - Managed inventory temp file
- `web/app.py:473` - Batch inventory temp file
- `web/content_repo.py:432` - Content archive

**Remediation:**
Consider using `tempfile.mkdtemp()` without hardcoded directory, or configure via environment variable.

---

### [LOW] Try/Except/Pass Patterns

**Priority:** P6 - Low/Easy
**Status:** ℹ️ Acceptable Pattern
**Affected Components:** Various cleanup code

**Description:**
Several try/except/pass patterns exist for cleanup operations where failure is acceptable (e.g., removing temp files).

**Files Affected:**
- `web/app.py` - Cleanup operations
- `web/scheduler.py` - APScheduler job removal
- `web/deployment.py` - Connectivity checks

**Remediation:**
Consider logging exceptions at DEBUG level for troubleshooting while maintaining silent failure for cleanup.

---

### [INFO] MongoDB Password False Positive

**Priority:** N/A
**Status:** ✅ False Positive
**Affected Component:** `web/storage/mongodb.py`

**Description:**
Bandit flagged `{'password_hash': 0}` as hardcoded password. This is a MongoDB projection to exclude the password_hash field, not a hardcoded password.

---

## Security Hardening Implemented

### Authentication & Authorization
- [x] User authentication with bcrypt password hashing
- [x] Session management with secure cookies
- [x] API token authentication for programmatic access
- [x] Worker token authentication
- [x] Agent service authentication
- [x] Role-based access control (RBAC)
- [x] Hierarchical permissions
- [x] Dynamic role management
- [x] Ownership-based filtering for jobs/schedules

### Transport Security
- [x] SSL/TLS support with auto-generated certificates
- [x] Certificate management module
- [x] HTTPS redirect capability
- [x] SSL verification for inter-service communication

### Security Headers
- [x] X-Content-Type-Options: nosniff
- [x] X-Frame-Options: DENY
- [x] X-XSS-Protection: 1; mode=block
- [x] Content-Security-Policy
- [x] Strict-Transport-Security (when SSL enabled)
- [x] Referrer-Policy
- [x] Permissions-Policy

### Input Validation
- [x] Validation module for all input types
- [x] Path traversal prevention
- [x] Playbook name validation
- [x] Username/email validation
- [x] Permission format validation

### Audit & Monitoring
- [x] Comprehensive audit logging
- [x] Account lockout after failed attempts
- [x] Login/logout event logging
- [x] Security-sensitive operation logging

---

## Recommendations for Production

1. **Update Dependencies**
   - Upgrade ansible to 12.2.0+
   - Upgrade cryptography to 46.0.5
   - Upgrade eventlet to 0.40.3
   - Upgrade pymongo to 4.6.3
   - Upgrade requests to 2.32.4

2. **MongoDB Security**
   - Enable authentication with MONGO_INITDB_ROOT_USERNAME/PASSWORD
   - Create dedicated application user with least privilege
   - Bind to internal network only

3. **SSL/TLS**
   - Use production certificates (not self-signed)
   - Enable HSTS with preload
   - Consider certificate pinning for workers

4. **Session Security**
   - Configure session timeout appropriately
   - Use Redis for session storage at scale
   - Enable secure cookie flags

5. **Network Security**
   - Restrict access to port 3443 only
   - Use firewall rules to limit worker connectivity
   - Consider VPN for worker communication

---

## Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| test_auth.py | Password hashing, sessions | ✅ |
| test_authz.py | Permissions, roles | ✅ |
| test_rbac_advanced.py | Hierarchical permissions | ✅ |
| test_roles_dynamic.py | Role CRUD | ✅ |
| test_job_permissions.py | Job ownership | ✅ |
| test_schedule_permissions.py | Schedule ownership | ✅ |
| test_worker_acls.py | Worker permissions | ✅ |
| test_agent_acls.py | Agent permissions | ✅ |
| test_tarfile_security.py | Path traversal prevention | ✅ |
| test_security_headers.py | Security headers | ✅ |
| test_validation.py | Input validation | ✅ |
| test_ssl_config.py | SSL configuration | ✅ |

Total Security Tests: 200+
