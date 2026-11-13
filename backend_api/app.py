import os
import sys
import ipaddress
import re
from base64 import b64encode
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, abort, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from firebase_service import get_db, init_firebase
from auth_utils import auth_required
from services.stripe_service import stripePaymentMode
from services.local_lan import load_lan_signer, local_lan_networks, local_lan_origins
from request_rate_limit import init_rate_limiter

load_dotenv()


def _truthy(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _allowed_cors_origins():
    origins = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if "*" in origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must list explicit browser origins; wildcard is not allowed")
    return origins


def create_app():
    app = Flask(__name__)
    networks = local_lan_networks()
    lan_origins = local_lan_origins(networks)
    lan_sign = load_lan_signer(os.getenv("LOCAL_LAN_IDENTITY_KEY", "")) if lan_origins else None
    app.config["LOCAL_LAN_ORIGINS"] = lan_origins
    app.config["LOCAL_FYP_SAMPLE_REVIEWS"] = bool(networks)
    if networks:
        @app.before_request
        def allow_only_trusted_lan():
            try:
                peer = ipaddress.ip_address(request.remote_addr or "")
            except ValueError:
                abort(403)
            if peer.is_loopback or any(peer in network for network in networks):
                return None
            abort(403)
    init_rate_limiter(app, db_factory=get_db)
    origins = _allowed_cors_origins()
    if origins:
        CORS(app, origins=origins, supports_credentials=False)
    init_firebase()

    from modules.fr01_user_management import bp as fr01
    from modules.fr02_travel_preference import bp as fr02
    from modules.fr03_destination_search_information import bp as fr03
    from modules.fr04_hybrid_recommendation import bp as fr04
    from modules.fr05_smart_itinerary_budget_planner import bp as fr05
    from modules.fr06_weather_forecast import bp as fr06
    from modules.fr07_flight_search import bp as fr07
    from modules.fr08_hotel_booking import bp as fr08
    from modules.fr09_payment import bp as fr09
    from modules.fr10_feedback_rating import bp as fr10
    from modules.fr11_chatbot_travel_assistant import bp as fr11
    from modules.fr12_tourism_operator_management import bp as fr12
    from modules.fr13_administrator_management import bp as fr13
    from modules.fr15_package_checkout import bp as fr15
    from modules.shared_public_content import bp as public_content
    from modules.traveller_notifications import bp as notifications

    for blueprint in [fr01, fr02, fr03, fr04, fr05, fr06, fr07, fr08, fr09, fr10, fr11, fr12, fr13, fr15, public_content, notifications]:
        app.register_blueprint(blueprint)

    @app.get("/api/health")
    def health():
        from services.package_checkout_contract import SUPPLIER_REQUIREMENT_VERSION
        payload = {"ok": True, "service": "TravelMate Backend API",
                   "recommendationContract": "relevant_v1",
                   "packageRequirementsContract": f"supplier_v{SUPPLIER_REQUIREMENT_VERSION}"}
        nonce = request.args.get("lanChallenge")
        if nonce is None:
            return jsonify(payload)
        origin = f"http://{request.host}"
        if not lan_sign or origin not in lan_origins:
            abort(404)
        if not re.fullmatch(r"[0-9a-f]{64}", nonce):
            abort(400)
        payload["lanProof"] = b64encode(lan_sign(origin, nonce)).decode("ascii")
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/config-status")
    @auth_required(['admin'])
    def config_status():
        fallback = _truthy("FALLBACK_MODE")
        hotel_live = bool(os.getenv("LITEAPI_KEY", "").strip())
        sample = _truthy("HOTEL_SAMPLE_MODE") or (_truthy("TRAVELMATE_TESTING") and fallback)
        transaction = os.getenv("HOTEL_TRANSACTION_MODE", "local_demo").strip().lower()
        if transaction not in {"local_demo", "provider_sandbox"}:
            transaction = "local_demo"
        return jsonify({
            "ok": True,
            "paymentMode": stripePaymentMode(),
            "hotelMode": "live" if hotel_live else ("sample" if sample else "unavailable"),
            "hotelContentMode": "provider" if hotel_live else ("sample_fixture" if sample else "unavailable"),
            "hotelRateMode": "live_quote" if hotel_live else ("sample_fixture" if sample else "unavailable"),
            "hotelTransactionMode": transaction,
        })

    return app


if __name__ == "__main__":
    app = create_app()
    bind_host = "0.0.0.0" if local_lan_networks() else "127.0.0.1"
    app.run(
        host=bind_host,
        port=int(os.getenv("PORT", "5000")),
        debug=_truthy("FLASK_DEBUG"),
    )
