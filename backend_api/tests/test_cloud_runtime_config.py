from pathlib import Path
import os
import subprocess
import sys

import pytest

from portal_security_config import backend_base_url


def test_cloud_portal_requires_a_public_https_backend():
    assert backend_base_url({"APP_ENV": "development"}) == "http://127.0.0.1:5000"
    assert backend_base_url({
        "APP_ENV": "production",
        "BACKEND_URL": "https://travelmate-api.example",
    }) == "https://travelmate-api.example"

    for unsafe_url in ("", "http://api.example", "https://localhost", "https://192.168.1.5"):
        with pytest.raises(RuntimeError):
            backend_base_url({"APP_ENV": "production", "BACKEND_URL": unsafe_url})


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
