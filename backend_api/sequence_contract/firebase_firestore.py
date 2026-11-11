from firebase_service import get_db
from utils import doc_to_dict
from google.api_core.exceptions import AlreadyExists, FailedPrecondition, NotFound


def _notify_committed(collection, document_id, record):
    if collection not in {'checkout_orders', 'payment_records'}:
        return
    # Delivery failure cannot roll back an already committed financial operation.
    try:
        from services.notification_delivery import capture_committed_order
        capture_committed_order({**(record or {}), 'id': document_id})
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Committed notification deferred to worker.')


def transactNotificationRecord(collection, document_id, transform):
    if collection not in {'notification_devices', 'notification_outbox', 'notification_deliveries', 'notification_worker_state'}:
        raise ValueError('Unsupported notification collection')
    from google.cloud import firestore
    db = get_db()
    ref = db.collection(collection).document(document_id)

    @firestore.transactional
    def commit(transaction):
        snap = ref.get(transaction=transaction)
        current = snap.to_dict() if snap.exists else None
        updated = transform(current)
        if updated is not None:
            transaction.set(ref, updated)
        return updated
    return commit(db.transaction())


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
        if not snap.exists:
            return None
        record = {"id": snap.id, **(snap.to_dict() or {})}
        return loadRecommendationSnapshot(record) if collectionName == 'recommendation_snapshots' else record
    query = collection
    for field, operator, value in (filters or []):
        query = query.where(field, operator, value)
    if limit:
        query = query.limit(limit)
    return [doc_to_dict(doc) for doc in query.stream()]


def loadRecommendationSnapshot(record):
    """Hydrate a selected list result after filtering and sorting its headers."""
    if 'recommendationPayloadFormat' not in record:
        return record
    from services.recommendation_snapshot_storage import load_snapshot
    ref = get_db().collection('recommendation_snapshots').document(record['id'])
    return load_snapshot(ref, record)


def storeRecord(collectionName, data, documentId=None, merge=False):
    """Exact sequence-diagram name for Firestore create/store."""
    db = get_db()
    collection = db.collection(collectionName)
    ref = collection.document(str(documentId)) if documentId else collection.document()
    if collectionName == 'recommendation_snapshots':
        from services.recommendation_snapshot_storage import write_snapshot
        write_snapshot(db, ref, data)
        return {"id": ref.id, **data}
    if documentId:
        _revoke_public_projection(collectionName, documentId)
    ref.set(data, merge=merge)
    result = {"id": ref.id, **data}
    _public_projection_changed(collectionName, ref.id, result)
    _notify_committed(collectionName, ref.id, result)
    return result


def claimRecord(collectionName, documentId, data):
    """Atomically create an operation record, or return the existing claim.

    Firestore ``create`` is deliberately used instead of a read followed by
    ``set`` so concurrent duplicate requests cannot both win the claim. No
    provider/network work is performed while the claim is being created.
    """
    db = get_db()
    ref = db.collection(collectionName).document(str(documentId))
    try:
        if collectionName == 'feedback':
            from services.review_service import stage_public_review, stage_review_decision
            batch = db.batch()
            batch.create(ref, data)
            projection = db.collection('public_destination_reviews').document(ref.id)
            stage_public_review(batch, projection, ref.id, data)
            stage_review_decision(batch, ref, data)
            batch.commit()
        else:
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
    _notify_committed(collectionName, documentId, result)
    return result


def commitPackageFulfillment(document_id, expected, patch, clarification_revision=None):
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
        if clarification_revision is not None:
            from services.booking_requirements import COLLECTION, assessment
            review = db.collection(COLLECTION).document(document_id).get(transaction=transaction)
            clarification = review.to_dict() if review.exists else None
            if (not clarification or clarification.get('revision')!=clarification_revision or assessment(current,clarification)['integrityError']):
                raise ReviewConflict('Purchased requirement clarification changed. Refresh before recording arrangements.')
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
        if trip_ref is not None and patch:
            updated = {**current, **patch}
            mirror = {key: updated[key] for key in ('fulfillmentStatus', 'supplierReservationStatus', 'fulfillmentRecord')
                      if key in updated}
            if patch:
                mirror['updatedAt'] = patch['updatedAt']
            transaction.update(trip_ref, mirror)
        return {**current, **patch}

    result = commit(db.transaction())
    if patch:
        _notify_committed('checkout_orders', document_id, result)
    return result


def commitRequirementClarification(document_id, actor, role, action, payload):
    """Serialize a separate clarification/decision against the unchanged purchase."""
    from google.cloud import firestore
    from services.booking_requirements import COLLECTION, transition
    from utils import utc_now_iso
    db = get_db()
    source = db.collection('checkout_orders').document(document_id)
    review = db.collection(COLLECTION).document(document_id)

    @firestore.transactional
    def commit(transaction):
        snap = source.get(transaction=transaction)
        current = review.get(transaction=transaction)
        if not snap.exists:raise ValueError('Booking not found.')
        order = {**(snap.to_dict() or {}),'id':snap.id}
        before = current.to_dict() if current.exists else None
        updated = transition(order,before,payload,actor,role,action,utc_now_iso())
        if updated != before:transaction.set(review,updated)
        return updated
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
