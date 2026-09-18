import os
from flask import Flask
from dotenv import load_dotenv
from modules.fr01_user_management import bp as fr01
from modules.fr13_administrator_management import bp as fr13

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")
app.config["SESSION_COOKIE_NAME"] = "travelmate_admin_session"
app.register_blueprint(fr01)
app.register_blueprint(fr13)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5002")), debug=True)
