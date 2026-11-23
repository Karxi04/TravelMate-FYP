"""Owner-run initial Administrator provisioning; existing account roles are immutable."""
import argparse
from dotenv import load_dotenv
from google.api_core.exceptions import AlreadyExists
from firebase_service import init_firebase, get_db
from firebase_admin import auth
from utils import utc_now_iso


def provision_admin(email, password, name='TravelMate Administrator'):
    try:
        user = auth.get_user_by_email(email)
    except auth.UserNotFoundError:
        user = auth.create_user(email=email, password=password, email_verified=True)
    ref = get_db().collection('users').document(user.uid)
    snapshot = ref.get()
    if snapshot.exists:
        if str((snapshot.to_dict() or {}).get('role') or '').strip().lower() not in {'admin', 'administrator'}:
            raise ValueError('An existing account cannot be converted to Administrator.')
        return  # Preserve the existing role, account status and history exactly.
    now = utc_now_iso()
    try:
        ref.create({'uid': user.uid, 'email': email, 'name': name, 'role': 'admin',
                    'status': 'active', 'createdAt': now, 'updatedAt': now})
    except AlreadyExists as error:
        raise ValueError('The account was provisioned concurrently. No role changes were applied.') from error


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', required=True)
    parser.add_argument('--password', required=True)
    parser.add_argument('--name', default='TravelMate Administrator')
    args = parser.parse_args()
    init_firebase()
    provision_admin(args.email, args.password, args.name)
    print('Administrator profile is provisioned. Existing account settings were preserved.')


if __name__ == '__main__':
    main()
