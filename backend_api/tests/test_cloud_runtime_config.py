from pathlib import Path
import os
import subprocess
import sys

import pytest

from portal_security_config import backend_base_url
from app import create_app
from services.local_lan import local_lan_networks, local_lan_origins


def test_cloud_portal_requires_a_public_https_backend():
    assert backend_base_url({"APP_ENV": "development"}) == "http://127.0.0.1:5000"
    assert backend_base_url({
        "APP_ENV": "production",
        "BACKEND_URL": "https://travelmate-api.example",
    }) == "https://travelmate-api.example"

    for unsafe_url in ("", "http://api.example", "https://localhost", "https://192.168.1.5"):
        with pytest.raises(RuntimeError):
            backend_base_url({"APP_ENV": "production", "BACKEND_URL": unsafe_url})


def test_local_lan_mode_requires_an_explicit_private_network():
    networks = local_lan_networks({
        "APP_ENV": "development",
        "LOCAL_LAN_DEMO": "true",
        "TRUSTED_LAN_CIDR": "192.168.10.0/24",
    })
    assert [str(network) for network in networks] == ["192.168.10.0/24"]
    assert local_lan_networks({"APP_ENV": "development"}) == ()
    with pytest.raises(RuntimeError):
        local_lan_networks({
            "APP_ENV": "production",
            "LOCAL_LAN_DEMO": "true",
            "TRUSTED_LAN_CIDR": "192.168.10.0/24",
        })


@pytest.mark.parametrize("subnets", [
    "192.168.100.0/24,0.0.0.0/0",
    "172.20.10.0/28,127.0.0.0/8",
    "192.168.100.0/24,",
    "192.168.100.0/24,fd00::/64",
])
def test_local_lan_rejects_invalid_or_non_private_networks(subnets):
    with pytest.raises(RuntimeError, match="TRUSTED_LAN_CIDR"):
        local_lan_networks({"LOCAL_LAN_DEMO": "true", "TRUSTED_LAN_CIDR": subnets})


def test_two_networks_share_one_signed_identity_and_keep_checkout_on_its_origin(
    monkeypatch, tmp_path,
):
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from modules.fr09_payment.routes import _checkout_return_url

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path = tmp_path / "isolated-test.pem"
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    home = "http://192.168.100.26:5000"
    hotspot = "http://172.20.10.5:5000"
    for name, value in {
        "APP_ENV": "development",
        "PORT": "5000",
        "LOCAL_LAN_DEMO": "true",
        "TRUSTED_LAN_CIDR": "192.168.100.0/24,172.20.10.0/28",
        "LOCAL_LAN_ORIGINS": f"{home},{hotspot}",
        "LOCAL_LAN_IDENTITY_KEY": str(key_path),
        "STRIPE_CHECKOUT_RETURN_ORIGIN": hotspot,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("app.init_firebase", lambda: None)
    app = create_app()
    client = app.test_client()
    nonce = "a0" * 32
    path = f"/api/health?lanChallenge={nonce}"

    for origin, address in [(home, "192.168.100.24"), (hotspot, "172.20.10.7")]:
        response = client.get(path, base_url=origin, environ_overrides={"REMOTE_ADDR": address})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        data = response.get_json()
        assert data["service"] == "TravelMate Backend API"
        key.public_key().verify(
            base64.b64decode(data["lanProof"]),
            f"travelmate-local-lan-v1\n{origin}\n{nonce}".encode("ascii"),
            padding.PKCS1v15(), hashes.SHA256(),
        )
        with app.test_request_context("/", base_url=origin, environ_overrides={"REMOTE_ADDR": address}):
            assert _checkout_return_url("success").startswith(f"{origin}/api/fr9/checkout/return/")
    assert client.get(path, base_url=home, environ_overrides={"REMOTE_ADDR": "192.168.101.24"}).status_code == 403
    assert client.get(path, base_url="http://192.168.100.99:5000").status_code == 404
    assert client.get("/api/health?lanChallenge=invalid", base_url=home).status_code == 400
    assert "lanProof" not in client.get("/api/health", base_url=home).get_json()
    with app.test_request_context("/", base_url="http://192.168.100.99:5000",
                                  environ_overrides={"REMOTE_ADDR": "192.168.100.24"}):
        with pytest.raises(RuntimeError, match="approved"):
            _checkout_return_url("cancel")
    with app.test_request_context("/", base_url="http://127.0.0.1:5000",
                                  environ_overrides={"REMOTE_ADDR": "127.0.0.1"}):
        assert _checkout_return_url("cancel").startswith(hotspot)


def test_unapproved_lan_origins_and_cloud_proof_are_rejected(client):
    env = {"LOCAL_LAN_DEMO": "true", "TRUSTED_LAN_CIDR": "192.168.100.0/24"}
    networks = local_lan_networks(env)
    for wrong in ["http://127.0.0.1:5000", "http://192.168.100.50:80",
                  "https://192.168.100.50:5000", "http://192.168.100.50:5000?code=x"]:
        with pytest.raises(RuntimeError, match="LOCAL_LAN_ORIGINS"):
            local_lan_origins(networks, {**env, "LOCAL_LAN_ORIGINS": f"http://192.168.100.26:5000,{wrong}"})
    assert client.get("/api/health?lanChallenge=" + "ab" * 32).status_code == 404


def test_cloud_run_files_use_gunicorn_without_secrets():
    root = Path(__file__).resolve().parents[2]
    for portal in ("operator_website", "admin_website"):
        dockerfile = (root / portal / "Dockerfile").read_text(encoding="utf-8")
        requirements = (root / portal / "requirements.txt").read_text(encoding="utf-8")
        assert "gunicorn 'app:app'" in dockerfile
        assert "gunicorn>=23,<24" in requirements

    cloudbuild = (root / "cloudbuild.yaml").read_text(encoding="utf-8")
    assert "travelmate-api" in cloudbuild
    assert "travelmate-operator" in cloudbuild
    assert "travelmate-admin" in cloudbuild
    assert "${_IMAGE_TAG}" in cloudbuild
    assert "$COMMIT_SHA" not in cloudbuild

    for name in ("backend.env.example", "operator.env.example", "admin.env.example"):
        template = (root / "deploy" / "cloudrun" / name).read_text(encoding="utf-8")
        assert "127.0.0.1" not in template
        assert "10.0.2.2" not in template
        assert "SECRET_MANAGER:" not in template

    for service, health_path in (
        ("travelmate-api", "/api/health"),
        ("travelmate-operator", "/health"),
        ("travelmate-admin", "/health"),
    ):
        template = (root / "deploy" / "cloudrun" / "services" / f"{service}.yaml.template").read_text(encoding="utf-8")
        assert "containerPort: 8080" in template
        assert f"path: {health_path}" in template
        assert "autoscaling.knative.dev/minScale: \"0\"" in template


def test_portal_health_endpoints_start_without_cloud_configuration():
    root = Path(__file__).resolve().parents[2]
    script = "from app import app; response = app.test_client().get('/health'); assert response.status_code == 200"
    for portal in ("operator_website", "admin_website"):
        environment = {**os.environ, "APP_ENV": "development"}
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=root / portal,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
