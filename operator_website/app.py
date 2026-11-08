import os
import sys
from pathlib import Path
from flask import Flask, jsonify
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portal_security_config import configure_portal_app, env_flag
from modules.fr01_user_management.routes import bp as fr01
from modules.fr12_tourism_operator_management.routes import bp as fr12

load_dotenv()
app = Flask(__name__)
from portal_commerce import register_commerce_presentation
register_commerce_presentation(app)
configure_portal_app(app, "travelmate_operator_session", "operator")
app.register_blueprint(fr01)
app.register_blueprint(fr12)


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "TravelMate Operator Portal"})

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5001")),
        debug=env_flag("FLASK_DEBUG"),
    )
