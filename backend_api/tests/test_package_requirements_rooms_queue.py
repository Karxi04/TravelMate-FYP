"""Snapshot, moderation and read-only room metadata regressions; no live services."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from services import operator_hotel_service as hotels
from services.package_checkout_contract import derive_required_services, fulfillment_readiness, prepare_package_snapshot
from services.package_service import normalise_package, package_submission_error, package_update_changes_reviewed_content
from services.public_content_projection import public_package, eligible_package
from test_operator_hotel_integration import raw_hotel, package, no_booking_mutations, AUTH


@pytest.mark.parametrize('status,expected', [('all', {'pending','submitted','approved','rejected','suspended'}),
    ('pending', {'pending','submitted'}), ('approved', {'approved'}), ('rejected', {'rejected'}),
    ('draft', set()), ('archived', set())])
def test_admin_queue_uses_current_lifecycle_not_historical_decision(client, mock_admin_auth, status, expected):
    records = [package(id=state, approvalStatus=state, reviewedAt='2026-01-01', reviewedBy='admin',
                       reviewComment='Previously approved') for state in
               ('draft','archived','pending','submitted','approved','rejected','suspended')]
    records.append(package(id='deleted', approvalStatus='approved', deletedAt='2026-01-02'))
    before = deepcopy(records)
    with patch('modules.fr13_administrator_management.routes._load', return_value=records), \
         patch('modules.fr13_administrator_management.routes._save') as save:
        result = client.get('/api/fr13/packages?status='+status, headers=AUTH)
        pending = client.get('/api/fr13/packages/pending', headers=AUTH)
    assert result.status_code == pending.status_code == 200
    assert {r['id'] for r in result.json['items']} == expected
    assert {r['id'] for r in pending.json['items']} == {'pending','submitted'}
    assert records == before
    save.assert_not_called()
    assert not eligible_package(records[1])


@pytest.mark.parametrize('changes', [{'approvalStatus':'draft'}, {'approvalStatus':'archived'},
                                  {'approvalStatus':'approved','deletedAt':'2026-01-02'}])
def test_direct_review_cannot_republish_hidden_lifecycle_and_detail_keeps_history(client, mock_admin_auth, changes):
    record = package(reviewComment='', reviewedBy='original-admin', **changes)
    before = deepcopy(record)
    with patch('modules.fr13_administrator_management.routes.retrieveRecord', return_value=record), \
         patch('modules.fr13_administrator_management.routes._save') as save, \
         patch('modules.fr13_administrator_management.routes._reconcile_moderation') as reconcile:
        response = client.post('/api/fr13/packages/p/review', headers=AUTH, json={'decision':'approved'})
        detail = client.get('/api/fr13/packages/p', headers=AUTH)
    assert response.status_code == 409
    assert detail.json['package']['reviewedBy'] == 'original-admin'
    assert record == before
    save.assert_not_called()
    reconcile.assert_not_called()


def snapshot(**changes):
    return {'inclusions': [], 'exclusions': [], 'accommodation': {}, 'transport': {}, **changes}


@pytest.mark.parametrize('data,required', [
    (snapshot(accommodationIncluded=True, accommodation={'accommodationName':'Homestay','roomType':'Entire house'}), {'accommodation'}),
    (snapshot(accommodationIncluded=False), set()),
    (snapshot(transportIncluded=True), {'transport'}),
    (snapshot(guideActivitiesIncluded=True), {'guideActivities'}),
    (snapshot(accommodationIncluded=True,transportIncluded=True,guideActivitiesIncluded=True), {'accommodation','transport','guideActivities'}),
    (snapshot(accommodationIncluded=False,transportIncluded=False,guideActivitiesIncluded=False), set()),
    (snapshot(inclusions=['Optional hotel suggestion','Self-guided free attraction','Public transport guidance']), set()),
    (snapshot(accommodationName='None'), set()),
    (snapshot(inclusions=['Reserved attraction tickets','Paid activity']), {'guideActivities'}),
    (snapshot(inclusions=['Homestay accommodation']), {'accommodation'}),
    (snapshot(inclusions=['Free airport shuttle']), {'transport'}),
    (snapshot(inclusions=['Free admission to public park']), set()),
    (snapshot(inclusions=['Licensed guide for walking tour']), {'guideActivities'}),
    (snapshot(inclusions=['Public transportation guidance'], transport={'transportTypes':['None']}), set()),
    (snapshot(inclusions=['Reserved attraction tickets'], exclusions=['Tour guide']), {'guideActivities'}),
    ({'inclusions': [], 'accommodationName':'Purchased Homestay', 'transportTypes':[]}, {'accommodation'}),
])
def test_requirement_states_and_authoritative_counts(data, required):
    before = deepcopy(data)
    req = derive_required_services(data)
    assert {key for key, meta in req.items() if meta['required']} == required
    assert not any(meta['uncertain'] for meta in req.values())
    readiness = fulfillment_readiness({}, req, {}, True)
    assert readiness['requiredCount'] == len(required) and readiness['completedCount'] == 0
    assert readiness['canMarkReady'] == (not required)
    assert data == before


def test_partial_legacy_evidence_is_component_specific_and_blocks_readiness():
    req = derive_required_services({'accommodationName':'Purchased Stay'})
    assert req['accommodation']['required'] and not req['accommodation']['uncertain']
    assert req['transport']['uncertain'] and req['guideActivities']['uncertain']
    readiness = fulfillment_readiness({}, req, {}, True)
    assert not readiness['canMarkReady'] and not readiness['requirementsReliable']
    assert any('Transportation:' in reason for reason in readiness['blockers'])


@pytest.mark.parametrize('data', [{}, {'inclusions':['Hotel included'], 'accommodationIncluded':False},
    snapshot(inclusions=['Private airport transfer'], exclusions=['Transport']),
    snapshot(accommodation={'accommodationName':'Selected Hotel','accommodationHotel':{'hotelId':'x'}})])
def test_ambiguous_or_conflicting_snapshot_never_ready(data):
    req = derive_required_services(data)
    assert any(meta['uncertain'] for meta in req.values())
    assert not fulfillment_readiness({}, req, {}, True)['canMarkReady']


def test_complete_attested_services_allow_readiness_but_payment_and_provider_still_gate():
    req = derive_required_services(snapshot(accommodationIncluded=True,transportIncluded=True,guideActivitiesIncluded=True))
    record = {'services': {key: {'reference':'ACTUAL-REF','providerName':'Actual fleet', 'status':'confirmed',
                               'provenance':'operator_attested','confirmedBy':'op','confirmedAt':'2026-11-08'} for key in req}}
    ready = fulfillment_readiness({}, req, record, True)
    assert ready['canMarkReady'] and ready['completedCount'] == ready['requiredCount'] == 3
    assert not fulfillment_readiness({},req,record,False)['canMarkReady']
    record['services']['transport']['providerName'] = ''
    assert not fulfillment_readiness({},req,record,True)['canMarkReady']


def room(**changes):
    return {'id':123,'roomName':'Studio King','description':'<p>Factual room</p>',
            'maxOccupancy':3,'maxAdults':2,'maxChildren':2,
            'bedTypes':[{'bedType':'King','quantity':1}], 'roomAmenities':[{'name':'Wi-Fi'}],
            'photos':[{'url':'https://images.example.test/room.jpg'}], 'privateKey':'not-public', **changes}


def test_operator_detail_exposes_safe_room_content_without_booking_calls(client,mock_operator_auth):
    with no_booking_mutations(), patch.object(hotels,'retrieveHotelContent',return_value={'data':raw_hotel(rooms=[room()])}) as detail:
        response = client.get('/api/fr12/hotels/lp_synthetic',headers=AUTH)
    assert response.status_code == 200 and response.json['availabilityChecked'] is False
    result = response.json['hotel']['rooms'][0]
    assert result['id'] == '123' and result['maxOccupancy'] == 3 and result['bedTypes'][0]['bedType'] == 'King'
    assert result['reservationStatus'] == 'not_created'
    assert 'privateKey' not in str(result)
    detail.assert_called_once_with('lp_synthetic')


def test_room_selection_save_reopen_projection_and_immutable_purchase(client, mock_operator_auth):
    payload = package(approvalStatus='draft', hotelSelection={'provider':'liteapi','hotelId':'lp_synthetic'},
                      roomSelection={'hotelId':'lp_synthetic','roomId':'123'}, accommodationIncluded=True,
                      transportIncluded=False,guideActivitiesIncluded=False,inclusions=[],roomType='Entire studio for two')
    with no_booking_mutations(), patch.object(hotels,'retrieveHotelContent',return_value={'data':raw_hotel(rooms=[room()])}) as detail, \
         patch('modules.fr12_tourism_operator_management.routes.retrieveRecord',return_value={}), \
         patch('modules.fr12_tourism_operator_management.routes.storeRecord',side_effect=lambda c,d:{'id':'new',**d}) as store:
        response = client.post('/api/fr12/packages', headers=AUTH,json=payload)
    assert response.status_code == 201
    detail.assert_called_once_with('lp_synthetic')
    saved = store.call_args.args[1]
    reopened = normalise_package(saved)
    assert reopened['accommodationRoom']['id'] == '123'
    assert reopened['roomType'] == 'Entire studio for two'
    assert 'rooms' not in reopened['accommodationHotel']
    assert 'privateKey' not in str(reopened) and 'roomSelection' not in reopened
    published = public_package({'id':'new',**saved,'approvalStatus':'approved'})
    assert published['accommodationRoom']['id'] == '123'
    purchased = prepare_package_snapshot({'id':'new',**saved,'approvalStatus':'approved'}, {'id':'op'})
    before = deepcopy(purchased)
    saved.update(accommodationIncluded=False,approvalStatus='archived',roomType='Changed later')
    assert purchased == before and derive_required_services(purchased)['accommodation']['required']
    assert purchased['accommodation']['accommodationRoom']['reservationStatus'] == 'not_created'
    assert fulfillment_readiness({},derive_required_services(purchased),{},True)['completedCount'] == 0


def test_detail_rooms_allowlist_unmapped_and_invalid_room_identity():
    with patch.object(hotels,'retrieveHotelContent',return_value={'data':raw_hotel(rooms=[room(),room(id=124,hotelId='other'),{}])}):
        hotel = hotels.hotel_detail('lp_synthetic')
        assert [r['id'] for r in hotel['rooms']] == ['123']
        assert hotel['rooms'][0]['description'] == 'Factual room'
        assert hotel['rooms'][0]['availabilityChecked'] is False
        with pytest.raises(hotels.HotelDataError):
            hotels.resolve_package_hotel({'hotelSelection':{'provider':'liteapi','hotelId':'lp_synthetic'},
                                          'roomSelection':{'hotelId':'other','roomId':'123'}})
    with patch.object(hotels,'retrieveHotelContent',return_value={'data':raw_hotel()}):
        assert hotels.hotel_detail('lp_synthetic')['rooms'] == []
        manual = hotels.resolve_package_hotel({'hotelSelection':{'provider':'liteapi','hotelId':'lp_synthetic'},'roomType':'Entire apartment'})
        assert manual['roomType'] == 'Entire apartment' and not manual.get('accommodationRoom')


def test_replacement_clear_and_unchanged_room_preservation():
    with patch.object(hotels,'retrieveHotelContent',return_value={'data':raw_hotel(rooms=[room()])}) as detail:
        saved = hotels.resolve_package_hotel({'hotelSelection':{'provider':'liteapi','hotelId':'lp_synthetic'},
                                             'roomSelection':{'hotelId':'lp_synthetic','roomId':'123'}})
        detail.reset_mock()
        assert not hotels.resolve_package_hotel({'title':'Edited'},saved).get('accommodationRoom')
        detail.assert_not_called()
        assert normalise_package({'title':'Edited'},saved)['accommodationRoom']['id'] == '123'
        assert hotels.resolve_package_hotel({'hotelSelection':None},saved)['accommodationRoom'] is None
        detail.return_value = {'data':raw_hotel(id='other')}
        replaced = hotels.resolve_package_hotel({'hotelSelection':{'provider':'liteapi','hotelId':'other'}},saved)
        assert replaced['accommodationRoom'] is None and replaced['roomType'] == ''


def test_inclusion_validation_and_no_inferred_legacy_migration():
    assert 'accommodationIncluded' not in normalise_package(package())
    assert 'true or false' in package_submission_error(package(accommodationIncluded='false'))
    assert 'accommodation promised' in package_submission_error(package(accommodationIncluded=True))
    assert 'Room Configuration' in package_submission_error(package(accommodationIncluded=True,accommodationName='Stay'))
    assert package_submission_error(package(accommodationIncluded=False)) is None
    assert package_submission_error(package(accommodationIncluded=True,accommodationName='House',roomType='Whole property')) is None
    purchased = prepare_package_snapshot(package(approvalStatus='approved'),{'id':'op'})
    assert any(m['uncertain'] for m in derive_required_services(purchased).values())
    assert package_update_changes_reviewed_content(package(),{'accommodationIncluded':False})
