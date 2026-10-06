import os
import socket

import pytest
from pytest_socket import SocketBlockedError


def test_provider_credentials_are_disabled_by_default():
    assert os.environ['TRAVELMATE_TESTING'] == 'true'
    assert os.environ['FALLBACK_MODE'] == 'true'
    for key in (
        'FIREBASE_SERVICE_ACCOUNT',
        'FIREBASE_SERVICE_ACCOUNT_JSON',
        'GOOGLE_APPLICATION_CREDENTIALS',
        'SERPAPI_KEY',
        'LITEAPI_KEY',
        'STRIPE_SECRET_KEY',
        'GEMINI_API_KEY',
    ):
        assert os.environ[key] == ''


def test_unmocked_firestore_access_fails_fast():
    from sequence_contract.firebase_firestore import retrieveRecord

    with pytest.raises(AssertionError, match='Live Firebase/provider access'):
        retrieveRecord('must_not_reach_live_firestore')


def test_network_sockets_are_disabled_by_default():
    with pytest.warns(UserWarning, match='tried to use socket.socket'):
        with pytest.raises(SocketBlockedError):
            socket.socket()
