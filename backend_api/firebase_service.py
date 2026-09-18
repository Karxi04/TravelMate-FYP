import json
import os

import firebase_admin
from firebase_admin import credentials, firestore


def init_firebase():
    if firebase_admin._apps:
        return firebase_admin.get_app()

    service_account_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', '').strip()
    if service_account_json:
        info = json.loads(service_account_json)
        return firebase_admin.initialize_app(credentials.Certificate(info))

    service_account = os.getenv('FIREBASE_SERVICE_ACCOUNT', 'serviceAccountKey.json')
    if service_account:
        if not os.path.isabs(service_account):
            candidate = os.path.join(os.path.dirname(__file__), service_account)
            if os.path.exists(candidate):
                service_account = candidate
        if os.path.exists(service_account):
            return firebase_admin.initialize_app(credentials.Certificate(service_account))

    # Supports Application Default Credentials on supported cloud platforms.
    return firebase_admin.initialize_app()


def get_db():
    init_firebase()
    return firestore.client()
