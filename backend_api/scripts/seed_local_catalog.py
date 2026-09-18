from dotenv import load_dotenv
load_dotenv()

from firebase_service import init_firebase, get_db
from utils import utc_now_iso
from services.local_catalog import DESTINATIONS

init_firebase()
db = get_db()

for destination in DESTINATIONS:
    doc_id = destination["place_id"]
    db.collection("destination_cache").document(doc_id).set({
        **destination,
        "destinationId": doc_id,
        "cachedAt": utc_now_iso(),
    }, merge=True)

print(f"Seeded {len(DESTINATIONS)} local destination records into destination_cache.")
