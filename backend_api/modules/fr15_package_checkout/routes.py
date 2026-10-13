from flask import Blueprint, g, jsonify, request
from auth_utils import auth_required
from sequence_contract.firebase_firestore import claimRecord, retrieveRecord
from services.package_checkout_contract import create_package_attempt

bp = Blueprint('fr15_package_checkout', __name__, url_prefix='/api/fr15/package-checkout-attempts')

@bp.post('')
@auth_required(['traveller'])
def create_attempt():
    payload = request.get_json(silent=True) or {}
    package = retrieveRecord('tourism_packages', str(payload.get('packageId') or ''))
    trip_id = str(payload.get('intendedTripId') or '').strip()
    trip = retrieveRecord('itineraries', trip_id) if trip_id else None
    if trip_id and not trip:
        return jsonify({'ok': False, 'error': 'The intended trip was not found.'}), 404
    try:
        attempt, created = create_package_attempt(claimRecord, g.uid, package or {},
            retrieveRecord('users', (package or {}).get('operatorId')) or {},
            str(payload.get('idempotencyKey') or ''), trip, payload.get('quantity', 1))
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 409
    except Exception:
        return jsonify({'ok': False, 'error': 'Package checkout preparation is temporarily unavailable.'}), 503
    return jsonify({'ok': True, 'attempt': attempt, 'reused': not created})

@bp.get('/<attempt_id>')
@auth_required(['traveller'])
def get_attempt(attempt_id):
    attempt = retrieveRecord('package_checkout_attempts', attempt_id)
    if not attempt or attempt.get('travellerId') != g.uid:
        return jsonify({'ok': False, 'error': 'Package checkout attempt not found.'}), 404
    return jsonify({'ok': True, 'attempt': attempt})
