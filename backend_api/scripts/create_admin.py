import argparse
from dotenv import load_dotenv
load_dotenv()

from firebase_service import init_firebase, get_db
from firebase_admin import auth
from utils import utc_now_iso

parser = argparse.ArgumentParser()
parser.add_argument("--email", required=True)
parser.add_argument("--password", required=True)
parser.add_argument("--name", default="TravelMate Administrator")
args = parser.parse_args()

init_firebase()
try:
    user = auth.get_user_by_email(args.email)
except auth.UserNotFoundError:
    user = auth.create_user(email=args.email, password=args.password, email_verified=True)

get_db().collection("users").document(user.uid).set({
    "uid": user.uid,
    "email": args.email,
    "name": args.name,
    "role": "admin",
    "status": "active",
    "createdAt": utc_now_iso(),
    "updatedAt": utc_now_iso(),
}, merge=True)
print("Administrator ready:", user.uid, args.email)
