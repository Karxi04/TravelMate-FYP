import os
import sys
from pathlib import Path
from flask import Flask
from dotenv import load_dotenv
from modules.fr01_user_management import bp as fr01
from modules.fr13_administrator_management import bp as fr13

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from portal_security_config import configure_portal_app, env_flag

load_dotenv()
app = Flask(__name__)
configure_portal_app(app, "travelmate_admin_session", "admin")
app.register_blueprint(fr01)
app.register_blueprint(fr13)

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5002")),
        debug=env_flag("FLASK_DEBUG"),
    )
