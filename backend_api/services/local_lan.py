import ipaddress
import os
from urllib.parse import urlsplit


_PRIVATE_NETWORKS = tuple(map(ipaddress.ip_network, (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
)))


def local_lan_networks(environ=None):
    source = os.environ if environ is None else environ
    if source.get("LOCAL_LAN_DEMO", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return ()
    if source.get("APP_ENV", "development").strip().lower() not in {"development", "dev", "local", "demo"}:
        raise RuntimeError("LOCAL_LAN_DEMO is allowed only in an explicit local environment")
    try:
        networks = tuple(
            ipaddress.IPv4Network(entry.strip(), strict=False)
            for entry in source.get("TRUSTED_LAN_CIDR", "").split(",")
        )
    except ValueError as exc:
        raise RuntimeError("LOCAL_LAN_DEMO requires valid TRUSTED_LAN_CIDR entries") from exc
    if any(not any(network.subnet_of(private) for private in _PRIVATE_NETWORKS) for network in networks):
        raise RuntimeError("TRUSTED_LAN_CIDR must contain only private IPv4 networks")
    return networks


def is_lan_address(host, networks):
    try:
        address = ipaddress.IPv4Address(host)
    except (ValueError, TypeError):
        return False
    return str(address) not in {"10.0.2.2", "10.0.3.2"} and any(
        address in network for network in networks
    )


def local_lan_origins(networks, environ=None):
    source = os.environ if environ is None else environ
    raw = source.get("LOCAL_LAN_ORIGINS", "").strip()
    if not networks or not raw:
        return ()
    origins = tuple(entry.strip().rstrip("/") for entry in raw.split(","))
    try:
        if len(set(origins)) != 2 or len(origins) != 2:
            raise ValueError
        for origin in origins:
            parsed = urlsplit(origin)
            if (not is_lan_address(parsed.hostname, networks) or
                    parsed.port != int(source.get("PORT", "5000")) or
                    origin != f"http://{parsed.hostname}:{parsed.port}"):
                raise ValueError
    except ValueError as exc:
        raise RuntimeError("LOCAL_LAN_ORIGINS requires two trusted private HTTP origins on PORT") from exc
    return origins


def load_lan_signer(path):
    from pathlib import Path
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    try:
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("LOCAL_LAN_IDENTITY_KEY must reference a readable private PEM key") from exc
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise RuntimeError("LOCAL_LAN_IDENTITY_KEY requires an RSA key of at least 2048 bits")

    def sign(origin, nonce):
        return key.sign(
            f"travelmate-local-lan-v1\n{origin}\n{nonce}".encode("ascii"),
            padding.PKCS1v15(), hashes.SHA256(),
        )

    return sign
