import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DIR = ROOT / "admin_website"
OP_DIR = ROOT / "operator_website"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
while str(ADMIN_DIR) in sys.path:
    sys.path.remove(str(ADMIN_DIR))
if str(OP_DIR) not in sys.path:
    sys.path.insert(0, str(OP_DIR))

for k in list(sys.modules.keys()):
    if k == "modules" or k.startswith("modules."):
        del sys.modules[k]

from operator_website.app import app


@pytest.fixture
def auth_client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    if "request_rate_limiter" in app.extensions:
        app.extensions["request_rate_limiter"].reset()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["id_token"] = "valid_operator_token"
            sess["portal_role"] = "operator"
            sess["verification_status"] = "approved"
            sess["operator_id"] = "test_op_uid"
        yield c


SAMPLE_BOOKING = {
    "id": "ord-penang-fulfillment",
    "orderReference": "ord-penang-fulfillment",
    "quoteType": "package",
    "packageId": "pkg-penang-lux",
    "packageTitle": "Penang Luxury Island Getaway",
    "departureDate": "2027-05-10",
    "groupSize": 2,
    "adults": 2,
    "children": 0,
    "paymentStatus": "paid",
    "isPaid": True,
    "orderStatus": "paid",
    "fulfillmentStatus": "awaiting_operator_fulfillment",
    "supplierReservationStatus": "not_created",
    "amount": 2500.00,
    "groupTotal": 2500.00,
    "currency": "MYR",
    "testMode": True,
    "requiredServices": {
        "accommodation": {
            "required": True,
            "brochureName": "Shangri-La Rasa Sayang Resort",
            "brochureRoomType": "Deluxe Seaview",
            "brochureCategory": "Resort",
            "brochureNotes": "Daily buffet breakfast included",
        },
        "transport": {
            "required": True,
            "brochureTypes": ["Airport Limousine Van"],
            "brochureNotes": "Direct Penang airport pickup",
        },
        "guideActivities": {
            "required": True,
            "inclusions": [
                "Private Licensed Tour Docent",
                "Penang Hill Funicular Train Fast Lane",
            ],
            "itineraryDaysCount": 3,
        },
    },
    "packageBrochure": {
        "packageId": "pkg-penang-lux",
        "title": "Penang Luxury Island Getaway",
        "destination": "Penang",
        "durationDays": 3,
        "durationNights": 2,
    },
    "fulfillmentRecord": {
        "status": "awaiting_operator_fulfillment",
        "services": {
            "accommodation": {
                "required": True,
                "status": "unconfirmed",
                "supplierName": "Shangri-La Rasa Sayang Resort",
                "reference": "",
                "notes": "",
                "provenance": "unconfirmed_manual",
            },
            "transport": {
                "required": True,
                "status": "unconfirmed",
                "providerName": "Airport Limousine Van",
                "reference": "",
                "notes": "",
                "provenance": "unconfirmed_manual",
            },
            "guideActivities": {
                "required": True,
                "status": "unconfirmed",
                "guideOrActivity": "Private Licensed Tour Docent",
                "reference": "",
                "notes": "",
                "provenance": "unconfirmed_manual",
            },
        },
    },
}


def test_booking_detail_renders_all_required_supplier_cards(auth_client):
    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "booking": SAMPLE_BOOKING}

    with patch.dict(app.view_functions["operator_fr12.booking_detail"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get(f"/bookings/{SAMPLE_BOOKING['orderReference']}")
        assert res.status_code == 200
        html = res.get_data(as_text=True)

        # Section 2 header
        assert "Supplier Arrangements" in html
        # Accommodation card
        assert "Accommodation" in html
        assert "Shangri-La Rasa Sayang Resort" in html
        assert "Deluxe Seaview" in html
        assert "Save Accommodation" in html

        # Transport card
        assert "Transportation" in html
        assert "Airport Limousine Van" in html
        assert "Save Transport" in html

        # Guide card
        assert "Guide &amp; Activities" in html or "Guide & Activities" in html
        assert "Penang Hill Funicular Train Fast Lane" in html
        assert "Save Guide/Ticket" in html

        # Action section
        assert "Mark Arrangements Ready" in html
        assert "Unable to Fulfil" in html


def test_submit_accommodation_attestation(auth_client):
    mock_post_resp = MagicMock(ok=True)
    mock_post_resp.json.return_value = {"ok": True}

    with patch.dict(app.view_functions["operator_fr12.update_booking_fulfillment"].__globals__, {"call_api": lambda m, p, **k: mock_post_resp}) as captured:
        res = auth_client.post(
            f"/bookings/{SAMPLE_BOOKING['orderReference']}/fulfillment",
            data={
                "serviceType": "accommodation",
                "supplierName": "Shangri-La Rasa Sayang Resort",
                "reference": "SHANG-PEN-90123",
                "notes": "Confirmed high floor room",
            },
            follow_redirects=False,
        )
        assert res.status_code == 302
        assert f"/bookings/{SAMPLE_BOOKING['orderReference']}" in res.headers["Location"]


def test_submit_confirm_fulfillment(auth_client):
    mock_post_resp = MagicMock(ok=True)
    mock_post_resp.json.return_value = {"ok": True}

    with patch.dict(app.view_functions["operator_fr12.confirm_booking_fulfillment"].__globals__, {"call_api": lambda m, p, **k: mock_post_resp}):
        res = auth_client.post(
            f"/bookings/{SAMPLE_BOOKING['orderReference']}/confirm-fulfillment",
            follow_redirects=False,
        )
        assert res.status_code == 302
        assert f"/bookings/{SAMPLE_BOOKING['orderReference']}" in res.headers["Location"]


def test_submit_decline_fulfillment(auth_client):
    mock_post_resp = MagicMock(ok=True)
    mock_post_resp.json.return_value = {"ok": True}

    with patch.dict(app.view_functions["operator_fr12.decline_booking_fulfillment"].__globals__, {"call_api": lambda m, p, **k: mock_post_resp}):
        res = auth_client.post(
            f"/bookings/{SAMPLE_BOOKING['orderReference']}/decline",
            data={"reason": "Hotel is fully booked during festival dates."},
            follow_redirects=False,
        )
        assert res.status_code == 302
        assert f"/bookings/{SAMPLE_BOOKING['orderReference']}" in res.headers["Location"]


def test_bookings_list_renders_trip_ready_and_attested_badges(auth_client):
    ready_booking = dict(SAMPLE_BOOKING)
    ready_booking["fulfillmentStatus"] = "trip_ready"
    ready_booking["supplierReservationStatus"] = "operator_attested"

    mock_resp = MagicMock(ok=True)
    mock_resp.json.return_value = {"ok": True, "items": [ready_booking]}

    with patch.dict(app.view_functions["operator_fr12.bookings"].__globals__, {"call_api": lambda m, p, **k: mock_resp}):
        res = auth_client.get("/bookings")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Trip Ready" in html
        assert "Arrangements Recorded (Operator)" in html


@pytest.mark.parametrize('ready,uncertain,disabled', [(False,False,True),(True,True,True),(True,False,False)])
def test_readiness_action_requires_complete_attestation(auth_client, ready, uncertain, disabled):
    from copy import deepcopy
    import re
    booking = deepcopy(SAMPLE_BOOKING)
    for service in booking['fulfillmentRecord']['services'].values():
        if ready:
            service.update(status='confirmed',reference='supplier-ref',provenance='operator_attested',confirmedBy='op',confirmedAt='2026-11-08T10:00:00Z')
    booking['requiredServices']['accommodation']['uncertain'] = uncertain
    booking['readiness'] = {'canMarkReady':not disabled, 'blockers':[] if not disabled else ['Required supplier records are incomplete.'], 'components':[], 'requiredCount':3, 'completedCount':3 if ready else 0, 'requirementsReliable':not uncertain}
    response = MagicMock(ok=True)
    response.json.return_value = {'ok':True,'booking':booking}
    with patch.dict(app.view_functions['operator_fr12.booking_detail'].__globals__, {'call_api':lambda *a, **kw:response}):
        page = auth_client.get('/bookings/ord-penang-fulfillment')
    assert page.status_code == 200
    button = re.search(r'<button[^>]*id="confirm-fulfillment-btn"[^>]*>', page.get_data(as_text=True)).group(0)
    assert ('disabled' in button) is disabled


@pytest.mark.parametrize('reliable,count,complete,message', [
    (False,0,0,'Supplier requirements need review'),
    (True,0,0,'No external arrangements required'),
    (True,1,0,'0 / 1 required arrangements complete'),
    (True,3,0,'0 / 3 required arrangements complete'),
    (True,3,3,'3 / 3 required arrangements complete'),
])
def test_fulfillment_summary_matches_backend_requirement_state(auth_client,reliable,count,complete,message):
    from copy import deepcopy
    booking = deepcopy(SAMPLE_BOOKING)
    booking['readiness'] = {'canMarkReady':reliable and complete == count,'blockers':[],
        'components':[{'label':'Accommodation','required':count > 0,'complete':complete > 0,'uncertain':not reliable}],
        'requirementsReliable':reliable,'requiredCount':count,'completedCount':complete}
    response = MagicMock(ok=True)
    response.json.return_value = {'ok':True,'booking':booking}
    with patch.dict(app.view_functions['operator_fr12.booking_detail'].__globals__,{'call_api':lambda *a,**kw:response}):
        page = auth_client.get('/bookings/ord-penang-fulfillment')
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and message in html
    assert '0 / 0' not in html and 'required records complete' not in html
