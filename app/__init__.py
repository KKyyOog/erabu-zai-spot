import os

from flask import Flask

from app.routes.materials import materials_bp
from app.routes.users import users_bp
from app.routes.link import link_bp
from app.routes.callback import callback_bp
from app.routes.admin import admin_bp
from app.config import Config


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    app.register_blueprint(materials_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(link_bp)
    app.register_blueprint(callback_bp)
    app.register_blueprint(admin_bp)

    @app.context_processor
    def inject_liff_id():
        return {"LIFF_ID": app.config["LIFF_ID"]}

    @app.route("/")
    def index():
        return "えらぶ材すぽっと is running."

    return app
