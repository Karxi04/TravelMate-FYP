from firebase_service import get_db
from utils import doc_to_dict
from google.api_core.exceptions import AlreadyExists


def retrieveRecord(collectionName, documentId=None, filters=None, limit=None):
    """Exact sequence-diagram name for Firestore retrieval."""
    collection = get_db().collection(collectionName)
    if documentId:
        snap = collection.document(str(documentId)).get()
        return ({"id": snap.id, **(snap.to_dict() or {})}) if snap.exists else None
    query = collection
    for field, operator, value in (filters or []):
        query = query.where(field, operator, value)
    if limit:
        query = query.limit(limit)
    return [doc_to_dict(doc) for doc in query.stream()]


def storeRecord(collectionName, data, documentId=None, merge=False):
    """Exact sequence-diagram name for Firestore create/store."""
    ref = get_db().collection(collectionName).document(str(documentId)) if documentId else get_db().collection(collectionName).document()
    ref.set(data, merge=merge)
    return {"id": ref.id, **data}


def claimRecord(collectionName, documentId, data):
    """Atomically create an operation record, or return the existing claim.

    Firestore ``create`` is deliberately used instead of a read followed by
    ``set`` so concurrent duplicate requests cannot both win the claim. No
    provider/network work is performed while the claim is being created.
    """
    ref = get_db().collection(collectionName).document(str(documentId))
    try:
        ref.create(data)
        return {"id": ref.id, **data}, True
    except AlreadyExists:
        snap = ref.get()
        return ({"id": snap.id, **(snap.to_dict() or {})}, False)


def updateRecord(collectionName, documentId, data):
    """Exact sequence-diagram name for Firestore update."""
    ref = get_db().collection(collectionName).document(str(documentId))
    if not ref.get().exists:
        return None
    ref.set(data, merge=True)
    return retrieveRecord(collectionName, documentId)


def deleteRecord(collectionName, documentId):
    """Exact sequence-diagram name for Firestore delete."""
    ref = get_db().collection(collectionName).document(str(documentId))
    if not ref.get().exists:
        return False
    ref.delete()
    return True
