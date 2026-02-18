"""
Certificate Management Module for Ansible SimpleWeb

Provides SSL/TLS certificate functionality including:
- Self-signed certificate generation
- Certificate loading and validation
- Certificate information extraction
- Certificate expiry monitoring
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


class CertificateError(Exception):
    """Raised when certificate operations fail."""
    pass


def check_cryptography_available():
    """Check if cryptography library is available."""
    if not CRYPTOGRAPHY_AVAILABLE:
        raise CertificateError(
            "cryptography library not installed. "
            "Install with: pip install cryptography"
        )


def generate_self_signed_cert(
    hostname: str = 'localhost',
    days: int = 365,
    cert_path: str = None,
    key_path: str = None,
    organization: str = 'Ansible SimpleWeb',
    country: str = 'US',
    state: str = 'California',
    locality: str = 'San Francisco',
    key_size: int = 2048
) -> Tuple[str, str]:
    """
    Generate a self-signed SSL certificate and private key.

    Args:
        hostname: Hostname/CN for the certificate (default: localhost)
        days: Certificate validity in days (default: 365)
        cert_path: Path to save certificate (default: /app/config/certs/server.crt)
        key_path: Path to save private key (default: /app/config/certs/server.key)
        organization: Organization name for certificate
        country: Country code (2-letter)
        state: State or province
        locality: City or locality
        key_size: RSA key size in bits (default: 2048)

    Returns:
        Tuple of (cert_path, key_path)

    Raises:
        CertificateError: If generation fails
    """
    check_cryptography_available()

    # Default paths
    if cert_path is None:
        cert_path = '/app/config/certs/server.crt'
    if key_path is None:
        key_path = '/app/config/certs/server.key'

    try:
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend()
        )

        # Build certificate subject
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, country[:2]),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state),
            x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ])

        # Build certificate
        now = datetime.now(timezone.utc)
        cert_builder = x509.CertificateBuilder()
        cert_builder = cert_builder.subject_name(subject)
        cert_builder = cert_builder.issuer_name(subject)  # Self-signed
        cert_builder = cert_builder.public_key(private_key.public_key())
        cert_builder = cert_builder.serial_number(x509.random_serial_number())
        cert_builder = cert_builder.not_valid_before(now)
        cert_builder = cert_builder.not_valid_after(now + timedelta(days=days))

        # Add Subject Alternative Names (SAN)
        san_list = [x509.DNSName(hostname)]
        if hostname != 'localhost':
            san_list.append(x509.DNSName('localhost'))
        # Add IP addresses if hostname looks like one
        try:
            import ipaddress
            ip = ipaddress.ip_address(hostname)
            san_list.append(x509.IPAddress(ip))
        except ValueError:
            pass
        # Always add localhost IP
        import ipaddress
        san_list.append(x509.IPAddress(ipaddress.ip_address('127.0.0.1')))

        cert_builder = cert_builder.add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False
        )

        # Add basic constraints (not a CA)
        cert_builder = cert_builder.add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True
        )

        # Add key usage
        cert_builder = cert_builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False
            ),
            critical=True
        )

        # Add extended key usage (server authentication)
        cert_builder = cert_builder.add_extension(
            x509.ExtendedKeyUsage([
                x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH
            ]),
            critical=False
        )

        # Sign the certificate
        certificate = cert_builder.sign(private_key, hashes.SHA256(), default_backend())

        # Create directory if needed
        cert_dir = os.path.dirname(cert_path)
        if cert_dir:
            os.makedirs(cert_dir, mode=0o755, exist_ok=True)

        key_dir = os.path.dirname(key_path)
        if key_dir:
            os.makedirs(key_dir, mode=0o700, exist_ok=True)

        # Save private key (restricted permissions)
        with open(key_path, 'wb') as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
        os.chmod(key_path, 0o600)

        # Save certificate
        with open(cert_path, 'wb') as f:
            f.write(certificate.public_bytes(serialization.Encoding.PEM))
        os.chmod(cert_path, 0o644)

        return cert_path, key_path

    except Exception as e:
        raise CertificateError(f"Failed to generate certificate: {e}")


def load_certificate(cert_path: str) -> 'x509.Certificate':
    """
    Load a certificate from a PEM file.

    Args:
        cert_path: Path to the certificate file

    Returns:
        x509.Certificate object

    Raises:
        CertificateError: If loading fails
    """
    check_cryptography_available()

    if not os.path.exists(cert_path):
        raise CertificateError(f"Certificate file not found: {cert_path}")

    try:
        with open(cert_path, 'rb') as f:
            cert_data = f.read()

        certificate = x509.load_pem_x509_certificate(cert_data, default_backend())
        return certificate

    except Exception as e:
        raise CertificateError(f"Failed to load certificate: {e}")


def validate_certificate(cert_path: str, key_path: str = None) -> Tuple[bool, str]:
    """
    Validate a certificate file (and optionally its matching key).

    Args:
        cert_path: Path to the certificate file
        key_path: Optional path to the private key file

    Returns:
        Tuple of (is_valid, error_message)
        If valid, error_message is empty.
    """
    check_cryptography_available()

    try:
        # Load certificate
        cert = load_certificate(cert_path)

        # Check expiry
        now = datetime.now(timezone.utc)
        if cert.not_valid_before_utc > now:
            return False, "Certificate is not yet valid"
        if cert.not_valid_after_utc < now:
            return False, "Certificate has expired"

        # Check key match if provided
        if key_path:
            if not os.path.exists(key_path):
                return False, f"Private key file not found: {key_path}"

            try:
                with open(key_path, 'rb') as f:
                    key_data = f.read()

                private_key = serialization.load_pem_private_key(
                    key_data,
                    password=None,
                    backend=default_backend()
                )

                # Compare public keys
                cert_public_key = cert.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo
                )
                key_public_key = private_key.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo
                )

                if cert_public_key != key_public_key:
                    return False, "Certificate and private key do not match"

            except Exception as e:
                return False, f"Failed to validate private key: {e}"

        return True, ""

    except CertificateError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Certificate validation failed: {e}"


def get_cert_info(cert_path: str) -> Dict:
    """
    Extract information from a certificate.

    Args:
        cert_path: Path to the certificate file

    Returns:
        Dict with certificate information:
        - subject: Dict of subject fields (CN, O, OU, etc.)
        - issuer: Dict of issuer fields
        - serial_number: Certificate serial number
        - not_valid_before: Start of validity period (ISO format)
        - not_valid_after: End of validity period (ISO format)
        - days_until_expiry: Days until certificate expires
        - is_expired: Whether certificate has expired
        - is_self_signed: Whether certificate is self-signed
        - san: List of Subject Alternative Names

    Raises:
        CertificateError: If loading fails
    """
    check_cryptography_available()

    cert = load_certificate(cert_path)
    now = datetime.now(timezone.utc)

    # Extract subject fields
    def name_to_dict(name: x509.Name) -> Dict:
        result = {}
        for attr in name:
            oid_name = attr.oid._name
            result[oid_name] = attr.value
        return result

    # Extract SAN
    san_list = []
    try:
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        for name in san_ext.value:
            if isinstance(name, x509.DNSName):
                san_list.append(f"DNS:{name.value}")
            elif isinstance(name, x509.IPAddress):
                san_list.append(f"IP:{name.value}")
    except x509.ExtensionNotFound:
        pass

    # Calculate expiry
    expiry = cert.not_valid_after_utc
    days_until_expiry = (expiry - now).days
    is_expired = expiry < now

    # Check if self-signed
    is_self_signed = cert.subject == cert.issuer

    return {
        'subject': name_to_dict(cert.subject),
        'issuer': name_to_dict(cert.issuer),
        'serial_number': hex(cert.serial_number),
        'not_valid_before': cert.not_valid_before_utc.isoformat(),
        'not_valid_after': cert.not_valid_after_utc.isoformat(),
        'days_until_expiry': days_until_expiry,
        'is_expired': is_expired,
        'is_self_signed': is_self_signed,
        'san': san_list,
    }


def check_cert_expiry(cert_path: str, warn_days: int = 30) -> Tuple[str, int]:
    """
    Check certificate expiry status.

    Args:
        cert_path: Path to the certificate file
        warn_days: Days before expiry to consider "expiring soon"

    Returns:
        Tuple of (status, days_remaining)
        status is one of: 'valid', 'expiring', 'expired', 'error'
    """
    try:
        info = get_cert_info(cert_path)
        days = info['days_until_expiry']

        if info['is_expired']:
            return 'expired', days
        elif days <= warn_days:
            return 'expiring', days
        else:
            return 'valid', days

    except CertificateError:
        return 'error', 0


def ensure_certificate(
    cert_path: str,
    key_path: str,
    hostname: str = 'localhost',
    days: int = 365,
    regenerate: bool = False,
    renew_days: int = 30
) -> Tuple[bool, str]:
    """
    Ensure a valid certificate exists, generating one if needed.

    Args:
        cert_path: Path to the certificate file
        key_path: Path to the private key file
        hostname: Hostname for certificate generation
        days: Certificate validity in days
        regenerate: Force regeneration even if valid
        renew_days: Days before expiry to trigger renewal

    Returns:
        Tuple of (generated_new, message)
        generated_new is True if a new cert was generated
    """
    # Check if certificate exists and is valid
    if not regenerate and os.path.exists(cert_path) and os.path.exists(key_path):
        is_valid, error = validate_certificate(cert_path, key_path)

        if is_valid:
            # Check expiry
            status, days_remaining = check_cert_expiry(cert_path, renew_days)

            if status == 'valid':
                return False, f"Certificate valid for {days_remaining} more days"
            elif status == 'expiring':
                # Renew expiring certificate
                pass
            elif status == 'expired':
                # Need to regenerate
                pass
        # Certificate exists but invalid or expiring - regenerate

    # Generate new certificate
    try:
        generate_self_signed_cert(
            hostname=hostname,
            days=days,
            cert_path=cert_path,
            key_path=key_path
        )
        return True, f"Generated new self-signed certificate for {hostname}"

    except CertificateError as e:
        raise CertificateError(f"Failed to ensure certificate: {e}")


def save_uploaded_certificate(
    cert_data: bytes,
    key_data: bytes,
    cert_path: str,
    key_path: str
) -> Tuple[bool, str]:
    """
    Save uploaded certificate and key files after validation.

    Args:
        cert_data: PEM-encoded certificate data
        key_data: PEM-encoded private key data
        cert_path: Path to save certificate
        key_path: Path to save private key

    Returns:
        Tuple of (success, error_message)
    """
    check_cryptography_available()

    try:
        # Validate certificate
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())

        # Validate key
        private_key = serialization.load_pem_private_key(
            key_data,
            password=None,
            backend=default_backend()
        )

        # Verify key matches certificate
        cert_public = cert.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo
        )
        key_public = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo
        )

        if cert_public != key_public:
            return False, "Certificate and private key do not match"

        # Check expiry
        now = datetime.now(timezone.utc)
        if cert.not_valid_after_utc < now:
            return False, "Certificate has already expired"

        # Create directories
        cert_dir = os.path.dirname(cert_path)
        if cert_dir:
            os.makedirs(cert_dir, mode=0o755, exist_ok=True)

        key_dir = os.path.dirname(key_path)
        if key_dir:
            os.makedirs(key_dir, mode=0o700, exist_ok=True)

        # Save files
        with open(key_path, 'wb') as f:
            f.write(key_data)
        os.chmod(key_path, 0o600)

        with open(cert_path, 'wb') as f:
            f.write(cert_data)
        os.chmod(cert_path, 0o644)

        return True, ""

    except Exception as e:
        return False, f"Failed to save certificate: {e}"
