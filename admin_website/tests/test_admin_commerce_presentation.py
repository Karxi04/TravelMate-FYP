import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DIR = ROOT / "admin_website"
OP_DIR = ROOT / "operator_website"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
while str(OP_DIR) in sys.path:
    sys.path.remove(str(OP_DIR))
if str(ADMIN_DIR) not in sys.path:
    sys.path.insert(0, str(ADMIN_DIR))

for k in list(sys.modules.keys()):
    if k == "modules" or k.startswith("modules."):
        del sys.modules[k]

from admin_website.app import app


@pytest.fixture
def auth_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["id_token"] = "valid_admin_token"
            sess["portal_role"] = "admin"
            sess["admin_id"] = "admin_test_1"
        yield client


def _patch_view_api(view_name, mock_fn):
    fn_globals = app.view_functions[view_name].__globals__
    return patch.dict(fn_globals, {"call_api": mock_fn})


@pytest.mark.parametrize('status,label', [('operator_attested','Arrangements Recorded (Operator)'),
    ('declined','Unable to Fulfil'),('not_required','Not Required')])
def test_supplier_attestation_disclosure_is_not_overwritten(auth_client,status,label):
    response=MagicMock(ok=True)
    response.json.return_value={'ok':True,'items':[{'id':'synthetic','bookingType':'package',
        'supplierReservationStatus':status,'supplierReservationDisclosure':'Operator evidence, not API verified',
        'amount':100,'currency':'MYR','fulfillmentStatus':'trip_ready'}]}
    with _patch_view_api('admin_fr13.bookings',MagicMock(return_value=response)):
        page=auth_client.get('/admin/bookings?type=package')
    html=page.get_data(as_text=True)
    assert page.status_code == 200 and label in html
    assert 'Not Created (Manual)' not in html


@pytest.mark.parametrize('page',['dashboard','users','packages','campaigns','feedback','destinations','activities','bookings','payments','reports'])
def test_f4b_outage_is_visible_without_private_exception(auth_client,page):
    import requests
    with patch('api_client.requests.request',side_effect=requests.Timeout('private-sentinel')):
        response=auth_client.get('/admin/'+page)
    assert response.status_code == 200
    html=response.get_data(as_text=True)
    assert 'temporarily unavailable' in html and 'private-sentinel' not in html
    if page == 'dashboard':assert 'Queue Clear' not in html


def test_f4b_non_admin_session_is_rejected_before_proxy(auth_client):
    with auth_client.session_transaction() as sess:sess['portal_role']='operator'
    api=MagicMock()
    with _patch_view_api('admin_fr13.users',api):
        response=auth_client.get('/admin/users')
    assert response.status_code == 302
    api.assert_not_called()


def test_f4b_expired_token_clears_session_and_redirects(auth_client):
    import requests
    failure=requests.Response();failure.status_code=401
    failure._content=b'{"ok":false,"error":"expired"}'
    with patch('api_client.requests.request',return_value=failure):
        response=auth_client.get('/admin/users')
    assert response.status_code == 302
    with auth_client.session_transaction() as sess:assert not sess.get('id_token')


def test_f4b_csrf_blocks_mutation_before_proxy(auth_client):
    previous=app.config['WTF_CSRF_ENABLED'];app.config['WTF_CSRF_ENABLED']=True
    try:
        with patch('api_client.requests.request') as api:
            response=auth_client.post('/admin/packages/p/review',data={'decision':'approved'})
        assert response.status_code == 400
        api.assert_not_called()
    finally:app.config['WTF_CSRF_ENABLED']=previous


def test_f4b_partial_dashboard_is_disclosed(auth_client):
    import requests
    response=requests.Response();response.status_code=200
    response._content=b'{"ok":true,"report":{"dataLimited":true,"counts":{"users":500}}}'
    with patch('api_client.requests.request',return_value=response):
        page=auth_client.get('/admin/dashboard')
    assert page.status_code == 200 and b'Partial results' in page.data and b'500' in page.data


def test_f4b_unknown_payment_is_not_free_or_live(auth_client):
    response=MagicMock(ok=True)
    response.json.return_value={'ok':True,'items':[{'id':'unknown','amount':None,'currency':'UNKNOWN'}]}
    with _patch_view_api('admin_fr13.payments',MagicMock(return_value=response)):
        page=auth_client.get('/admin/payments')
    html=page.get_data(as_text=True)
    assert 'Unavailable' in html and '>Environment<' not in html and '>Live</span>' not in html


def test_admin_payments_renders_filters_and_test_mode_badge(auth_client):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "items": [
            {
                "id": "ord-test-1",
                "transactionReference": "tx-12345",
                "productType": "package",
                "productTitle": "Penang Explorer",
                "travellerId": "tr-100",
                "paymentStatus": "paid",
                "amount": 250.00,
                "currency": "MYR",
                "testMode": True,
                "createdAt": "2026-10-24T12:00:00Z",
            }
        ]
    }
    mock_call = MagicMock(return_value=mock_resp)
    with _patch_view_api("admin_fr13.payments", mock_call):
        res = auth_client.get("/admin/payments?startDate=2026-10-20&endDate=2026-10-25")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert 'name="startDate"' in html
        assert 'name="endDate"' in html
        assert "Stripe Test Mode" in html
        assert "Penang Explorer" in html
        assert "250.00" in html

        mock_call.assert_called_once()
        _, kwargs = mock_call.call_args
        assert kwargs.get("params", {}).get("startDate") == "2026-10-20"
        assert kwargs.get("params", {}).get("endDate") == "2026-10-25"


def test_admin_bookings_renders_package_tab_and_supplier_disclosure(auth_client):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "items": [
            {
                "id": "ord-pkg-99",
                "bookingReference": "ord-pkg-99",
                "bookingType": "package",
                "packageTitle": "Penang Heritage Tour",
                "packageId": "pkg-99",
                "operatorId": "op-penang",
                "travellerId": "tr-200",
                "paymentStatus": "paid",
                "fulfillmentStatus": "fulfillment_pending",
                "supplierReservationStatus": "not_created",
                "supplierReservationDisclosure": "Package Trip creation is platform-managed; no direct third-party supplier reservation has been booked.",
                "amount": 420.00,
                "currency": "MYR",
                "createdAt": "2026-10-24T14:00:00Z",
            }
        ]
    }
    with _patch_view_api("admin_fr13.bookings", MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/bookings?type=package")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Package Bookings (Platform)" in html
        assert "Penang Heritage Tour" in html
        assert "Reservation Not Created" in html
        assert "420.00" in html


def test_admin_bookings_hotel_tab_renders_hotel_details(auth_client):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ok": True,
        "items": [
            {
                "id": "hb-1",
                "bookingReference": "HTL-1234",
                "travellerId": "tr-300",
                "hotelName": "Eastern & Oriental",
                "roomType": "Deluxe Suite",
                "bookingStatus": "confirmed",
                "hotelCost": 550.00,
                "createdAt": "2026-10-24T15:00:00Z",
            }
        ]
    }
    with _patch_view_api("admin_fr13.bookings", MagicMock(return_value=mock_resp)):
        res = auth_client.get("/admin/bookings?type=hotel")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Eastern &amp; Oriental" in html or "Eastern & Oriental" in html
        assert "Deluxe Suite" in html
        assert "550.00" in html
