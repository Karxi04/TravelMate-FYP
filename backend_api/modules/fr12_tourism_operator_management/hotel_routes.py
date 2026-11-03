from flask import g, jsonify, request
from auth_utils import auth_required
from services.operator_hotel_service import HotelDataError, hotel_detail, search_hotels
from .routes import bp


def _error(error):
    response = jsonify(ok=False, error=str(error), code=error.code)
    if error.status == 429:
        response.headers['Retry-After'] = '60'
    return response, error.status


@bp.get('/hotels/search')
@auth_required(['operator'])
def search_operator_hotels():
    if g.role != 'operator':
        return jsonify(ok=False, error='Verified Tourism Operator access is required.'), 403
    try:
        return jsonify(search_hotels(request.args))
    except HotelDataError as error:
        return _error(error)


@bp.get('/hotels/<hotel_id>')
@auth_required(['operator'])
def operator_hotel_detail(hotel_id):
    if g.role != 'operator':
        return jsonify(ok=False, error='Verified Tourism Operator access is required.'), 403
    try:
        return jsonify(ok=True, hotel=hotel_detail(hotel_id), availabilityChecked=False)
    except HotelDataError as error:
        return _error(error)
