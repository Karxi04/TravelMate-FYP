import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from firebase_service import init_firebase
from auth_utils import auth_required
from services.stripe_service import stripePaymentMode
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
    init_rate_limiter(app)
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
    from modules.shared_public_content import bp as public_content

    for blueprint in [fr01, fr02, fr03, fr04, fr05, fr06, fr07, fr08, fr09, fr10, fr11, fr12, fr13, public_content]:
        app.register_blueprint(blueprint)

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "service": "TravelMate Backend API"})

    @app.get("/api/config-status")
    @auth_required(['admin'])
    def config_status():
        fallback = _truthy("FALLBACK_MODE")
        hotel_live = bool(os.getenv("LITEAPI_KEY", "").strip())
        return jsonify({
            "ok": True,
            "paymentMode": stripePaymentMode(),
            "hotelMode": "live" if hotel_live else ("fallback" if fallback else "unavailable"),
        })

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=_truthy("FLASK_DEBUG"),
    )
