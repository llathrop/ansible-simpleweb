"""
Tests for Certificate Management - Phase 2.1

Tests:
- Self-signed certificate generation
- Certificate loading and validation
- Certificate info extraction
- Certificate expiry checking
- Uploaded certificate validation
"""

import pytest
import tempfile
import os
import sys
from datetime import datetime, timezone, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from web.certificates import (
    generate_self_signed_cert,
    load_certificate,
    validate_certificate,
    get_cert_info,
    check_cert_expiry,
    ensure_certificate,
    save_uploaded_certificate,
    CertificateError,
    CRYPTOGRAPHY_AVAILABLE
)


# Skip all tests if cryptography not available
pytestmark = pytest.mark.skipif(
    not CRYPTOGRAPHY_AVAILABLE,
    reason="cryptography library not installed"
)


class TestGenerateSelfSignedCert:
    """Tests for self-signed certificate generation."""

    def test_generate_default_cert(self):
        """Should generate certificate with default settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            result_cert, result_key = generate_self_signed_cert(
                hostname='localhost',
                cert_path=cert_path,
                key_path=key_path
            )

            assert result_cert == cert_path
            assert result_key == key_path
            assert os.path.exists(cert_path)
            assert os.path.exists(key_path)

    def test_generate_with_custom_hostname(self):
        """Should generate certificate with custom hostname."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='myserver.example.com',
                cert_path=cert_path,
                key_path=key_path
            )

            info = get_cert_info(cert_path)
            assert info['subject']['commonName'] == 'myserver.example.com'

    def test_generate_with_custom_validity(self):
        """Should generate certificate with custom validity period."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='localhost',
                days=30,
                cert_path=cert_path,
                key_path=key_path
            )

            info = get_cert_info(cert_path)
            assert info['days_until_expiry'] <= 30
            assert info['days_until_expiry'] >= 29  # Account for timing

    def test_key_permissions(self):
        """Private key should have restricted permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='localhost',
                cert_path=cert_path,
                key_path=key_path
            )

            # Check key permissions (0600 = owner read/write only)
            key_mode = os.stat(key_path).st_mode & 0o777
            assert key_mode == 0o600

    def test_generates_san(self):
        """Certificate should include SAN extension."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='myserver.local',
                cert_path=cert_path,
                key_path=key_path
            )

            info = get_cert_info(cert_path)
            assert len(info['san']) > 0
            assert 'DNS:myserver.local' in info['san']


class TestLoadCertificate:
    """Tests for certificate loading."""

    def test_load_valid_cert(self):
        """Should load a valid certificate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='localhost',
                cert_path=cert_path,
                key_path=key_path
            )

            cert = load_certificate(cert_path)
            assert cert is not None

    def test_load_nonexistent_cert(self):
        """Should raise error for nonexistent certificate."""
        with pytest.raises(CertificateError) as exc:
            load_certificate('/nonexistent/path/cert.pem')

        assert 'not found' in str(exc.value).lower()

    def test_load_invalid_cert(self):
        """Should raise error for invalid certificate data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'invalid.crt')

            # Write invalid data
            with open(cert_path, 'w') as f:
                f.write('not a certificate')

            with pytest.raises(CertificateError):
                load_certificate(cert_path)


class TestValidateCertificate:
    """Tests for certificate validation."""

    def test_validate_valid_cert(self):
        """Should validate a valid certificate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='localhost',
                cert_path=cert_path,
                key_path=key_path
            )

            is_valid, error = validate_certificate(cert_path, key_path)
            assert is_valid is True
            assert error == ''

    def test_validate_cert_without_key(self):
        """Should validate certificate without key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='localhost',
                cert_path=cert_path,
                key_path=key_path
            )

            is_valid, error = validate_certificate(cert_path)
            assert is_valid is True
            assert error == ''

    def test_validate_mismatched_key(self):
        """Should fail validation with mismatched key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate first cert
            cert1_path = os.path.join(tmpdir, 'cert1.crt')
            key1_path = os.path.join(tmpdir, 'key1.key')
            generate_self_signed_cert(
                hostname='localhost',
                cert_path=cert1_path,
                key_path=key1_path
            )

            # Generate second cert (different key)
            cert2_path = os.path.join(tmpdir, 'cert2.crt')
            key2_path = os.path.join(tmpdir, 'key2.key')
            generate_self_signed_cert(
                hostname='localhost',
                cert_path=cert2_path,
                key_path=key2_path
            )

            # Try to validate cert1 with key2
            is_valid, error = validate_certificate(cert1_path, key2_path)
            assert is_valid is False
            assert 'do not match' in error.lower()

    def test_validate_missing_key(self):
        """Should fail validation when key is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='localhost',
                cert_path=cert_path,
                key_path=key_path
            )

            # Remove key
            os.remove(key_path)

            is_valid, error = validate_certificate(cert_path, key_path)
            assert is_valid is False
            assert 'not found' in error.lower()


class TestGetCertInfo:
    """Tests for certificate info extraction."""

    def test_get_info_basic(self):
        """Should extract basic certificate info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='testhost.example.com',
                days=180,
                cert_path=cert_path,
                key_path=key_path,
                organization='Test Org',
                country='US'
            )

            info = get_cert_info(cert_path)

            assert info['subject']['commonName'] == 'testhost.example.com'
            assert info['subject']['organizationName'] == 'Test Org'
            assert info['subject']['countryName'] == 'US'
            assert info['is_self_signed'] is True
            assert 'serial_number' in info

    def test_get_info_expiry(self):
        """Should calculate expiry correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='localhost',
                days=365,
                cert_path=cert_path,
                key_path=key_path
            )

            info = get_cert_info(cert_path)

            assert info['is_expired'] is False
            assert info['days_until_expiry'] >= 364
            assert info['days_until_expiry'] <= 365


class TestCheckCertExpiry:
    """Tests for certificate expiry checking."""

    def test_check_valid_cert(self):
        """Should return valid status for fresh cert."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generate_self_signed_cert(
                hostname='localhost',
                days=365,
                cert_path=cert_path,
                key_path=key_path
            )

            status, days = check_cert_expiry(cert_path, warn_days=30)

            assert status == 'valid'
            assert days >= 364

    def test_check_expiring_cert(self):
        """Should return expiring status for cert within warn threshold."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            # Create cert that expires in 10 days
            generate_self_signed_cert(
                hostname='localhost',
                days=10,
                cert_path=cert_path,
                key_path=key_path
            )

            status, days = check_cert_expiry(cert_path, warn_days=30)

            assert status == 'expiring'
            assert days <= 10

    def test_check_error_for_missing(self):
        """Should return error for missing cert."""
        status, days = check_cert_expiry('/nonexistent/cert.pem')

        assert status == 'error'
        assert days == 0


class TestEnsureCertificate:
    """Tests for ensure_certificate function."""

    def test_ensure_generates_if_missing(self):
        """Should generate certificate if none exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            generated, message = ensure_certificate(
                cert_path=cert_path,
                key_path=key_path,
                hostname='localhost'
            )

            assert generated is True
            assert os.path.exists(cert_path)
            assert os.path.exists(key_path)
            assert 'Generated' in message

    def test_ensure_keeps_valid_cert(self):
        """Should not regenerate valid certificate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            # Generate initial cert
            generate_self_signed_cert(
                hostname='localhost',
                days=365,
                cert_path=cert_path,
                key_path=key_path
            )

            # Get original serial
            info1 = get_cert_info(cert_path)

            # Ensure (should not regenerate)
            generated, message = ensure_certificate(
                cert_path=cert_path,
                key_path=key_path,
                hostname='localhost',
                renew_days=30
            )

            # Get new serial
            info2 = get_cert_info(cert_path)

            assert generated is False
            assert info1['serial_number'] == info2['serial_number']
            assert 'valid' in message.lower()

    def test_ensure_regenerates_if_forced(self):
        """Should regenerate certificate if forced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, 'server.crt')
            key_path = os.path.join(tmpdir, 'server.key')

            # Generate initial cert
            generate_self_signed_cert(
                hostname='localhost',
                cert_path=cert_path,
                key_path=key_path
            )

            info1 = get_cert_info(cert_path)

            # Force regenerate
            generated, message = ensure_certificate(
                cert_path=cert_path,
                key_path=key_path,
                hostname='localhost',
                regenerate=True
            )

            info2 = get_cert_info(cert_path)

            assert generated is True
            assert info1['serial_number'] != info2['serial_number']


class TestSaveUploadedCertificate:
    """Tests for uploaded certificate validation and saving."""

    def test_save_valid_upload(self):
        """Should save valid uploaded certificate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate a cert to use as "uploaded" data
            temp_cert = os.path.join(tmpdir, 'temp.crt')
            temp_key = os.path.join(tmpdir, 'temp.key')

            generate_self_signed_cert(
                hostname='localhost',
                cert_path=temp_cert,
                key_path=temp_key
            )

            # Read the generated files
            with open(temp_cert, 'rb') as f:
                cert_data = f.read()
            with open(temp_key, 'rb') as f:
                key_data = f.read()

            # "Upload" to new location
            final_cert = os.path.join(tmpdir, 'final.crt')
            final_key = os.path.join(tmpdir, 'final.key')

            success, error = save_uploaded_certificate(
                cert_data=cert_data,
                key_data=key_data,
                cert_path=final_cert,
                key_path=final_key
            )

            assert success is True
            assert error == ''
            assert os.path.exists(final_cert)
            assert os.path.exists(final_key)

    def test_reject_mismatched_upload(self):
        """Should reject upload with mismatched cert/key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate two different certs
            cert1_path = os.path.join(tmpdir, 'cert1.crt')
            key1_path = os.path.join(tmpdir, 'key1.key')
            cert2_path = os.path.join(tmpdir, 'cert2.crt')
            key2_path = os.path.join(tmpdir, 'key2.key')

            generate_self_signed_cert(
                hostname='host1',
                cert_path=cert1_path,
                key_path=key1_path
            )
            generate_self_signed_cert(
                hostname='host2',
                cert_path=cert2_path,
                key_path=key2_path
            )

            # Read mismatched data
            with open(cert1_path, 'rb') as f:
                cert_data = f.read()
            with open(key2_path, 'rb') as f:
                key_data = f.read()

            # Try to upload
            final_cert = os.path.join(tmpdir, 'final.crt')
            final_key = os.path.join(tmpdir, 'final.key')

            success, error = save_uploaded_certificate(
                cert_data=cert_data,
                key_data=key_data,
                cert_path=final_cert,
                key_path=final_key
            )

            assert success is False
            assert 'do not match' in error.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
