import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from app import _truthy, create_app
from portal_security_config import configure_portal_app, env_flag, resolve_secret


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_config_status_requires_admin(client):
    response = client.get('/api/config-status')
    assert response.status_code == 401


def test_config_status_is_minimal_and_stripe_accurate(client, mock_admin_auth):
    with patch.dict(os.environ, {
        'STRIPE_SECRET_KEY': 'pk_test_publishable_only',
        'LITEAPI_KEY': '',
        'FALLBACK_MODE': 'true',
    }):
        response = client.get(
            '/api/config-status',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
    assert response.status_code == 200
    assert response.get_json() == {
        'ok': True,
        'paymentMode': 'simulation',
        'hotelMode': 'fallback',
    }
    serialized = response.get_data(as_text=True)
    for forbidden in ('SERPAPI_KEY', 'STRIPE_SECRET_KEY', 'firebaseServiceAccount', 'providers'):
        assert forbidden not in serialized


def test_config_status_reports_stripe_test_mode(client, mock_admin_auth):
    with patch.dict(os.environ, {
        'STRIPE_SECRET_KEY': 'sk_test_example_not_real',
        'LITEAPI_KEY': 'liteapi-test-placeholder',
        'FALLBACK_MODE': 'true',
    }):
        response = client.get(
            '/api/config-status',
            headers={'Authorization': 'Bearer valid_test_token'},
        )
    assert response.status_code == 200
    assert response.get_json() == {
        'ok': True,
        'paymentMode': 'sandbox',
        'hotelMode': 'live',
    }


def test_cors_allows_only_configured_browser_origin():
    with patch.dict(os.environ, {
        'CORS_ALLOWED_ORIGINS': 'https://operator.example,https://admin.example',
    }), patch('app.init_firebase'):
        app = create_app()
    client = app.test_client()
    allowed = client.get('/api/health', headers={'Origin': 'https://operator.example'})
    denied = client.get('/api/health', headers={'Origin': 'https://evil.example'})
    assert allowed.headers.get('Access-Control-Allow-Origin') == 'https://operator.example'
    assert denied.headers.get('Access-Control-Allow-Origin') is None


def test_cors_rejects_wildcard_configuration():
    with patch.dict(os.environ, {'CORS_ALLOWED_ORIGINS': '*'}):
        with pytest.raises(RuntimeError, match='wildcard is not allowed'):
            create_app()


def test_production_portal_requires_strong_secret():
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        resolve_secret({'APP_ENV': 'production', 'SECRET_KEY': ''}, 'admin')
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        resolve_secret(
            {'APP_ENV': 'production', 'SECRET_KEY': 'change-this-development-secret'},
            'operator',
        )


def test_portal_cookie_defaults_are_secure_in_production():
    app = Flask('portal-config-test')
    configure_portal_app(
        app,
        'travelmate_test_session',
        'test',
        {
            'APP_ENV': 'production',
            'SECRET_KEY': 'a-strong-random-deployment-secret-value',
        },
    )
    assert app.config['SESSION_COOKIE_HTTPONLY'] is True
    assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
    assert app.config['SESSION_COOKIE_SECURE'] is True


def test_debug_is_disabled_by_default():
    with patch.dict(os.environ, {}, clear=True):
        assert _truthy('FLASK_DEBUG') is False
        assert env_flag('FLASK_DEBUG') is False


def test_feedback_rules_allowlist_expected_fields_and_reject_unknown_fields():
    rules = (PROJECT_ROOT / 'firebase' / 'firestore.rules').read_text(encoding='utf-8')
    match = re.search(
        r"request\.resource\.data\.keys\(\)\.hasOnly\(\[(.*?)\]\)",
        rules,
        re.DOTALL,
    )
    assert match is not None
    allowed_fields = set(re.findall(r"'([^']+)'", match.group(1)))
    assert allowed_fields == {
        'destinationId',
        'destinationName',
        'destinationAddress',
        'rating',
        'comment',
        'travellerId',
        'travellerName',
        'feedbackStatus',
        'moderationStatus',
        'submittedAt',
        'updatedAt',
    }
    valid_payload_fields = {
        'destinationId',
        'destinationName',
        'rating',
        'comment',
        'travellerId',
        'travellerName',
        'feedbackStatus',
        'moderationStatus',
        'submittedAt',
    }
    assert valid_payload_fields <= allowed_fields
    assert not ({'adminRole'} <= allowed_fields)
    assert not ({'operatorId'} <= allowed_fields)
    assert "request.resource.data.diff(resource.data).affectedKeys().hasOnly([" in rules


def test_firebase_project_alias_is_valid_and_unchanged():
    config = json.loads((PROJECT_ROOT / '.firebaserc').read_text(encoding='utf-8'))
    assert config['projects'] == {'default': 'travelmate2-30a8a'}
