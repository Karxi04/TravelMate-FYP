from firebase_service import get_db
from utils import doc_to_dict
from google.api_core.exceptions import AlreadyExists, FailedPrecondition, NotFound


def _public_projection_changed(collection_name, document_id, source):
    if collection_name not in {'tourism_packages', 'promotional_campaigns', 'feedback'}:
        return
    from services.public_content_projection import source_changed
    source_changed(collection_name, document_id, source)


def _revoke_public_projection(collection_name, document_id):
    if collection_name not in {'tourism_packages', 'promotional_campaigns', 'feedback'}:
        return
    from services.public_content_projection import revoke_projection
    revoke_projection(collection_name, document_id)


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
    if documentId:
        _revoke_public_projection(collectionName, documentId)
    ref.set(data, merge=merge)
    result = {"id": ref.id, **data}
    _public_projection_changed(collectionName, ref.id, result)
    return result


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


def transactPreferenceLearning(uid, transform):
    """Commit the adaptive state and its audit event together, retrying stale reads."""
    from google.cloud import firestore
    db = get_db()
    profile = db.collection('learned_preference_profiles').document(uid)

    @firestore.transactional
    def commit(transaction):
        snapshot = profile.get(transaction=transaction)
        current = snapshot.to_dict() if snapshot.exists else None
        if current and (current.get('travellerId', uid) != uid or current.get('userId',uid) != uid):
            raise ValueError('Preference learning profile is unavailable.')
        updated, event, changed = transform(current)
        if event is not None:
            transaction.set(profile, updated)
            audit = db.collection('recommendation_feedback_events').document(event['feedbackEventId'])
            transaction.create(audit, event)
        return updated, event, changed

    return commit(db.transaction())


def updateRecord(collectionName, documentId, data, expected=None):
    """Exact sequence-diagram name for Firestore update."""
    if collectionName == 'feedback' and expected is not None:
        from services.review_service import commit_feedback
        return commit_feedback(documentId, expected, data)
    ref = get_db().collection(collectionName).document(str(documentId))
    snap = ref.get()
    if not snap.exists:
        return None
    option = None
    if expected is not None:
        from services.review_service import ReviewConflict
        if {"id": snap.id, **(snap.to_dict() or {})} != expected:
            raise ReviewConflict('This record changed. Refresh and try again.')
        option = get_db().write_option(last_update_time=snap.update_time)
    _revoke_public_projection(collectionName, documentId)
    if option is None:
        ref.set(data, merge=True)
    else:
        try:
            ref.update(data, option=option)
        except (FailedPrecondition, NotFound) as error:
            raise ReviewConflict('This record changed. Refresh and try again.') from error
    result = retrieveRecord(collectionName, documentId)
    _public_projection_changed(collectionName, documentId, result)
    return result


def commitPackageFulfillment(document_id, expected, patch):
    """CAS a package order and its owned Trip mirror in one transaction."""
    from google.cloud import firestore
    from services.review_service import ReviewConflict
    db = get_db()
    source = db.collection('checkout_orders').document(document_id)

    @firestore.transactional
    def commit(transaction):
        snap = source.get(transaction=transaction)
        current = {'id': snap.id, **(snap.to_dict() or {})} if snap.exists else None
        if current != expected:
            raise ReviewConflict('Booking changed. Refresh and try again.')
        trip_id = current.get('fulfilledTripId')
        trip_ref = None
        if trip_id:
            trip_ref = db.collection('itineraries').document(trip_id)
            trip_snap = trip_ref.get(transaction=transaction)
            trip = trip_snap.to_dict() if trip_snap.exists else None
            if (not trip or trip.get('travellerId') != current.get('travellerId') or
                    trip.get('checkoutOrderId') != document_id or
                    trip.get('operatorId') != current.get('operatorId')):
                raise ReviewConflict('Linked Package Trip is unavailable or inconsistent.')
        elif patch.get('fulfillmentStatus') == 'trip_ready':
            raise ReviewConflict('Recover the paid Package Trip before confirming arrangements.')
        if patch:
            transaction.update(source, patch)
        if trip_ref is not None:
            updated = {**current, **patch}
            mirror = {key: updated[key] for key in ('fulfillmentStatus', 'supplierReservationStatus', 'fulfillmentRecord')
                      if key in updated}
            if patch:
                mirror['updatedAt'] = patch['updatedAt']
            transaction.update(trip_ref, mirror)
        return {**current, **patch}

    return commit(db.transaction())


def transactPackingChecklist(trip_id, uid, transform):
    """Recheck Trip/Checklist ownership and serialize edits without writing Trips."""
    from google.cloud import firestore
    from google.api_core.exceptions import Aborted, DeadlineExceeded
    from random import uniform
    from time import sleep
    from services.packing_checklist_service import PackingError, checklist_id
    db = get_db()
    checklist_ref = db.collection('packing_checklists').document(checklist_id(uid, trip_id))
    trip_ref = db.collection('itineraries').document(trip_id)
    preferences_ref = db.collection('travel_preferences').document(uid)

    @firestore.transactional
    def commit(transaction):
        trip_snap = trip_ref.get(transaction=transaction)
        trip = trip_snap.to_dict() if trip_snap.exists else None
        if not trip or trip.get('travellerId') != uid:
            raise PackingError('Trip not found.', 404)
        snapshot = checklist_ref.get(transaction=transaction)
        current = {'id': snapshot.id, **(snapshot.to_dict() or {})} if snapshot.exists else None
        if current and (current.get('travellerId') != uid or current.get('tripId') != trip_id):
            raise PackingError('Checklist not found.', 404)
        pref_snap = preferences_ref.get(transaction=transaction)
        preferences = pref_snap.to_dict() if pref_snap.exists else None
        if preferences and preferences.get('travellerId', uid) != uid:
            preferences = None
        updated, result = transform(current, trip, preferences)
        if updated is not None and updated != current:
            transaction.set(checklist_ref, {k: v for k, v in updated.items() if k != 'id'})
        return result

    for attempt in range(2):
        try:
            return commit(db.transaction(max_attempts=3))
        except (Aborted, DeadlineExceeded, ValueError) as error:
            # The SDK wraps exhausted Aborted retries in ValueError.
            if isinstance(error, ValueError) and not isinstance(error.__cause__, (Aborted, DeadlineExceeded)):
                raise
            if attempt:
                raise
            # A new transaction rechecks ownership and revision after lock timeout.
            # Even an ambiguous commit cannot repeat an edit at the same revision.
            sleep(uniform(0.1, 0.4))


def deleteRecord(collectionName, documentId, expected=None):
    """Exact sequence-diagram name for Firestore delete."""
    if collectionName == 'feedback' and expected is not None:
        from services.review_service import commit_feedback
        return commit_feedback(documentId, expected)
    ref = get_db().collection(collectionName).document(str(documentId))
    if not ref.get().exists:
        return False
    _revoke_public_projection(collectionName, documentId)
    ref.delete()
    _public_projection_changed(collectionName, documentId, None)
    return True
