import os
from flask import Flask
from dotenv import load_dotenv
from modules.fr01_user_management.routes import bp as fr01
from modules.fr12_tourism_operator_management.routes import bp as fr12

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")
app.config["SESSION_COOKIE_NAME"] = "travelmate_operator_session"
app.register_blueprint(fr01)
app.register_blueprint(fr12)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5001")), debug=True)
