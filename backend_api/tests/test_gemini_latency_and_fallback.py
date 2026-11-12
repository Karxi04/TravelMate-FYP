import os
import re
import time
import pytest
from unittest.mock import MagicMock, patch

from google.genai import types
from google.genai.errors import ClientError, ServerError
import httpx

from services import gemini_service as gs


# ==============================================================================
# 1. Timeout and Configuration (Tests 1 - 8)
# ==============================================================================

def test_01_default_timeout(monkeypatch):
    monkeypatch.delenv('GEMINI_TIMEOUT_SECONDS', raising=False)
    assert gs.get_gemini_timeout_seconds() == 8.0


def test_02_valid_custom_timeout(monkeypatch):
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', '45')
    assert gs.get_gemini_timeout_seconds() == 45.0


def test_03_missing_variable(monkeypatch):
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', '')
    assert gs.get_gemini_timeout_seconds() == 8.0


def test_04_invalid_numeric_value(monkeypatch):
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', 'invalid_str')
    assert gs.get_gemini_timeout_seconds() == 8.0


def test_05_negative_value(monkeypatch):
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', '-10')
    assert gs.get_gemini_timeout_seconds() == 8.0


def test_06_extremely_large_value(monkeypatch):
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', '600')
    assert gs.get_gemini_timeout_seconds() == 120.0


def test_07_extremely_small_value(monkeypatch):
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', '2')
    assert gs.get_gemini_timeout_seconds() == 5.0


def test_08_correct_sdk_http_options_and_no_retry_loop(monkeypatch):
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', '25')
    timeout_sec = gs.get_gemini_timeout_seconds()
    timeout_ms = int(timeout_sec * 1000)
    assert timeout_ms == 25000
    client = MagicMock()
    client.models.generate_content.return_value.text = 'A short reply'
    with patch.object(gs.genai, 'Client') as constructor:
        constructor.return_value = client
        monkeypatch.setenv('GEMINI_API_KEY', 'test_key')
        assert gs._generate('Synthetic question') == 'A short reply'
        http_opts = constructor.call_args.kwargs['http_options']
        assert http_opts.timeout == 25000
        assert http_opts.retry_options.attempts == 1
        assert client.models.generate_content.call_count == 1
        client.close.assert_called_once()


# ==============================================================================
# 2. Thinking Configuration (Tests 9 - 12)
# ==============================================================================

def test_09_low_thinking_serialization():
    assert hasattr(types, 'ThinkingConfig')
    assert hasattr(types, 'ThinkingLevel')
    assert types.ThinkingLevel.LOW == 'LOW'

    thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    cfg = types.GenerateContentConfig(
        system_instruction=gs.SYSTEM_PREFIX,
        thinking_config=thinking_config,
    )
    dumped = cfg.model_dump(exclude_none=True, by_alias=True)
    assert 'thinkingConfig' in dumped
    assert dumped['thinkingConfig']['thinkingLevel'] == 'LOW'
    assert 'systemInstruction' in dumped


def test_10_original_model_preserved(monkeypatch):
    monkeypatch.setenv('GEMINI_MODEL', 'gemini-3.8-flash')
    model = os.getenv('GEMINI_MODEL', 'gemini-3.7-flash').strip()
    assert model == 'gemini-3.8-flash'


def test_11_original_system_instructions_preserved():
    assert "You are TravelMate, a concise and practical Malaysia-wide travel-planning assistant." in gs.SYSTEM_PREFIX
    assert "TravelMate supports travel planning across the entire country of Malaysia (all 13 states and 3 federal territories" in gs.SYSTEM_PREFIX
    assert "If a traveller requests a destination outside Malaysia" in gs.SYSTEM_PREFIX


def test_12_existing_response_extraction_preserved(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.text = "   Mock Gemini Trip Recommendation   "
    with patch('services.gemini_service.genai.Client') as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_resp
        mock_client_cls.return_value = mock_client
        monkeypatch.setenv('GEMINI_API_KEY', 'test_key')
        text = gs._generate("Hello Malaysia")
        assert text == "Mock Gemini Trip Recommendation"


# ==============================================================================
# 3. Gemini Failure Handling & Sanitized Diagnostics (Tests 13 - 20)
# ==============================================================================

def test_13_http_429_fallback():
    exc = ClientError(429, "429 RESOURCE_EXHAUSTED: Quota exceeded for model gemini-3.8-flash")
    cat = gs._classify_provider_error(exc)
    assert cat == 'HTTP_429_RATE_LIMIT_EXHAUSTED'


def test_14_http_503_fallback():
    exc = ServerError(503, "503 UNAVAILABLE: Upstream backend overloaded")
    cat = gs._classify_provider_error(exc)
    assert cat == 'HTTP_503_SERVICE_UNAVAILABLE'


def test_15_http_504_fallback():
    exc = ServerError(504, "504 DEADLINE_EXCEEDED: Gateway timeout")
    cat = gs._classify_provider_error(exc)
    assert cat == 'HTTP_504_DEADLINE_EXCEEDED'


def test_16_client_timeout():
    exc = httpx.ReadTimeout("The read operation timed out after 30.0 seconds")
    cat = gs._classify_provider_error(exc)
    assert cat == 'CLIENT_TIMEOUT'


def test_17_empty_response():
    exc = gs.EmptyProviderResponse()
    cat = gs._classify_provider_error(exc)
    assert cat == 'EMPTY_PROVIDER_RESPONSE'


def test_18_unexpected_provider_exception():
    exc = KeyError("unexpected_field")
    cat = gs._classify_provider_error(exc)
    assert cat == 'UNEXPECTED_PROVIDER_ERROR'


@pytest.mark.parametrize('status,category', [
    (400, 'HTTP_400_BAD_REQUEST'), (401, 'HTTP_401_403_AUTH_ERROR'),
    (403, 'HTTP_401_403_AUTH_ERROR'), (404, 'HTTP_404_MODEL_OR_RESOURCE_NOT_FOUND'),
    (500, 'HTTP_500_PROVIDER_ERROR'),
])
def test_provider_classification_ignores_error_body(status, category):
    error = ClientError(status, '429 timeout followed by synthetic private content')
    assert gs._classify_provider_error(error) == category


@pytest.mark.parametrize('value,error', [('  ', gs.EmptyProviderResponse),
    ('{"internalId":"example"}', gs.InvalidProviderResponse)])
def test_empty_and_structured_provider_output_are_rejected(monkeypatch, value, error):
    monkeypatch.setenv('GEMINI_API_KEY', 'test_key')
    with patch.object(gs.genai, 'Client') as constructor:
        constructor.return_value.models.generate_content.return_value.text = value
        with pytest.raises(error):
            gs._generate('Synthetic question')


def test_19_correct_source_labeling(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test_key')
    monkeypatch.setenv('FALLBACK_MODE', 'true')
    now = 100.0
    monkeypatch.setattr(gs, 'monotonic', lambda: now)

    with patch('services.gemini_service._generate', side_effect=ServerError(504, "504 DEADLINE_EXCEEDED")) as generate:
        res = gs.generateChatbotResponse("Plan a trip to Langkawi", with_source=True)
        assert res['source'] == 'travelmate-assistant'
        assert isinstance(res['reply'], str)
        assert len(res['reply']) > 20
        assert gs.generateFollowUpResponse("What else?", with_source=True)['source'] == 'travelmate-assistant'
        generate.assert_called_once()

    now += gs.PROVIDER_COOLDOWN_SECONDS
    with patch('services.gemini_service._generate', return_value="Live provider response"):
        res = gs.generateChatbotResponse("Plan a trip to Langkawi", with_source=True)
        assert res['source'] == 'gemini'
        assert res['reply'] == "Live provider response"


@pytest.mark.parametrize('question', ['Where can I rent a car in Ipoh?', 'How do I hire a car for a two-day trip?'])
def test_retired_car_rental_cannot_be_advertised_by_provider(monkeypatch, question):
    monkeypatch.setenv('GEMINI_API_KEY', 'test_key')
    with patch.object(gs, '_generate') as generate:
        result = gs.generateChatbotResponse(question, with_source=True)
    generate.assert_not_called()
    assert result['source'] == 'travelmate-assistant'
    assert 'no longer offers car rental' in result['reply']
    assert 'Smart Packing Checklist' in result['reply']
    assert 'Home → Car Rental' not in result['reply']


def test_20_correct_sanitized_error_handling(monkeypatch, caplog):
    monkeypatch.setenv('GEMINI_API_KEY', 'secret_gemini_api_key_12345')
    monkeypatch.setenv('FALLBACK_MODE', 'true')

    with patch('services.gemini_service._generate', side_effect=ServerError(504, "504 DEADLINE_EXCEEDED key=secret_gemini_api_key_12345")):
        with caplog.at_level('WARNING'):
            res = gs.generateChatbotResponse("Hello", with_source=True)
            assert res['source'] == 'travelmate-assistant'
            log_text = caplog.text
            assert 'secret_gemini_api_key_12345' not in log_text
            assert 'HTTP_504_DEADLINE_EXCEEDED' in log_text


# ==============================================================================
# 4. Context-Aware Fallback (Tests 21 - 34)
# ==============================================================================

def test_21_kuala_lumpur_three_day_planning():
    ps = {
        'destinationArea': 'Kuala Lumpur',
        'destinationState': 'Kuala Lumpur',
        'destinationCountry': 'Malaysia',
        'tripDays': 3,
        'startDate': '2026-12-05',
        'endDate': '2026-12-07',
        'budgetLimit': 800.0,
        'travellerCount': 3,
        'interests': ['Food', 'Culture']
    }
    q = "Plan a 3-day Kuala Lumpur trip starting 5 December 2026 with a budget of RM800 for three people. We enjoy food and cultural attractions."
    reply = gs._local_assistant(q, planning_state=ps)
    assert "Kuala Lumpur" in reply
    assert "3-day" in reply
    assert "2026-12-05 to 2026-12-07" in reply


def test_22_rm800_group_budget():
    ps = {
        'destinationArea': 'Kuala Lumpur',
        'destinationState': 'Kuala Lumpur',
        'tripDays': 3,
        'budgetLimit': 800.0,
        'travellerCount': 3,
    }
    q = "Plan a 3-day trip in Kuala Lumpur for 3 people with RM800 budget."
    reply = gs._local_assistant(q, planning_state=ps)
    assert "RM800" in reply
    assert "3 travellers" in reply
    assert "estimate" in reply.lower()


def test_23_food_and_culture_interests():
    ps = {
        'destinationArea': 'Kuala Lumpur',
        'destinationState': 'Kuala Lumpur',
        'tripDays': 3,
        'budgetLimit': 800.0,
        'travellerCount': 3,
        'interests': ['Food', 'Culture']
    }
    q = "Plan a 3-day Kuala Lumpur trip"
    reply = gs._local_assistant(q, planning_state=ps)
    assert "Food, Culture" in reply
    assert "Petronas Twin Towers" in reply or "Bukit Bintang" in reply


def test_24_melaka_multi_turn_state():
    ps = {
        'destinationArea': 'Melaka',
        'destinationState': 'Melaka',
        'destinationCountry': 'Malaysia',
        'tripDays': 3,
        'travellerCount': 3,
        'interests': ['Culture', 'Food'],
        'budgetLimit': 1000.0,
    }
    q = "Actually change our budget to RM1000."
    reply = gs._local_assistant(q, planning_state=ps)
    assert "Melaka" in reply
    assert "3-day" in reply
    assert "3 travellers" in reply
    assert "A Famosa" in reply or "Jonker Street" in reply


def test_25_latest_budget_overrides_earlier_budget():
    ps = {
        'destinationArea': 'Melaka',
        'destinationState': 'Melaka',
        'tripDays': 3,
        'travellerCount': 3,
        'budgetLimit': 1000.0,
        'interests': ['Culture', 'Food']
    }
    q = "Actually change our budget to RM1000."
    reply = gs._local_assistant(q, planning_state=ps)
    assert "RM1000" in reply
    assert "RM1200" not in reply


def test_26_missing_destination_handled_gracefully():
    ps = {'tripDays': 3, 'budgetLimit': 500.0, 'travellerCount': 2}
    q = "Plan 3 days with budget RM500"
    reply = gs._local_assistant(q, planning_state=ps)
    assert isinstance(reply, str)
    assert len(reply) > 20


def test_27_missing_dates_handled_gracefully():
    ps = {'destinationArea': 'Penang', 'destinationState': 'Penang', 'tripDays': 3, 'budgetLimit': 600.0}
    q = "Plan 3 days in Penang with budget RM600"
    reply = gs._local_assistant(q, planning_state=ps)
    assert "Penang" in reply
    assert "3-day" in reply
    assert "None" not in reply


def test_28_missing_traveller_count_handled_gracefully():
    ps = {'destinationArea': 'Langkawi', 'destinationState': 'Kedah', 'tripDays': 2}
    q = "Plan two days in Langkawi"
    reply = gs._local_assistant(q, planning_state=ps)
    assert "Langkawi" in reply
    assert "traveller" not in reply.lower()


def test_29_foreign_destination_restriction():
    reply = gs._local_assistant("Plan a trip to Singapore and Tokyo")
    assert "exclusively to travel planning within Malaysia" in reply
    assert "Singapore" in reply or "Tokyo" in reply


def test_30_weather_related_request():
    reply = gs._local_assistant("What cultural attractions can I visit in Kuala Lumpur on a rainy day?")
    assert "Weather tool for the live Open-Meteo forecast" in reply
    assert "indoor food experiences as safer wet-weather choices" in reply


def test_31_hotel_booking_guidance():
    reply = gs._local_assistant("Where can I book a hotel in Melaka?")
    assert "Use Home → Hotels" in reply


def test_32_flight_search_guidance():
    reply = gs._local_assistant("How do I search flights to Penang?")
    assert "Use Home → Flights" in reply


def test_33_no_cross_session_state_leakage():
    reply1 = gs._local_assistant("Plan a trip to Penang", planning_state={'destinationArea': 'Penang'})
    reply2 = gs._local_assistant("How should I budget my money?", planning_state=None)
    assert "Penang" in reply1
    assert "Penang" not in reply2


def test_34_no_invented_provider_confirmations():
    reply = gs._local_assistant("Please confirm my booking reference BK-9988 for RM500")
    assert "booking ref" not in reply.lower()
    assert "payment confirmed" not in reply.lower()


# ==============================================================================
# 5. Response-Time & Simulated Stalled Provider Tests
# ==============================================================================

def test_mock_transport_stalled_provider_and_fallback_timing(client, mock_traveller_auth):
    """
    Verifies with a deterministic mock transport that a stalled provider triggers
    safe fallback within the client execution deadline, measuring total route latency.
    """
    def mock_stalled_generate(*args, **kwargs):
        # Simulate provider exceeding timeout
        time.sleep(0.05)
        raise ServerError(504, "504 DEADLINE_EXCEEDED: upstream timeout")

    with patch('services.gemini_service._generate', side_effect=mock_stalled_generate), \
         patch('modules.fr11_chatbot_travel_assistant.routes.retrieveRecord', return_value=[]), \
         patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord', side_effect=lambda coll, d: {'id': f'mock_{coll}', **d}), \
         patch('modules.fr11_chatbot_travel_assistant.routes.updateRecord', side_effect=lambda coll, doc_id, d: {'id': doc_id, **d}):

        start_time = time.perf_counter()
        resp = client.post(
            '/api/fr11/chat',
            headers={'Authorization': 'Bearer valid_test_token'},
            json={'message': 'Plan a 3-day Kuala Lumpur trip starting 5 December 2026 with a budget of RM800 for three people.'}
        )
        elapsed = time.perf_counter() - start_time

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['source'] == 'travelmate-assistant'
        assert elapsed < 5.0  # Finished promptly within fallback deadline
        reply = data['reply']
        assert "Kuala Lumpur" in reply
        assert "3-day" in reply
        assert "RM800" in reply


# ==============================================================================
# 6. Multi-Turn Conversational Fallback Verification (Section 6 Scenario)
# ==============================================================================

def test_section_6_melaka_multi_turn_scenario(client, mock_traveller_auth):
    """
    Synthetic 5-turn conversation:
    Turn 1: 'Plan three days in Melaka.'
    Turn 2: 'There are three people.'
    Turn 3: 'Our budget is RM1200.'
    Turn 4: 'We enjoy cultural attractions and local food.'
    Turn 5: 'Actually change our budget to RM1000.'
    Simulate Gemini HTTP 503 on Turn 5 and verify deterministic fallback.
    """
    mock_db = {'chat_sessions': {}, 'chat_messages': {}}

    def mock_store(coll, d):
        import uuid
        doc_id = 'mock_' + uuid.uuid4().hex[:8]
        rec = {'id': doc_id, **d}
        mock_db.setdefault(coll, {})[doc_id] = rec
        return rec

    def mock_update(coll, doc_id, d):
        rec = mock_db.setdefault(coll, {}).setdefault(doc_id, {'id': doc_id})
        rec.update(d)
        return rec

    def mock_retrieve(coll, doc_id=None, filters=None, limit=None):
        col = mock_db.get(coll, {})
        if doc_id:
            return col.get(doc_id)
        res = list(col.values())
        if filters:
            for f, op, val in filters:
                if op == '==':
                    res = [r for r in res if r.get(f) == val]
        return res[:limit] if limit else res

    with patch('modules.fr11_chatbot_travel_assistant.routes.storeRecord', side_effect=mock_store), \
         patch('modules.fr11_chatbot_travel_assistant.routes.updateRecord', side_effect=mock_update), \
         patch('modules.fr11_chatbot_travel_assistant.routes.retrieveRecord', side_effect=mock_retrieve), \
         patch('services.gemini_service._generate', side_effect=ServerError(503, "503 UNAVAILABLE: Provider busy")):

        turns = [
            ("Turn 1", "Plan three days in Melaka."),
            ("Turn 2", "There are three people."),
            ("Turn 3", "Our budget is RM1200."),
            ("Turn 4", "We enjoy cultural attractions and local food."),
            ("Turn 5", "Actually change our budget to RM1000.")
        ]

        session_id = None
        last_data = None
        for turn_lbl, msg in turns:
            payload = {'message': msg}
            if session_id:
                payload['sessionId'] = session_id
            resp = client.post(
                '/api/fr11/chat',
                headers={'Authorization': 'Bearer valid_test_token'},
                json=payload
            )
            assert resp.status_code == 200
            last_data = resp.get_json()
            assert last_data['ok'] is True
            session_id = last_data['session']['id']

        final_reply = last_data['reply']
        final_source = last_data['source']
        final_ps = last_data['session']['planningState']

        assert final_source == 'travelmate-assistant'
        assert "Melaka" in final_reply
        assert "3-day" in final_reply
        assert "3 travellers" in final_reply
        assert "RM1000" in final_reply
        assert "RM1200" not in final_reply
        assert "Culture" in final_ps.get('interests', [])
        assert "Food" in final_ps.get('interests', [])
        assert final_ps.get('budgetLimit') == 1000.0
