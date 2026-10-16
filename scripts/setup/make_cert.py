"""Self-signed certificate for demoing on phones: browsers only allow the camera and GPS on
localhost or HTTPS, so the app and the API are served over HTTPS on the laptop's LAN address.

  python scripts/setup/make_cert.py            -> certs/key.pem, certs/cert.pem (localhost + every local IPv4)

Then start with  powershell -ExecutionPolicy Bypass -File scripts\\start.ps1 -Https
and on the phone open https://<laptop-ip>:8000/health once (accept the warning), then https://<laptop-ip>:5173.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
CERTS = ROOT / "certs"


def local_ips() -> list[str]:
    ips = {"127.0.0.1"}
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except socket.gaierror:
        pass
    try:  # the address used to reach the LAN, which gethostbyname_ex can miss
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips)


def main() -> None:
    CERTS.mkdir(exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ips = local_ips()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Vindex demo"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SYNAPSE 26")])
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    (CERTS / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    (CERTS / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print("wrote certs/key.pem and certs/cert.pem for localhost,", ", ".join(ips))


if __name__ == "__main__":
    main()
